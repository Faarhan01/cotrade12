"""
database — SQLite persistence
==============================
Stores strategies, indicator and pattern reference data, backtest reports and
pattern scan results.

    from database import Store
    store = Store()            # backend/data/peron.db by default
    store.migrate()
    store.save_strategy(plan)

Pure stdlib `sqlite3`; adds no dependency beyond what the project already has.
"""

from database.store import Store, new_run_id, DEFAULT_PATH
from database.schema import SCHEMA, REPORT_FIELDS, STRATEGY_FIELDS

__all__ = ["Store", "new_run_id", "DEFAULT_PATH", "SCHEMA",
           "REPORT_FIELDS", "STRATEGY_FIELDS"]
