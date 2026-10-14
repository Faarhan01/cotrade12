"""
deamon — Service Entry Point
==============================
Process lifecycle for the cony gateway: configuration, logging, the HTTP
server, and the streaming connections.

This is the only layer that knows about sockets. It assembles cony (engine)
and server (routing) and exposes them on the network, which is what makes
the daemon replaceable - an MCP server or a WebSocket front end would sit
here instead without touching the layers below.
"""

import json
import os
import select
import signal
import socket
import sys
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

_gateway_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_backend_dir = os.path.dirname(_gateway_dir)
for _d in (_backend_dir, _gateway_dir):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from cony import ConnectionManager, MT5Engine
from cony.marketbook import MarketBookError
from cony.mt5_engine import (
    MT5ConnectionError,
    MT5Error,
    NotFoundError,
    OrderRejectedError,
    SymbolNotFoundError,
)
from server import Router, RouteHandlers
from server.errors import BadRequest, HTTPError
from server.responses import RawResponse
from server.streaming import (
    EventStream,
    marketbook_producer,
    portfolio_producer,
    require_symbols,
    stream_params,
    tick_producer,
)
from deamon.config import config
from deamon.logger import get_logger

logger = get_logger("deamon")

# Streaming connections currently open, so shutdown can stop them.
_ACTIVE_STREAMS = set()
_STREAM_LOCK = threading.Lock()

# Responses at or below this size are pretty-printed for readability; larger
# ones go out compact, where the saving is worth more than the looks.
PRETTY_LIMIT = 64 * 1024


class PortUnavailable(RuntimeError):
    """The configured host:port is already taken."""


class GatewayServer(ThreadingMixIn, HTTPServer):
    """
    Threaded HTTP server.

    Threaded because a streaming connection occupies its handler for as long
    as the client stays connected; with a single-threaded server one open
    stream would block every other request, including the health check.

    Refuses to share its port. On Windows the default socket options let two
    processes bind the same port and then split connections between them with
    no error anywhere - which previously let this daemon answer requests from
    Cotrade's peron_bridge.py. Failing at startup beats serving the wrong
    process's responses.
    """

    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address, handler_class, gateway):
        self.gateway = gateway
        super().__init__(address, handler_class)

    def handle_error(self, request, client_address):
        """
        Log connection faults without dumping a traceback.

        A client that hangs up mid-stream raises ConnectionAbortedError, which
        is ordinary rather than a fault; the stdlib default prints a full
        traceback for it and buries the log in noise. Anything else is a real
        problem and still gets its traceback.
        """
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError, socket.timeout)):
            logger.debug("%s disconnected: %s",
                         client_address[0], type(exc).__name__)
            return
        logger.error("Unhandled error serving %s", client_address[0], exc_info=True)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError as exc:
                raise PortUnavailable(
                    f"Cannot bind {config.host}:{config.port} exclusively ({exc}). "
                    f"Another process is using the port."
                ) from exc
        try:
            super().server_bind()
        except OSError as exc:
            raise PortUnavailable(
                f"Cannot bind {config.host}:{config.port} - {exc}. "
                f"Another process already uses this port. "
                f"Set CONY_PORT to choose another."
            ) from exc


class GatewayHandler(BaseHTTPRequestHandler):
    """Translates HTTP into router calls, or into an SSE stream."""

    server_version = "cony-gateway/1.0"
    protocol_version = "HTTP/1.1"

    # Idle keep-alive connections must not pin a worker thread forever. With no
    # timeout, a client that vanishes without closing leaves the handler
    # blocked in readline() indefinitely; enough of those and the accept loop
    # starves while the process sits at zero CPU and still looks healthy.
    timeout = 30

    def log_message(self, fmt, *args):
        logger.debug("%s %s", self.client_address[0], fmt % args)

    # ─── Response helpers ───────────────────────────────────────────────

    def _headers(self, status, content_type, length=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Expose-Headers", "Content-Type")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def send_json(self, data, status=200):
        """
        Encode and send a JSON response.

        Pretty-printing is for humans at a terminal; an agent parsing this pays
        for it. Measured on 10,000 candles, indent=2 cost 299 ms against 79 ms
        compact and shipped 27% more bytes. Small bodies stay readable because
        they are cheap and often inspected by eye; large ones do not, so the
        size is estimated from one compact encode and only re-encoded when it
        turns out to be small.
        """
        compact = json.dumps(data, default=str)
        if len(compact) <= PRETTY_LIMIT:
            body = json.dumps(data, indent=2, default=str).encode("utf-8")
        else:
            body = compact.encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def send_raw(self, response):
        """
        Send a handler result verbatim, without JSON encoding.

        Only a RawResponse gets here. Anything else is a handler returning
        something the transport cannot send, which would otherwise surface as
        a confusing JSON error about the response's own type.
        """
        extra = dict(response.headers)
        # Static assets change only when the daemon restarts with new code, so
        # a short cache plus revalidation is correct and keeps the dashboard
        # from re-fetching its CSS on every visit.
        extra.setdefault("Cache-Control", "no-cache")
        self._headers(response.status, response.content_type,
                      len(response.body), extra)
        self.wfile.write(response.body)

    def send_error_json(self, message, status, type_name):
        self.send_json({"error": message, "type": type_name, "status": status}, status)

    # ─── Request parsing ────────────────────────────────────────────────

    def read_body(self):
        """Read the JSON body. Raises BadRequest when it is unparseable."""
        length = self.headers.get("Content-Length")
        if not length:
            return None
        raw = self.rfile.read(int(length))
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BadRequest(
                f"Request body is not valid JSON ({exc}). "
                f"Send a JSON object such as "
                f'{{"symbol": "EURUSD", "volume": 0.1}}.'
            )

    # ─── Dispatch ───────────────────────────────────────────────────────

    def handle_request(self, method, needs_body):
        try:
            body = self.read_body() if needs_body else None

            if method in ("POST", "PUT") and body is None:
                self.send_error_json(
                    "A JSON body is required. Send an object, "
                    'e.g. {"symbol": "EURUSD", "volume": 0.1}.',
                    400, "BadRequest",
                )
                return
            if body is not None and not isinstance(body, dict):
                self.send_error_json(
                    f"Body must be a JSON object, got {type(body).__name__}.",
                    400, "BadRequest",
                )
                return

            if method == "GET" and self._wants_stream():
                self.serve_stream()
                return

            handler, params, query = self.server.gateway.router.resolve(method, self.path)
            if handler is None:
                self.send_error_json(
                    f"No route for {method} {self.path}. "
                    f"GET /routes lists every endpoint.",
                    404, "NotFound",
                )
                return

            result = handler(params, query, body)
            # A handler may return bytes to send verbatim - the dashboard
            # page and its assets do. Everything else stays JSON.
            if isinstance(result, RawResponse):
                self.send_raw(result)
            else:
                self.send_json(result)

        except BadRequest as exc:
            self.send_error_json(str(exc), 400, "BadRequest")
        except SymbolNotFoundError as exc:
            self.send_error_json(str(exc), 404, "SymbolNotFound")
        except NotFoundError as exc:
            self.send_error_json(str(exc), 404, "NotFound")
        except OrderRejectedError as exc:
            self.send_json(
                {
                    "success": False,
                    "error": str(exc),
                    "type": "OrderRejected",
                    "retcode": exc.retcode,
                    "result": exc.result,
                },
                status=409,
            )
        except MT5ConnectionError as exc:
            self.send_error_json(str(exc), 503, "MT5Disconnected")
        except MarketBookError as exc:
            # A broker not offering depth of market is a normal condition on
            # retail accounts, not a server fault.
            self.send_error_json(str(exc), 409, "MarketBookUnavailable")
        except HTTPError as exc:
            self.send_error_json(str(exc), exc.status, exc.type_name)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client hung up mid-response
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to a caller
            # An unexpected exception is always our bug, not the caller's, so
            # the stack is logged at ERROR rather than DEBUG. At INFO the frame
            # that actually failed was invisible, which turned a one-line
            # diagnosis into a guess. The traceback still stays out of the
            # response body; the client gets the message only.
            logger.error("%s %s failed: %s\n%s", method, self.path, exc,
                         traceback.format_exc())
            self.send_error_json(str(exc), 500, type(exc).__name__)

    def _wants_stream(self) -> bool:
        """True for an SSE request. Requires both the path and Accept header."""
        if not self.path.split("?")[0].startswith("/stream/"):
            return False
        accept = self.headers.get("Accept", "")
        return "text/event-stream" in accept

    # ─── SSE ────────────────────────────────────────────────────────────

    def serve_stream(self):
        path = self.path.split("?")[0]
        query = {}
        for key, values in parse_qs(urlparse(self.path).query).items():
            query[key] = values[0]

        engine = self.server.gateway.engine

        try:
            if path == "/stream/ticks":
                symbols = require_symbols(query, engine)
                interval, book = stream_params(query)[1:]
                producer = tick_producer(engine, symbols, book=book)
                source = "tick"
            elif path == "/stream/marketbook":
                symbols = require_symbols(query, engine)
                interval = stream_params(query)[1]
                producer = marketbook_producer(engine, symbols)
                source = "marketbook"
            elif path == "/stream/portfolio":
                interval, book = stream_params(query)[1:]
                producer = portfolio_producer(engine, include_book=book)
                source = "portfolio"
            else:
                self.send_error_json(f"Unknown stream {path}", 404, "NotFound")
                return
        except BadRequest as exc:
            self.send_error_json(str(exc), 400, "BadRequest")
            return

        stream = EventStream(self, interval, source)
        with _STREAM_LOCK:
            _ACTIVE_STREAMS.add(stream)

        # A stream is long-lived by design, so lift the idle keep-alive timeout
        # for its duration and let the write path detect a departed client.
        previous_timeout = self.connection.gettimeout()
        self.connection.settimeout(None)

        self._headers(
            200,
            "text/event-stream; charset=utf-8",
            extra={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

        try:
            for frame in stream.run(producer):
                self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            logger.debug("stream %s closed by client", source)
        finally:
            stream.stop()
            with _STREAM_LOCK:
                _ACTIVE_STREAMS.discard(stream)
            try:
                self.connection.settimeout(previous_timeout)
            except OSError:
                pass

    @property
    def _client_gone(self) -> bool:
        """
        True once the client has disconnected.

        Checked properly rather than assumed: select() on the socket with a
        zero timeout reports readable-at-EOF when the peer is gone, which is
        the only reliable signal for a connection the server is not reading
        from. Previously this was a class attribute that nothing ever set, so
        an SSE stream could never detect a departed client and its thread
        spun forever writing into a dead socket.
        """
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            # Readable while we are not reading means either buffered request
            # data (the client is still talking) or EOF (it has gone).
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def finish(self):
        try:
            super().finish()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # ─── HTTP verbs ─────────────────────────────────────────────────────

    def do_HEAD(self):
        self.handle_request("GET", needs_body=False)

    def do_GET(self):
        self.handle_request("GET", needs_body=False)

    def do_POST(self):
        self.handle_request("POST", needs_body=True)

    def do_PUT(self):
        self.handle_request("PUT", needs_body=True)

    def do_DELETE(self):
        self.handle_request("DELETE", needs_body=False)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()


class Gateway:
    """Wires the engine, router and HTTP server into one runnable thing."""

    def __init__(self):
        self.engine = self.build_engine()
        self.router = Router()
        RouteHandlers(self.engine, self.router,
                          base=f"http://{config.host}:{config.port}")
        self.server = GatewayServer((config.host, config.port), GatewayHandler, self)

        # Market book subscriptions die with the connection; mirror that here
        # so the local list does not claim symbols the terminal has forgotten.
        # The cached symbol names go with it - a reconnect can land on a
        # different account with a different broker symbol list.
        self.engine._conn.on_disconnect(self._on_terminal_reset)

    def _on_terminal_reset(self):
        self.engine.market_book.release_all_on_disconnect()
        self.engine.invalidate_symbol_cache()

    def build_engine(self) -> MT5Engine:
        conn = ConnectionManager(
            {
                "package_path": config.mt5_package_path,
                "login": config.mt5_login,
                "password": config.mt5_password,
                "server": config.mt5_server,
                "terminal_path": config.mt5_path,
                "timeout": config.mt5_timeout,
                "auto_reconnect": config.auto_reconnect,
            }
        )
        return MT5Engine(conn, symbol_cache_ttl=config.symbol_cache_ttl)

    def connect(self) -> bool:
        """Attach to the terminal, reporting rather than raising."""
        try:
            info = self.engine._conn.connect()
            logger.info(
                "Connected to MT5 terminal (build %s, account %s)",
                info["terminal"]["build"],
                info["account"]["login"] if info.get("account") else "?",
            )
            if config.auto_reconnect:
                self.engine._conn.start_auto_reconnect(config.reconnect_interval)
            return True
        except (ConnectionError, MT5ConnectionError) as exc:
            logger.warning("Could not connect to MT5: %s", exc)
            logger.warning("Serving anyway; POST /connect to retry.")
            return False

    def serve_forever(self):
        logger.info("=" * 58)
        logger.info("cony gateway %s", __import__("cony").__version__)
        logger.info("listening      http://%s:%s", config.host, config.port)
        logger.info("package path   %s", config.mt5_package_path or "importable directly")
        logger.info("routes         http://%s:%s/routes", config.host, config.port)
        logger.info("endpoints      http://%s:%s/enums", config.host, config.port)
        logger.info("=" * 58)

        # The initial MT5 attach happens on a worker thread, never inline.
        # mt5.initialize() can block for far longer than its own timeout, and
        # running it before serve_forever() left the port listening but serving
        # nothing - unreachable, with no /health to explain why.
        if config.auto_connect:
            threading.Thread(
                target=self.connect, name="cony-connect", daemon=True
            ).start()

        try:
            self.server.serve_forever()
        finally:
            self.shutdown()

    def shutdown(self):
        logger.info("Shutting down...")
        with _STREAM_LOCK:
            for stream in list(_ACTIVE_STREAMS):
                stream.stop()
        self.server.server_close()
        try:
            self.engine.market_book.unsubscribe_all()
        except Exception:  # noqa: BLE001 - best effort during teardown
            pass
        self.engine._conn.disconnect()
        logger.info("Stopped.")


def main():
    logger.info("Starting cony gateway...")
    if not config.mt5_package_path and config.log_level == "INFO":
        logger.info(
            "MetaTrader5 package resolved from the default environment; "
            "set PERON_PACKAGE_PATH if imports fail."
        )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: sys.exit(0))
        except (ValueError, AttributeError):
            pass

    try:
        gateway = Gateway()
    except PortUnavailable as exc:
        logger.error("Cannot start: %s", exc)
        return 1

    try:
        gateway.serve_forever()
    except KeyboardInterrupt:
        logger.info("Interrupted.")
    except SystemExit:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
