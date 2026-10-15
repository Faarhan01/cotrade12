"""Composition objects for the application layer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.application.ports import (
    MT5Port,
    MarketDataPort,
    AccountPort,
    TradingPort,
    StrategyRepository,
    ReportRepository,
    PatternHitRepository,
    ConnectionPort,
)


@dataclass
class AppContainer:
    """Wires infrastructure implementations to application services.

    Constructed only by `core.composition.build_container`. Application code
    and transports read from here instead of building their own dependencies.
    """
    config: Any  # GatewayConfig (kept as Any to avoid import cycle; typed by caller)
    engine: MT5Port
    market_data: MarketDataPort
    account: AccountPort
    trading: TradingPort
    connection: ConnectionPort
    strategy_repo: StrategyRepository
    report_repo: ReportRepository
    pattern_hit_repo: PatternHitRepository
    backtest: Optional[Any] = None
    pattern_scan: Optional[Any] = None
    validation: Optional[Any] = None
    sizing: Optional[Any] = None
    strategy_repo_concrete: Optional[Any] = None


def build_container(config, engine) -> AppContainer:
    """Temporary Stage-2 factory.

    Services are wired in Stage 3 once concrete adapters exist for ports.
    Today we hand the raw engine through the `MT5Port`/`AccountPort` etc.
    contracts as adapters, since `MT5Engine` is structurally compatible with
    (a superset of) those protocols. The `engine` is expected to be a
    `cony.MT5Engine` instance.
    """
    from core.database import repositories as _repos

    store = _repos.SqliteStoreHandle(config) if hasattr(_repos, "SqliteStoreHandle") else None

    return AppContainer(
        config=config,
        engine=engine,                 # type: ignore[arg-type]
        market_data=engine,             # type: ignore[arg-type]
        account=engine,                 # type: ignore[arg-type]
        trading=engine,                # type: ignore[arg-type]
        connection=engine,             # type: ignore[arg-type]
        strategy_repo=_repos.SqliteStrategyRepository(config),
        report_repo=_repos.SqliteReportRepository(config),
        pattern_hit_repo=_repos.SqlitePatternHitRepository(config),
    )
