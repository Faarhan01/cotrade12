"""SQLite implementations of the application ports."""
from __future__ import annotations

from typing import Any, Dict, List

from database.store import Store


def _store() -> Store:
    # One Store per call mirrors the existing handler usage; the busy_timeout
    # and WAL pragmas are set in Store.__init__.
    return Store()


class SqliteStrategyRepository:
    def __init__(self, config=None):
        self.config = config

    def load(self, name: str):
        with _store() as s:
            return s.load_strategy(name)

    def save(self, strategy) -> int:
        with _store() as s:
            return s.save_strategy(strategy)

    def list(self) -> List[Dict[str, Any]]:
        with _store() as s:
            return s.list_strategies()

    def delete(self, name: str) -> bool:
        with _store() as s:
            return s.delete_strategy(name)


class SqliteReportRepository:
    def __init__(self, config=None):
        self.config = config

    def save(self, report: Dict[str, Any]) -> int:
        with _store() as s:
            return s.save_report(report)

    def list(self, *, strategy=None, verdict=None,
             limit: int = 100) -> List[Dict[str, Any]]:
        with _store() as s:
            return s.reports(strategy=strategy, verdict=verdict, limit=limit)

    def best(self, limit: int = 20) -> List[Dict[str, Any]]:
        with _store() as s:
            return s.best_reports(limit)


class SqlitePatternHitRepository:
    def __init__(self, config=None):
        self.config = config

    def save_hits(self, run_id: str, symbol: str, timeframe: str,
                  hits: List[Dict[str, Any]]) -> int:
        with _store() as s:
            return s.save_hits(run_id, symbol, timeframe, hits)

    def query(self, pattern=None, symbol=None, limit: int = 500):
        with _store() as s:
            return s.hits(pattern=pattern, symbol=symbol, limit=limit)

    def frequency(self, symbol=None):
        with _store() as s:
            return s.pattern_frequency(symbol)


# `config` param on the handle is ignored for now; the Container passes it
# and repositories would later share a connection if moved to per-request scope.
class SqliteStoreHandle:
    def __init__(self, config: Any = None):
        self.config = config
