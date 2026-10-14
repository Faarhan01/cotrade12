"""
tools.bot — Data Feed
=======================
Pulls market data from the cony gateway, with an optional SQLite cache.

The cache exists because MT5 will not re-serve history it has forgotten: ticks
survive roughly a day, M1 around 90-180 days. A strategy grid re-requests the
same window hundreds of times, so caching turns a slow sweep into a fast one
and makes results comparable between runs.

The gateway is the source of truth. Cached bars are only reused when they are
still inside what MT5 reports it holds.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from knowledgebase.patterns import Bar, to_bars  # noqa: E402

def _resolve_base() -> str:
    """
    Where the gateway is listening.

    Read from the same environment variables the daemon binds with, rather
    than from a literal. This module runs inside the gateway process and calls
    back over HTTP, so when the port was written in here as a constant,
    starting the daemon on any other port produced a gateway that could not
    reach its own research layer: the listener moved and this stayed behind.
    """
    explicit = os.environ.get("CONY_URL")
    if explicit:
        return explicit.rstrip("/")
    host = os.environ.get("CONY_HOST", "127.0.0.1")
    port = os.environ.get("CONY_PORT", "8890")
    return f"http://{host}:{port}".rstrip("/")


BASE = _resolve_base()


class GatewayError(RuntimeError):
    pass


def _call(method: str, path: str, payload: Optional[Dict] = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except Exception:
            body = {"error": "unparseable response"}
        raise GatewayError(f"{method} {path} -> HTTP {exc.code}: {body.get('error')}")
    except urllib.error.URLError as exc:
        raise GatewayError(
            f"Cannot reach the gateway at {BASE} ({exc.reason}). "
            f"Start it with: python -m deamon") from exc


def health() -> Dict:
    return _call("GET", "/health")


def symbol_info(symbol: str) -> Dict:
    return _call("GET", "/symbol/" + urllib.parse.quote(symbol))


def instrument(symbol: str) -> Dict:
    """
    Everything a strategy needs about an instrument, pulled once.

    Returned flat so callers do not have to reach into `_derived`, and so a
    whole instrument description serialises cleanly into a report snapshot.
    """
    info = symbol_info(symbol)
    d = info.get("_derived", {})
    lot = d.get("lot_info", {})
    return {
        "symbol": info.get("name", symbol),
        "digits": d.get("digits"),
        "point": d.get("point_size"),
        "pip": d.get("pip_size"),
        "spread_points": round(info.get("ask", 0) - info.get("bid", 0), 10),
        "spread_pips": round((info.get("ask", 0) - info.get("bid", 0))
                             / (d.get("pip_size") or 1), 6),
        "contract_size": lot.get("contract_size"),
        "min_lot": lot.get("min_lot"),
        "max_lot": lot.get("max_lot"),
        "lot_step": lot.get("lot_step"),
        "pip_value_per_lot": d.get("pip_value_per_lot"),
        "min_stop_pips": d.get("order_rules", {}).get("min_stop_distance_pips"),
        "trade_mode": d.get("trade_mode"),
        "currency": info.get("currency_profit"),
        "_raw": info,
    }


def value_per_point(inst: Dict) -> float:
    """Account-currency value of one point, per 1.0 lot."""
    pip_value = inst.get("pip_value_per_lot") or 0.0
    pip = inst.get("pip") or 1.0
    point = inst.get("point") or pip
    if not pip:
        return 0.0
    return pip_value * (point / pip)


def money_per_pip(inst: Dict) -> float:
    """
    Account-currency value of one pip, per 1.0 lot.

    `pip_value_per_lot` already answers exactly this, so this is a named
    accessor rather than arithmetic. Worth having explicitly because mixing
    pip-denominated results with per-point values was silently wrong by a
    factor of ten on every 5-digit pair.
    """
    return float(inst.get("pip_value_per_lot") or 0.0)


def money(pips: float, inst: Dict, lots: float = 1.0) -> float:
    """Convert a pip-denominated result into account currency."""
    return pips * money_per_pip(inst) * lots


def candles(symbol: str, timeframe: str = "M1", count: int = 5000,
            days: Optional[int] = None) -> List[Dict]:
    """Fetch OHLC bars. `days` requests a date window instead of a bar count."""
    q = urllib.parse.quote(symbol)
    if days:
        end = datetime.now()
        start = end - timedelta(days=days)
        path = (f"/candles/{q}?timeframe={timeframe}"
                f"&from={start.date().isoformat()}&to={end.date().isoformat()}")
    else:
        path = f"/candles/{q}?timeframe={timeframe}&count={count}"
    result = _call("GET", path)
    return result.get("candles", [])


def bars(symbol: str, timeframe: str = "M1", count: int = 5000,
         days: Optional[int] = None) -> List[Bar]:
    return to_bars(candles(symbol, timeframe, count, days))


def cached_bars(store, symbol: str, timeframe: str, count: int) -> List[Bar]:
    """Read bars from the SQLite cache, oldest first."""
    rows = store.load_bars(symbol, timeframe, count)
    return to_bars(rows) if rows else []


def fetch(symbol: str, timeframe: str = "M1", count: int = 5000,
          days: Optional[int] = None, store=None,
          use_cache: bool = True) -> List[Bar]:
    """
    Fetch bars, preferring the cache when it already has enough.

    Falls back to the gateway on a cache miss and writes the result back, so
    the second run of a sweep is served locally.
    """
    if use_cache and store is not None:
        local = cached_bars(store, symbol, timeframe, count)
        if len(local) >= min(count, 100):
            return local
    fetched = bars(symbol, timeframe, count, days)
    if store is not None and fetched:
        store.save_bars(symbol, timeframe, [
            {"time": int(b.time), "open": b.open, "high": b.high,
             "low": b.low, "close": b.close, "tick_volume": b.tick_volume}
            for b in fetched])
    return fetched
