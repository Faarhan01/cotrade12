"""
server — Live Streams
=======================
Server-Sent Events for continuous market data.

SSE over plain HTTP is the right fit here: it needs no extra dependency, it
survives proxies, and an agent or script can consume it with any HTTP client
or an EventSource in a browser. WebSocket would add a protocol layer for no
benefit against a feed that is one-directional.

Streams:
  /stream/ticks        - poll ticks for a symbol set on an interval
  /stream/marketbook   - poll depth of market on an interval
  /stream/portfolio    - account plus open positions, for PnL monitoring
"""

import json
import threading
import time
from typing import Iterator

from server import validation as v
from server.errors import BadRequest

DEFAULT_INTERVAL = 1.0
MIN_INTERVAL = 0.2
MAX_INTERVAL = 60.0
HEARTBEAT_SECONDS = 15.0


def _clamp_interval(value, default: float = DEFAULT_INTERVAL) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_INTERVAL, min(interval, MAX_INTERVAL))


def _format_event(data: dict, event: str = "message") -> bytes:
    """Encode one SSE frame."""
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _format_retry(seconds: float) -> bytes:
    """Tell the client how long to wait before reconnecting."""
    return f"retry: {int(seconds * 1000)}\n\n".encode("utf-8")


def _format_comment(text: str) -> bytes:
    """An SSE comment, used as a keepalive the client ignores."""
    return f": {text}\n\n".encode("utf-8")


class EventStream:
    """
    Drives a generator of events for one streaming connection.

    The handler owns the socket; this only produces bytes and stops cleanly
    when the client disconnects or the connection is lost.
    """

    def __init__(self, handler, interval: float, source: str):
        self.handler = handler
        self.interval = interval
        self.source = source
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _alive(self) -> bool:
        """False once the client has gone away."""
        if self._stop.is_set():
            return False
        return not self.handler._client_gone

    def run(self, producer) -> Iterator[bytes]:
        """
        Yield SSE frames from `producer` until the client disconnects.

        `producer` is called once per tick and returns a dict to emit, or None
        to skip. Errors are emitted as an `error` frame rather than tearing the
        stream down, so a transient MT5 hiccup does not lose the subscription.
        """
        yield _format_retry(MAX_INTERVAL)
        yield _format_event(
            {
                "source": self.source,
                "interval": self.interval,
                "status": "streaming",
            },
            event="open",
        )

        last_beat = time.monotonic()
        while self._alive():
            started = time.monotonic()
            try:
                payload = producer()
            except Exception as exc:  # noqa: BLE001 - report and keep the stream alive
                yield _format_event(
                    {"source": self.source, "error": str(exc),
                     "type": type(exc).__name__},
                    event="error",
                )
            else:
                if payload is not None:
                    yield _format_event(payload, event=self.source)

            # Keepalive so idle connections are not reaped by the client or proxy.
            now = time.monotonic()
            if now - last_beat >= HEARTBEAT_SECONDS:
                yield _format_comment("keepalive")
                last_beat = now

            # Sleep out the rest of the interval, waking early if asked to stop.
            elapsed = time.monotonic() - started
            self._stop.wait(max(self.interval - elapsed, 0.05))

        yield _format_event({"source": self.source, "status": "closed"}, event="close")


# ─── Producers ────────────────────────────────────────────────────────


def tick_producer(engine, symbols: list, book: bool = False):
    """
    Emit a tick for each symbol on every pass.

    Only symbols whose price actually moved are emitted, so a quiet market
    does not flood the client with unchanged values. The first pass always
    sends so the client has a starting point.

    Timestamps are labelled by origin. MT5 reports broker server time, which on
    this account ran ~30s ahead of the daemon's own clock; emitting both under
    a bare "time" key would let a consumer compare them and conclude the tick
    came from the future.
    """
    last = {}

    def produce():
        payload = {}
        for name in symbols:
            try:
                tick = engine.get_tick(name)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the feed
                payload[name] = {"error": str(exc)}
                continue

            changed = (
                name not in last
                or last[name].get("bid") != tick.get("bid")
                or last[name].get("ask") != tick.get("ask")
            )
            if changed:
                entry = {"symbol": name, **tick}
                if book:
                    try:
                        entry["book"] = engine.market_book.get(name)
                    except Exception:  # noqa: BLE001 - book is supplementary
                        entry["book"] = None
                payload[name] = entry
            last[name] = tick

        if not payload:
            return None
        return {
            "sent_at_utc": time.time(),
            "time_source": "broker server time (see tick.time_msc); "
                           "sent_at_utc is this daemon's clock",
            "symbols": payload,
        }

    return produce


def marketbook_producer(engine, symbols: list):
    """Emit the depth of market on every pass."""
    def produce():
        books = {}
        for name in symbols:
            try:
                books[name] = engine.market_book.get(name)
            except Exception as exc:  # noqa: BLE001
                books[name] = {"error": str(exc)}
        return {"sent_at_utc": time.time(), "books": books}

    return produce


def portfolio_producer(engine, include_book: bool = False):
    """
    Emit account and open positions together, so a client can track live PnL
    without issuing two separate polls per tick.
    """
    def produce():
        account = engine.get_account_info()
        positions = engine.get_positions()
        payload = {
            "sent_at_utc": time.time(),
            "time_source": "broker server time",
            "balance": account.get("balance"),
            "equity": account.get("equity"),
            "margin": account.get("margin"),
            "margin_free": account.get("margin_free"),
            "currency": account.get("currency"),
            "position_count": len(positions),
            "floating_profit": round(sum(p.get("profit", 0.0) for p in positions), 2),
            "positions": positions,
        }
        if include_book:
            payload["books"] = {
                p["symbol"]: engine.market_book.get(p["symbol"]) for p in positions
            }
        return payload

    return produce


# ─── Parameter parsing ────────────────────────────────────────────────


def stream_params(query) -> tuple:
    """
    Pull (symbols, interval, extras) out of a stream request's query string.

    symbols defaults to whatever is open, so the common case - watch my
    positions - needs no parameters at all.
    """
    names = v.symbol_list(query.get("symbols"))
    interval = _clamp_interval(query.get("interval"))
    extras = v.boolean(query.get("book"), default=False)
    return names, interval, extras


def require_symbols(query, engine) -> list:
    names = v.symbol_list(query.get("symbols"))
    if names:
        return names
    # Fall back to open positions, then to a single liquid default.
    positions = engine.get_positions()
    if positions:
        seen = []
        for pos in positions:
            if pos["symbol"] not in seen:
                seen.append(pos["symbol"])
        return seen
    raise BadRequest(
        "'symbols' is required when nothing is open, "
        "e.g. ?symbols=EURUSD,GBPUSD"
    )
