"""Centralised environment/configuration access.

Only this module (and the database's default path initializer) may read
process environment variables. Everywhere else consults a ``GatewayConfig`` obtained from
here or injected through the container.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


@dataclass
class GatewayConfig:
    """Snapshot of process configuration."""

    host: str = "0.0.0.0"
    port: int = 3000
    db_path: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "database", "data", "peron.db",
    )
    frontend_dir: str = field(default="")
    log_level: str = "INFO"
    gateway_url: str = "http://127.0.0.1:8890"
    mt5_login: Optional[str] = None
    mt5_password: Optional[str] = None
    mt5_server: Optional[str] = None
    mt5_path: Optional[str] = None

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        port = _int("CONY_PORT", _int("PORT", 3000))
        host = os.environ.get("CONY_HOST") or os.environ.get("HOST") or "0.0.0.0"
        explicit_url = os.environ.get("CONY_URL")
        base = explicit_url or f"http://{os.environ.get('CONY_HOST', '127.0.0.1')}:{port}"
        db_path = os.environ.get("PERON_DB") or os.environ.get("CONY_DB_PATH") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "database", "data", "peron.db",
        )
        frontend_dir = os.environ.get("CONY_FRONTEND_DIR", "")
        return cls(
            host=host,
            port=port,
            db_path=db_path,
            frontend_dir=frontend_dir,
            log_level=os.environ.get("CONY_LOG_LEVEL", "INFO").upper(),
            gateway_url=base,
            mt5_login=os.environ.get("MT5_LOGIN"),
            mt5_password=os.environ.get("MT5_PASSWORD"),
            mt5_server=os.environ.get("MT5_SERVER"),
            mt5_path=os.environ.get("MT5_PATH"),
        )


def validate(config: "GatewayConfig") -> None:
    """Raise ValueError when configuration is obviously invalid."""
    if config.port < 1 or config.port > 65535:
        raise ValueError(f"invalid port {config.port}")
    if config.host == "":
        raise ValueError("host must not be empty")
    db_path = getattr(config, "db_path", None)
    if isinstance(db_path, str) and db_path and not os.path.isabs(db_path):
        raise ValueError("db_path must be absolute")
    if config.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError(f"invalid log level {config.log_level}")


def gateway_url(supplied: Optional[str] = None) -> str:
    """Resolve a gateway base URL using centralized config only (not direct env reads elsewhere)."""
    explicit = os.environ.get("CONY_URL")
    if explicit:
        return explicit
    if supplied:
        return supplied
    return GatewayConfig.from_env().gateway_url
