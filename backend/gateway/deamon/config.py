"""
deamon — Configuration
========================
Every setting is an environment variable, so the daemon can be reconfigured
without touching code.

Package discovery is delegated to cony.paths, the single place that knows how
to locate the MetaTrader5 package - no absolute paths live here.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cony.paths import find_mt5_package


def _env_int(name: str, default: Optional[int]) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class DaemonConfig:
    """Runtime configuration for the daemon process."""

    # HTTP server.
    # 8890 by default rather than 8888: the Cotrade peron_bridge.py already
    # listens on 8888, and Windows lets two sockets double-bind a port, which
    # silently splits traffic between them. start() also refuses to start if
    # the port is taken, so this default avoids the collision outright.
    host: str = field(default_factory=lambda: os.getenv("CONY_HOST", os.getenv("HOST", "127.0.0.1")))
    port: int = field(default_factory=lambda: _env_int("CONY_PORT", _env_int("PORT", 8890)))

    # MetaTrader5 package
    mt5_package_path: Optional[str] = field(default_factory=find_mt5_package)

    # MT5 credentials (optional — terminal session can be reused)
    mt5_login: Optional[int] = field(default_factory=lambda: _env_int("MT5_LOGIN", None))
    mt5_password: Optional[str] = field(default_factory=lambda: os.getenv("MT5_PASSWORD") or None)
    mt5_server: Optional[str] = field(default_factory=lambda: os.getenv("MT5_SERVER") or None)
    mt5_path: Optional[str] = field(default_factory=lambda: os.getenv("MT5_PATH") or None)
    mt5_timeout: int = field(default_factory=lambda: _env_int("MT5_TIMEOUT", 60000))

    # Connection lifecycle
    auto_connect: bool = field(default_factory=lambda: _env_bool("CONY_AUTO_CONNECT", True))
    auto_reconnect: bool = field(default_factory=lambda: _env_bool("CONY_AUTO_RECONNECT", True))
    reconnect_interval: int = field(default_factory=lambda: _env_int("CONY_RECONNECT_INTERVAL", 20))

    # Symbol name cache. A name given in the wrong case is resolved from a
    # cached map instead of re-reading every symbol from the terminal, which
    # measures ~236 ms against ~0.04 ms for the lookup.
    symbol_cache_ttl: int = field(
        default_factory=lambda: _env_int("CONY_SYMBOL_CACHE_TTL", 300)
    )

    # Logging
    log_level: str = field(default_factory=lambda: os.getenv("CONY_LOG_LEVEL", "INFO"))
    log_file: Optional[str] = field(default_factory=lambda: os.getenv("CONY_LOG_FILE") or None)


config = DaemonConfig()
