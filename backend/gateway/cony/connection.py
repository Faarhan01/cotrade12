"""
cony — Connection Manager
==========================
Owns the lifecycle of the terminal connection: import, attach, authenticate,
reconnect and detach.

Kept separate from MT5Engine so the engine stays a thin set of operations and
the connection concerns (locking, retry, background reconnect) live in one
place.
"""

import threading
import time
from typing import Optional

from cony import enums
from cony.paths import ensure_on_path


class ConnectionManager:
    """
    Thread-safe connection state for the MT5 terminal.

    Usage:
        conn = ConnectionManager({"package_path": ...})
        conn.connect()
        engine = MT5Engine(conn)
        ...
        conn.disconnect()
    """

    def __init__(self, config: Optional[dict] = None):
        self._mt5 = None
        self._connected = False
        self._lock = threading.RLock()
        self._reconnect_thread: Optional[threading.Thread] = None
        self._stop_reconnect = threading.Event()
        self._connection_info: dict = {}
        self._config = dict(config or {})
        # Callbacks fired on disconnect so dependent state (market book
        # subscriptions) can be dropped along with the connection.
        self._on_disconnect: list = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def mt5(self):
        return self._mt5

    def on_disconnect(self, callback):
        """Register a callback invoked whenever the connection drops."""
        self._on_disconnect.append(callback)

    def _import_mt5(self):
        """Import the MetaTrader5 package, adding its directory if needed."""
        resolved = ensure_on_path(self._config.get("package_path"))
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            hint = (
                f"Set PERON_PACKAGE_PATH to the directory containing "
                f"MetaTrader5/. Searched: {resolved or 'site-packages only'}. "
                f"The package must match this interpreter "
                f"(cp{__import__('sys').version_info.major}"
                f"{__import__('sys').version_info.minor}-win_amd64)."
            )
            raise ConnectionError(f"Failed to import MetaTrader5. {hint} Original error: {exc}")
        return mt5

    def connect(self, **overrides) -> dict:
        """
        Attach to the running terminal.

        Any parameter left out falls back to the config this manager was built
        with. Credentials are only needed when the terminal is not already
        logged in; without them initialize() attaches to the current session.
        """
        with self._lock:
            self._mt5 = self._import_mt5()

            kwargs = {}
            for key, config_key in (
                ("login", "login"),
                ("password", "password"),
                ("server", "server"),
                ("path", "terminal_path"),
                ("timeout", "timeout"),
            ):
                value = self._config.get(config_key)
                if value is not None:
                    kwargs[key] = value
            kwargs.update({k: v for k, v in overrides.items() if v is not None})
            kwargs.setdefault("timeout", 60000)

            if not self._mt5.initialize(**kwargs):
                raise ConnectionError(
                    f"initialize() failed: {self._mt5.last_error()}. "
                    f"Is the MT5 terminal running and logged in?"
                )

            self._connected = True
            self._stop_reconnect.clear()

            terminal = self._mt5.terminal_info()
            account = self._mt5.account_info()

            self._connection_info = {
                "connected": True,
                "package_version": getattr(self._mt5, "__version__", None),
                "terminal": {
                    "name": terminal.name if terminal else None,
                    "company": terminal.company if terminal else None,
                    "build": terminal.build if terminal else None,
                    "connected": terminal.connected if terminal else None,
                    "community_account": terminal.community_account if terminal else None,
                    "language": terminal.language if terminal else None,
                },
                "account": {
                    "login": account.login if account else None,
                    "server": account.server if account else None,
                    "currency": account.currency if account else None,
                    "leverage": account.leverage if account else None,
                    "trade_mode": (
                        enums.TRADE_MODE_NAMES.get(account.trade_mode)
                        if account
                        else None
                    ),
                },
            }
            return self._connection_info

    def disconnect(self):
        """Detach from the terminal and stop the reconnect loop."""
        with self._lock:
            self._stop_reconnect.set()
            if self._mt5 and self._connected:
                try:
                    self._mt5.shutdown()
                finally:
                    self._connected = False
                    self._connection_info = {}
                    for callback in self._on_disconnect:
                        try:
                            callback()
                        except Exception:  # noqa: BLE001 - cleanup must not block shutdown
                            pass

    def ensure_connected(self):
        """
        Make sure a connection exists, connecting on demand.

        A read-only call while disconnected therefore reconnects rather than
        failing, which keeps a caller from having to re-issue POST /connect
        after a terminal restart.
        """
        if not self._connected:
            if self._config.get("auto_reconnect", True):
                self.connect()
            else:
                raise ConnectionError(
                    "Not connected to the MT5 terminal. POST /connect first."
                )

    def mark_dropped(self):
        """Record an unexpected drop so the next call reconnects."""
        with self._lock:
            self._connected = False
            self._connection_info = {}

    def start_auto_reconnect(self, interval: int = 20):
        """Run a background loop that reattaches whenever the link drops."""
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        self._stop_reconnect.clear()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop,
            args=(interval,),
            daemon=True,
            name="cony-reconnect",
        )
        self._reconnect_thread.start()

    def stop_auto_reconnect(self):
        self._stop_reconnect.set()

    def _reconnect_loop(self, interval: int):
        # Check often enough to notice a drop promptly, but not busy-loop.
        tick = min(max(interval // 4, 1), 5)
        while not self._stop_reconnect.is_set():
            if not self._connected:
                try:
                    self.connect()
                except ConnectionError:
                    pass
            self._stop_reconnect.wait(tick)

    def get_connection_info(self) -> dict:
        with self._lock:
            return dict(self._connection_info)
