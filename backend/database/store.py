"""
database — Store
=================
SQLite access layer.

Standard library only (`sqlite3`), so the database adds no dependency to a
project that already runs on the MetaTrader5 package alone.

WAL mode and a busy timeout are set because the bot may run a backtest sweep in
one thread while the daemon writes reports in another.
"""

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from database.schema import SCHEMA, REPORT_FIELDS, STRATEGY_FIELDS

DEFAULT_PATH = os.environ.get(
    "PERON_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "peron.db"),
)


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"


class Store:
    """Thread-safe SQLite wrapper for strategies, reports and pattern hits."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or DEFAULT_PATH
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")

    def close(self):
        with self._lock:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── Plumbing ───────────────────────────────────────────────────────

    def migrate(self):
        """Create tables and indexes if absent. Safe to call repeatedly."""
        with self._lock:
            for statement in SCHEMA:
                self._conn.execute(statement)
            self._conn.commit()

    def query(self, sql: str, params: Iterable = ()) -> List[Dict]:
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def execute(self, sql: str, params: Iterable = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur.lastrowid

    # ── Strategies ─────────────────────────────────────────────────────

    def save_strategy(self, strategy) -> int:
        """Insert or update a Strategy from the knowledgebase."""
        d = strategy.to_dict() if hasattr(strategy, "to_dict") else dict(strategy)
        existing = self.query("SELECT id FROM strategies WHERE name = ?", (d["name"],))
        values = (
            d.get("name"),
            d.get("description", ""),
            d.get("symbol", ""),
            d.get("timeframe", "M1"),
            d.get("entry_name", ""),
            json.dumps(d.get("entry_params", {})),
            json.dumps(d.get("exit_rule", {})),
            json.dumps(d.get("sizing", {})),
            float(d.get("spread_pips", 0.0)),
            json.dumps(d.get("tags", [])),
            1 if d.get("enabled", True) else 0,
        )
        with self._lock:
            if existing:
                self._conn.execute(
                    f"UPDATE strategies SET {', '.join(f'{f} = ?' for f in STRATEGY_FIELDS[1:])}"
                    " WHERE name = ?", values[1:] + (d["name"],))
                # The UPDATE branch needs its own commit. sqlite3 opens an
                # implicit transaction on DML, so without this the change sat
                # uncommitted and was rolled back at shutdown - the write only
                # appeared to work when some later call happened to commit on
                # its behalf. It also made vacuum() raise "cannot VACUUM from
                # within a transaction" whenever an UPDATE was pending.
                self._conn.commit()
                return existing[0]["id"]
            placeholders = ", ".join("?" for _ in STRATEGY_FIELDS)
            cur = self._conn.execute(
                f"INSERT INTO strategies ({', '.join(STRATEGY_FIELDS)}) "
                f"VALUES ({placeholders})", values)
            self._conn.commit()
            return cur.lastrowid

    def load_strategy(self, name: str):
        """Reconstruct a knowledgebase Strategy, or None."""
        from knowledgebase.strategies import Strategy
        rows = self.query("SELECT * FROM strategies WHERE name = ?", (name,))
        return Strategy.from_dict(self._row_to_strategy_dict(rows[0])) if rows else None

    def list_strategies(self) -> List[Dict]:
        return self.query("SELECT * FROM strategies ORDER BY name")

    @staticmethod
    def _row_to_strategy_dict(row: Dict) -> Dict:
        d = dict(row)
        d["entry_params"] = json.loads(d.get("entry_params") or "{}")
        d["exit_rule"] = json.loads(d.get("exit_rule") or "{}")
        d["sizing"] = json.loads(d.get("sizing") or "{}")
        d["tags"] = json.loads(d.get("tags") or "[]")
        d["enabled"] = bool(d.get("enabled", 1))
        return d

    def delete_strategy(self, name: str) -> bool:
        """Remove a strategy. Returns whether a row was actually deleted."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM strategies WHERE name = ?", (name,))
            self._conn.commit()
            return cur.rowcount > 0

    # ── Reference data ─────────────────────────────────────────────────

    def sync_indicators(self, catalogue: Dict[str, Dict]) -> int:
        """Upsert the indicator reference table from the knowledgebase."""
        n = 0
        for name, meta in catalogue.items():
            existing = self.query("SELECT id FROM indicators WHERE name = ?", (name,))
            if existing:
                self.execute(
                    "UPDATE indicators SET category=?, inputs=?, description=? WHERE id=?",
                    (meta.get("category", "trend"),
                     json.dumps(meta.get("inputs", ["close"])),
                     meta.get("description", ""), existing[0]["id"]))
            else:
                self.execute(
                    "INSERT INTO indicators (name, category, inputs, description) "
                    "VALUES (?,?,?,?)",
                    (name, meta.get("category", "trend"),
                     json.dumps(meta.get("inputs", ["close"])),
                     meta.get("description", "")))
            n += 1
        return n

    def sync_patterns(self, catalogue: Dict[str, Dict]) -> int:
        """Upsert the pattern reference table from the knowledgebase."""
        n = 0
        for name, meta in catalogue.items():
            existing = self.query("SELECT id FROM patterns WHERE name = ?", (name,))
            if existing:
                self.execute(
                    "UPDATE patterns SET family=?, direction=?, description=? WHERE id=?",
                    (meta.get("family", "candlestick"),
                     meta.get("direction", "neutral"),
                     meta.get("description", ""), existing[0]["id"]))
            else:
                self.execute(
                    "INSERT INTO patterns (name, family, direction, description) "
                    "VALUES (?,?,?,?)",
                    (name, meta.get("family", "candlestick"),
                     meta.get("direction", "neutral"), meta.get("description", "")))
            n += 1
        return n

    def list_patterns(self) -> List[Dict]:
        return self.query("SELECT * FROM patterns ORDER BY family, name")

    def list_indicators(self) -> List[Dict]:
        return self.query("SELECT * FROM indicators ORDER BY name")

    # ── Reports ────────────────────────────────────────────────────────

    def save_report(self, report: Dict) -> int:
        """Store a backtest result. `strategy_snapshot` keeps it reproducible."""
        payload = {k: report.get(k) for k in REPORT_FIELDS}
        payload["strategy_snapshot"] = json.dumps(
            report.get("strategy_snapshot", {}), default=str)
        payload["run_id"] = payload.get("run_id") or new_run_id()
        values = [payload[k] for k in REPORT_FIELDS]
        placeholders = ", ".join("?" for _ in REPORT_FIELDS)
        return self.execute(
            f"INSERT INTO reports ({', '.join(REPORT_FIELDS)}) "
            f"VALUES ({placeholders})", values)

    def reports(self, strategy: Optional[str] = None,
                verdict: Optional[str] = None, limit: int = 100) -> List[Dict]:
        clauses, params = [], []
        if strategy:
            clauses.append("strategy_name = ?")
            params.append(strategy)
        if verdict:
            clauses.append("verdict = ?")
            params.append(verdict)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        return self.query(
            f"SELECT * FROM reports {where} ORDER BY id DESC LIMIT ?", params)

    def best_reports(self, limit: int = 20) -> List[Dict]:
        """Ranked by t-statistic, so noise does not outrank signal."""
        return self.query(
            "SELECT * FROM reports WHERE trades > 0 "
            "ORDER BY COALESCE(t_statistic, 0) DESC, net_points DESC LIMIT ?",
            (limit,))

    # ── Pattern hits ───────────────────────────────────────────────────

    def save_hits(self, run_id: str, symbol: str, timeframe: str,
                  hits: List[Dict]) -> int:
        """Bulk insert pattern matches."""
        rows = [(run_id, symbol, timeframe, h["pattern"], int(h["index"]),
                 int(h.get("time", 0)), h.get("direction", "neutral"),
                 float(h.get("strength", 0)), h.get("price"),
                 json.dumps(h.get("meta", {}), default=str)) for h in hits]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO pattern_hits (run_id, symbol, timeframe, pattern, "
                "bar_index, bar_time, direction, strength, price, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self._conn.commit()
        return len(rows)

    def hits(self, pattern: Optional[str] = None, symbol: Optional[str] = None,
             limit: int = 500) -> List[Dict]:
        clauses, params = [], []
        if pattern:
            clauses.append("pattern = ?")
            params.append(pattern)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        return self.query(
            f"SELECT * FROM pattern_hits {where} ORDER BY bar_time DESC LIMIT ?", params)

    def pattern_frequency(self, symbol: Optional[str] = None) -> List[Dict]:
        clause = "WHERE symbol = ?" if symbol else ""
        params = (symbol,) if symbol else ()
        return self.query(
            f"SELECT pattern, COUNT(*) n, AVG(strength) avg_strength "
            f"FROM pattern_hits {clause} GROUP BY pattern ORDER BY n DESC", params)

    # ── Bar cache ──────────────────────────────────────────────────────

    def save_bars(self, symbol: str, timeframe: str, bars: List[Dict]) -> int:
        rows = [(symbol, timeframe, int(b["time"]), float(b["open"]),
                 float(b["high"]), float(b["low"]), float(b["close"]),
                 int(b.get("tick_volume", 0))) for b in bars]
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO bars (symbol, timeframe, bar_time, open, "
                "high, low, close, tick_volume) VALUES (?,?,?,?,?,?,?,?)", rows)
            self._conn.commit()
        return len(rows)

    def load_bars(self, symbol: str, timeframe: str,
                  limit: int = 10000) -> List[Dict]:
        """
        Cached bars, oldest first, keyed like the gateway's candles.

        The column is `bar_time` rather than `time`; it is renamed here so
        callers see the same shape whether bars came from the gateway or the
        cache.
        """
        rows = self.query(
            "SELECT bar_time, open, high, low, close, tick_volume FROM "
            "(SELECT * FROM bars WHERE symbol=? AND timeframe=? "
            " ORDER BY bar_time DESC LIMIT ?) ORDER BY bar_time",
            (symbol, timeframe, limit))
        return [{"time": r["bar_time"], "open": r["open"], "high": r["high"],
                 "low": r["low"], "close": r["close"],
                 "tick_volume": r["tick_volume"]} for r in rows]

    def bar_range(self, symbol: str, timeframe: str) -> Dict:
        r = self.query(
            "SELECT COUNT(*) n, MIN(bar_time) first, MAX(bar_time) last "
            "FROM bars WHERE symbol=? AND timeframe=?", (symbol, timeframe))
        return r[0] if r else {"n": 0, "first": None, "last": None}

    # ── Report trades ──────────────────────────────────────────────────
    def save_report_trades(self, run_id: str, strategy_name: str, symbol: str,
                           trades: List[Any], pip: float = 1.0) -> int:
        """Store individual trades of a backtest run for granular analysis."""
        rows = []
        for t in trades:
            pnl_pts = getattr(t, "pnl_points", 0.0)
            rows.append((
                run_id, strategy_name, symbol, int(getattr(t, "side", 1)),
                int(getattr(t, "entry_index", 0)), int(getattr(t, "exit_index", 0)),
                float(getattr(t, "entry_price", 0.0)), float(getattr(t, "exit_price", 0.0)),
                float(pnl_pts), float(pnl_pts / (pip or 1.0)),
                str(getattr(t, "reason", "unknown")), int(getattr(t, "bars_held", 0))
            ))
        if not rows:
            return 0
        with self._lock:
            self._conn.executemany(
                "INSERT INTO report_trades (run_id, strategy_name, symbol, side, "
                "entry_index, exit_index, entry_price, exit_price, pnl_points, "
                "pnl_pips, reason, bars_held) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                rows)
            self._conn.commit()
        return len(rows)

    def report_trades(self, run_id: str) -> List[Dict]:
        return self.query("SELECT * FROM report_trades WHERE run_id = ? ORDER BY id", (run_id,))

    # ── Bot sessions & Execution logging ───────────────────────────────
    def create_bot_session(self, session_id: str, strategy_name: str, symbol: str,
                           timeframe: str = "M1", magic: int = 0, dry_run: bool = True) -> int:
        return self.execute(
            "INSERT INTO bot_sessions (session_id, strategy_name, symbol, timeframe, magic, dry_run) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, strategy_name, symbol, timeframe, magic, 1 if dry_run else 0))

    def update_bot_session(self, session_id: str, trades_count: int, pnl_pips: float,
                           status: str = "running", stopped: bool = False) -> int:
        stopped_clause = ", stopped_at = datetime('now')" if stopped else ""
        return self.execute(
            f"UPDATE bot_sessions SET trades_count = ?, pnl_pips = ?, status = ?{stopped_clause} "
            f"WHERE session_id = ?",
            (trades_count, pnl_pips, status, session_id))

    def list_bot_sessions(self, limit: int = 50) -> List[Dict]:
        return self.query("SELECT * FROM bot_sessions ORDER BY id DESC LIMIT ?", (limit,))

    def log_bot_action(self, session_id: str, action: str, symbol: str,
                       side: Optional[str] = None, volume: Optional[float] = None,
                       price: Optional[float] = None, success: bool = True,
                       details: str = "") -> int:
        return self.execute(
            "INSERT INTO bot_logs (session_id, action, symbol, side, volume, price, success, details) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (session_id, action, symbol, side, volume, price, 1 if success else 0, details))

    def list_bot_logs(self, session_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
        if session_id:
            return self.query(
                "SELECT * FROM bot_logs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit))
        return self.query("SELECT * FROM bot_logs ORDER BY id DESC LIMIT ?", (limit,))

    # ── Maintenance & Diagnostics ──────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        def count(table: str) -> int:
            try:
                return self.query(f"SELECT COUNT(*) n FROM {table}")[0]["n"]
            except Exception:
                return 0
        return {
            "path": self.path,
            "strategies": count("strategies"),
            "reports": count("reports"),
            "report_trades": count("report_trades"),
            "pattern_hits": count("pattern_hits"),
            "indicators": count("indicators"),
            "patterns": count("patterns"),
            "cached_bars": count("bars"),
            "bot_sessions": count("bot_sessions"),
            "bot_logs": count("bot_logs"),
        }

    def check_integrity(self) -> str:
        with self._lock:
            cur = self._conn.execute("PRAGMA integrity_check")
            row = cur.fetchone()
            return row[0] if row else "unknown"

    def vacuum(self):
        with self._lock:
            self._conn.execute("VACUUM")

