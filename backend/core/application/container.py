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
from database import repositories as _repos


@dataclass
class AppContainer:
    """Wires infrastructure implementations to application services."""

    config: Any
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


def build_container(config, engine) -> AppContainer:
    # Stage 2/5 factory. Services below can be filled in later without
    # changing the container shape.
    return AppContainer(
        config=config,
        engine=engine,
        market_data=engine,
        account=engine,
        trading=engine,
        connection=engine,
        strategy_repo=_repos.SqliteStrategyRepository(config),
        report_repo=_repos.SqliteReportRepository(config),
        pattern_hit_repo=_repos.SqlitePatternHitRepository(config),
    )
