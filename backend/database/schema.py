"""
database — Schema
===================
SQLite schema for strategies, indicators, patterns and backtest reports.

Design notes:

  * Strategy and pattern *logic* are stored as JSON alongside the parameters
    that produced them. Storing the parameters is what makes a report
    reproducible months later - a result without its parameters is folklore.
  * Reports keep both the raw figures and the statistical verdict, so a query
    can rank candidates without re-running anything.
  * `updated` uses a trigger rather than application code so a row can never
    drift out of sync with its own timestamp.
"""

from typing import List

SCHEMA: List[str] = [
    # ── Strategies ────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS strategies (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT    NOT NULL UNIQUE,
        description   TEXT    NOT NULL DEFAULT '',
        symbol        TEXT    NOT NULL DEFAULT '',
        timeframe     TEXT    NOT NULL DEFAULT 'M1',
        entry_name    TEXT    NOT NULL,
        entry_params  TEXT    NOT NULL DEFAULT '{}',
        exit_rule     TEXT    NOT NULL DEFAULT '{}',
        sizing        TEXT    NOT NULL DEFAULT '{}',
        spread_pips   REAL    NOT NULL DEFAULT 0,
        tags          TEXT    NOT NULL DEFAULT '[]',
        enabled       INTEGER NOT NULL DEFAULT 1,
        version       INTEGER NOT NULL DEFAULT 1,
        created       TEXT    NOT NULL DEFAULT (datetime('now')),
        updated       TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Indicator reference ───────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS indicators (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        category    TEXT NOT NULL DEFAULT 'trend',
        inputs      TEXT NOT NULL DEFAULT '["close"]',
        description TEXT NOT NULL DEFAULT '',
        source      TEXT NOT NULL DEFAULT '',
        created     TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Pattern reference ─────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS patterns (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL UNIQUE,
        family          TEXT NOT NULL DEFAULT 'candlestick',
        direction       TEXT NOT NULL DEFAULT 'neutral',
        lookback        INTEGER NOT NULL DEFAULT 1,
        description     TEXT NOT NULL DEFAULT '',
        source          TEXT NOT NULL DEFAULT '',
        created         TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Backtest reports ──────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS reports (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id            TEXT NOT NULL,
        strategy_id       INTEGER REFERENCES strategies(id) ON DELETE SET NULL,
        strategy_name     TEXT NOT NULL,
        strategy_snapshot TEXT NOT NULL DEFAULT '{}',
        symbol            TEXT NOT NULL,
        timeframe         TEXT NOT NULL,
        pip               REAL NOT NULL DEFAULT 1.0,
        bars              INTEGER NOT NULL DEFAULT 0,
        from_ts           INTEGER,
        to_ts             INTEGER,
        split             TEXT NOT NULL DEFAULT 'full',
        trades            INTEGER NOT NULL DEFAULT 0,
        resolved          INTEGER NOT NULL DEFAULT 0,
        win_rate          REAL,
        resolved_win_rate REAL,
        profit_factor     REAL,
        net_points        REAL NOT NULL DEFAULT 0,
        gross_points      REAL NOT NULL DEFAULT 0,
        spread_cost       REAL NOT NULL DEFAULT 0,
        max_drawdown      REAL NOT NULL DEFAULT 0,
        expectancy        REAL,
        t_statistic       REAL,
        verdict           TEXT NOT NULL DEFAULT 'untested',
        created           TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Pattern scan results ──────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS pattern_hits (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      TEXT NOT NULL,
        symbol      TEXT NOT NULL,
        timeframe   TEXT NOT NULL,
        pattern     TEXT NOT NULL,
        bar_index   INTEGER NOT NULL,
        bar_time    INTEGER NOT NULL,
        direction   TEXT NOT NULL DEFAULT 'neutral',
        strength    REAL NOT NULL DEFAULT 0,
        price       REAL,
        meta        TEXT NOT NULL DEFAULT '{}',
        created     TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Indicator values at pattern hits (why it mattered) ───────────
    """
    CREATE TABLE IF NOT EXISTS hit_context (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        hit_id    INTEGER NOT NULL REFERENCES pattern_hits(id) ON DELETE CASCADE,
        indicator TEXT NOT NULL,
        value     REAL,
        UNIQUE (hit_id, indicator)
    )
    """,

    # ── Raw bar cache (optional; avoids re-fetching for repeated tests) ─
    """
    CREATE TABLE IF NOT EXISTS bars (
        symbol      TEXT NOT NULL,
        timeframe   TEXT NOT NULL,
        bar_time    INTEGER NOT NULL,
        open        REAL NOT NULL,
        high        REAL NOT NULL,
        low         REAL NOT NULL,
        close       REAL NOT NULL,
        tick_volume INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (symbol, timeframe, bar_time)
    )
    """,

    # ── Individual trades from backtests ──────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS report_trades (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        symbol        TEXT NOT NULL,
        side          INTEGER NOT NULL,
        entry_index   INTEGER NOT NULL,
        exit_index    INTEGER NOT NULL,
        entry_price   REAL NOT NULL,
        exit_price    REAL NOT NULL,
        pnl_points    REAL NOT NULL,
        pnl_pips      REAL NOT NULL,
        reason        TEXT NOT NULL,
        bars_held     INTEGER NOT NULL,
        created       TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Live & paper bot sessions ─────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS bot_sessions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id    TEXT NOT NULL UNIQUE,
        strategy_name TEXT NOT NULL,
        symbol        TEXT NOT NULL,
        timeframe     TEXT NOT NULL DEFAULT 'M1',
        magic         INTEGER NOT NULL DEFAULT 0,
        dry_run       INTEGER NOT NULL DEFAULT 1,
        started_at    TEXT NOT NULL DEFAULT (datetime('now')),
        stopped_at    TEXT,
        trades_count  INTEGER NOT NULL DEFAULT 0,
        pnl_pips      REAL NOT NULL DEFAULT 0.0,
        status        TEXT NOT NULL DEFAULT 'running'
    )
    """,

    # ── Bot execution and audit logs ──────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS bot_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT NOT NULL,
        action      TEXT NOT NULL,
        symbol      TEXT NOT NULL,
        side        TEXT,
        volume      REAL,
        price       REAL,
        success     INTEGER NOT NULL DEFAULT 1,
        details     TEXT NOT NULL DEFAULT '',
        timestamp   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,

    "CREATE INDEX IF NOT EXISTS idx_reports_strategy ON reports(strategy_name)",
    "CREATE INDEX IF NOT EXISTS idx_reports_run      ON reports(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_reports_verdict  ON reports(verdict)",
    "CREATE INDEX IF NOT EXISTS idx_hits_pattern     ON pattern_hits(pattern)",
    "CREATE INDEX IF NOT EXISTS idx_hits_symbol      ON pattern_hits(symbol, timeframe)",
    "CREATE INDEX IF NOT EXISTS idx_hits_time        ON pattern_hits(bar_time)",
    "CREATE INDEX IF NOT EXISTS idx_trades_run       ON report_trades(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_status  ON bot_sessions(status)",
    "CREATE INDEX IF NOT EXISTS idx_bot_logs_sess    ON bot_logs(session_id)",

    # Keep updated_at honest without relying on every writer to remember.
    """
    CREATE TRIGGER IF NOT EXISTS trg_strategies_updated
    AFTER UPDATE ON strategies
    FOR EACH ROW
    BEGIN
        UPDATE strategies
           SET updated = datetime('now'),
               version = version + 1
         WHERE id = NEW.id;
    END
    """,
]

# Column order for reports, so inserts and reads cannot drift apart.
REPORT_FIELDS = (
    "run_id", "strategy_id", "strategy_name", "strategy_snapshot", "symbol",
    "timeframe", "pip", "bars", "from_ts", "to_ts", "split", "trades", "resolved",
    "win_rate", "resolved_win_rate", "profit_factor", "net_points",
    "gross_points", "spread_cost", "max_drawdown", "expectancy",
    "t_statistic", "verdict",
)

STRATEGY_FIELDS = (
    "name", "description", "symbol", "timeframe", "entry_name", "entry_params",
    "exit_rule", "sizing", "spread_pips", "tags", "enabled",
)
