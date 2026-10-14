"""
server — Research API
=======================
HTTP surface for strategy work: catalogue, indicators, patterns, strategies,
backtests.

The gateway stays a MetaTrader 5 gateway. This is an optional extension that
registers extra routes only when `knowledgebase` and `tools.bot` are importable
alongside the gateway, so a standalone deployment still runs unchanged. Where
they are present, an agent gets the full research workflow over the same
port it already uses for market data.

Layering is preserved: the knowledgebase takes its market data through an
injected fetcher rather than importing the gateway, so nothing below this layer
knows HTTP exists.
"""

import importlib
import json
import os
import sys
import urllib.error
import urllib.parse
from datetime import datetime
from typing import Optional

from server.errors import BadRequest, NotFound, UpstreamUnavailable

# The gateway lives at backend/gateway; its siblings (knowledgebase, tools)
# are one level up. Added so the extension can find them without the caller
# having to arrange PYTHONPATH.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Where this gateway is listening. Supplied by `deamon` when it registers the
# research routes, because that layer owns the configuration and `server/`
# must not import `deamon/` - doing so points the dependency backwards
# (deamon -> server -> deamon) and collapses the layering.
#
# It matters that this follows the listener. This module runs inside the
# gateway and calls back over HTTP to read candles. When the port was
# hardcoded here, setting CONY_PORT produced a daemon that could not reach its
# own research layer: the listener moved and this stayed behind.
#
# CONY_URL still wins, so the research layer can be pointed at a remote
# gateway instead of the local one.
def _resolve_base(supplied: Optional[str] = None) -> str:
    base = os.environ.get("CONY_URL") or supplied or "http://127.0.0.1:8890"
    return base.rstrip("/")


BASE = _resolve_base()

_research = None
_load_error = None


def _gateway_fetch(symbol: str, timeframe: str = "M1", count: int = 2000,
                   days: Optional[int] = None):
    """Pull bars from the gateway over HTTP and return them as `Bar` objects.

    Used instead of importing the engine directly so the research layer works
    against a remote gateway as readily as a local one. The conversion is not
    cosmetic: the gateway serves candles as plain dicts, but every detector and
    indicator downstream reads attributes, so handing back raw dicts fails
    deep inside the analysis instead of at the boundary.
    """
    import urllib.error
    import urllib.request

    from knowledgebase.patterns import to_bars

    def call(path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            BASE + path, data=data,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            # Translate the upstream status rather than letting a raw urllib
            # string escape. Without this an unknown symbol - a client
            # mistake - surfaces as a 500, telling the caller the server is
            # broken when it is not.
            try:
                detail = json.loads(exc.read()).get("error", "")
            except Exception:                           # noqa: BLE001
                detail = ""
            if exc.code == 404:
                raise NotFound(detail or f"No data for '{symbol}'") from exc
            raise BadRequest(detail or f"Upstream returned {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise UpstreamUnavailable(
                f"Gateway at {BASE} is unreachable: {exc.reason}") from exc

    # safe="" so a symbol containing a slash cannot escape its path segment.
    q = urllib.parse.quote(symbol, safe="")
    if days:
        from datetime import datetime, timedelta, timezone
        end = datetime.now(timezone.utc).replace(tzinfo=None)
        start = end - timedelta(days=days)
        path = (f"/candles/{q}?timeframe={timeframe}"
                f"&from={start.date().isoformat()}&to={end.date().isoformat()}")
    else:
        path = f"/candles/{q}?timeframe={timeframe}&count={count}"
    return to_bars(call(path).get("candles", []))


def get_research():
    """
    Build the Research service once, with a store if one is reachable.

    Returns None when the knowledgebase is not installed; callers then skip
    registering these routes instead of failing at import time.
    """
    global _research, _load_error
    if _research is not None:
        return _research
    if _load_error is not None:
        return None
    try:
        api = importlib.import_module("knowledgebase.api")
        store = None
        try:
            database = importlib.import_module("database")
            store = database.Store()
            store.migrate()
        except Exception as exc:                      # noqa: BLE001
            # A missing or unwritable database is not fatal; research still
            # works, results just do not persist between restarts.
            print(f"[cony] research running without a database: {exc}",
                  file=sys.stderr)
        _research = api.Research(fetch=_gateway_fetch, store=store)
        return _research
    except Exception as exc:                          # noqa: BLE001
        _load_error = str(exc)
        return None


def load_error() -> Optional[str]:
    """Why the research layer is absent, or None if it loaded or has not been tried."""
    return _load_error


_DESCRIPTIONS = {
    "/research": "this page",
    "/research/catalogue": "indicators, patterns, entry rules, exit and "
                           "sizing fields - read before composing a strategy",
    "/research/indicators": "indicator catalogue only",
    "/research/patterns": "pattern catalogue only",
    "/research/strategies": "entry rule catalogue only",
    "/research/library": "built-in starter strategies",
    "/research/stored": "strategies saved to the database",
    "/research/strategy/{name}": "one stored strategy",
    "/research/strategy/validate": "check a definition, report what is wrong",
    "/research/strategy/save": "validate then persist",
    "/research/backtest": "backtest a definition, or the name of a stored one",
    "/research/sweep": "backtest several strategies, ranked by |t|",
    "/research/patterns/scan": "find patterns and measure follow-through "
                               "against the market baseline and the spread",
    "/research/indicator": "compute one indicator over recent bars",
}


def _describe(pattern: str) -> str:
    return _DESCRIPTIONS.get(pattern, "")


def register(router, engine, base: Optional[str] = None):
    """
    Attach the research routes to an existing Router.

    `base` is where this gateway is listening, supplied by the caller that owns
    the configuration. The research layer reads candles back over HTTP, so it
    has to agree with the listener rather than assume the default port.

    Returns the number of routes registered, so the caller can report that the
    extension is absent rather than leaving the agent to guess why a 404
    appeared.
    """
    global BASE
    BASE = _resolve_base(base)
    research = get_research()
    if research is None:
        return 0

    before = len(router.list_routes())

    @router.get("/research")
    def research_home(params, query, body):
        # Built from the router rather than written out by hand. The hand-
        # written version had two entries for /research/strategies, and JSON
        # silently collapsed them, so one of the two was simply unreachable
        # from the documentation an agent reads to find its way around.
        endpoints = {
            f"{r['method']:<5} {r['pattern']}": _describe(r["pattern"])
            for r in router.list_routes()
            if r["pattern"].startswith("/research")
        }
        return {
            "service": "cony research",
            "description": "Strategy creation, pattern scanning, indicators "
                           "and backtesting.",
            "endpoints": endpoints,
            "workflow": [
                "1. GET /research/catalogue",
                "2. POST /research/patterns/scan to see what the data supports",
                "3. POST /research/strategy/validate while drafting",
                "4. POST /research/backtest",
                "5. Only consider it if verdict beats 'noise' and the "
                "train/test split is consistent.",
            ],
            "reading_the_output": {
                "verdict": "the only field that decides whether anything is "
                           "worth doing; 'noise' means do not trade it",
                "win_rate vs resolved_win_rate": "the first counts every trade, "
                                                 "the second only those that "
                                                 "reached take-profit or "
                                                 "stop-loss; they disagree "
                                                 "whenever the exit rule is loose",
                "split_check.consistent": "false means the profit was all in "
                                          "the first half of the sample",
                "mean_edge_pct": "follow-through with the market's own drift "
                                 "removed - the verdict is based on this, not "
                                 "on the raw move",
                "trade_direction": "'inverted' means the pattern reliably "
                                    "moves the other way, which is tradeable; "
                                    "an edge that fails to replicate across "
                                    "symbols is noise whatever its t-statistic",
            },
        }

    @router.get("/research/catalogue")
    def catalogue(params, query, body):
        return research.catalogue()

    @router.get("/research/indicators")
    def indicators(params, query, body):
        return {"indicators": research.catalogue()["indicators"]}

    @router.get("/research/patterns")
    def patterns(params, query, body):
        return {"patterns": research.catalogue()["patterns"]}

    @router.get("/research/strategies")
    def strategies(params, query, body):
        return {"entry_rules": research.catalogue()["entry_rules"]}

    @router.get("/research/library")
    def library(params, query, body):
        return {"strategies": research.library()}

    @router.get("/research/strategy/{name}")
    def get_strategy(params, query, body):
        found = research.get_strategy(params["name"])
        if not found:
            raise NotFound(f"No stored strategy named '{params['name']}'")
        return found

    @router.get("/research/stored")
    def stored_strategies(params, query, body):
        return {"strategies": research.list_strategies()}

    @router.post("/research/strategy/validate")
    def validate_strategy(params, query, body):
        return research.validate_strategy(body or {})

    @router.post("/research/strategy/save")
    def save_strategy(params, query, body):
        return research.save_strategy(body or {})

    @router.post("/research/backtest")
    def backtest(params, query, body):
        body = body or {}
        spec = body.get("strategy")
        if isinstance(spec, str):
            stored = research.get_strategy(spec)
            if not stored:
                raise NotFound(f"No stored strategy named '{spec}'")
            spec = stored
        if not isinstance(spec, dict):
            raise BadRequest(
                "'strategy' must be a strategy object or the name of a stored one")
        symbol = body.get("symbol")
        if not symbol:
            raise BadRequest("'symbol' is required")
        return research.backtest(
            spec, symbol,
            timeframe=body.get("timeframe", "M1"),
            count=int(body.get("count", 4000)),
            warmup=int(body.get("warmup", 60)),
            spread_pips=body.get("spread_pips"),
        )

    @router.post("/research/sweep")
    def sweep(params, query, body):
        body = body or {}
        specs = body.get("strategies")
        if not specs:
            specs = research.library()
        if not isinstance(specs, list):
            raise BadRequest("'strategies' must be a list")
        symbol = body.get("symbol")
        if not symbol:
            raise BadRequest("'symbol' is required")
        return research.sweep(
            specs, symbol,
            timeframe=body.get("timeframe", "M1"),
            count=int(body.get("count", 4000)),
        )

    @router.post("/research/patterns/scan")
    def pattern_scan(params, query, body):
        body = body or {}
        symbol = body.get("symbol")
        if not symbol:
            raise BadRequest("'symbol' is required")
        only = body.get("patterns")
        if isinstance(only, str):
            only = [p.strip() for p in only.split(",") if p.strip()]
        return research.pattern_scan(
            symbol,
            timeframe=body.get("timeframe", "M1"),
            count=int(body.get("count", 2000)),
            days=body.get("days"),
            only=only,
            horizon=int(body.get("horizon", 5)),
        )

    @router.post("/research/indicator")
    def indicator(params, query, body):
        body = body or {}
        symbol = body.get("symbol")
        name = body.get("indicator") or body.get("name")
        if not symbol:
            raise BadRequest("'symbol' is required")
        if not name:
            raise BadRequest("'indicator' is required")
        result = research.indicator(
            symbol, name,
            timeframe=body.get("timeframe", "M1"),
            count=int(body.get("count", 2000)),
            params=body.get("params"),
        )
        if "error" in result:
            raise BadRequest(result["error"])
        return result

    @router.get("/research/patterns/frequency")
    def pattern_frequency(params, query, body):
        """Get pattern frequency statistics."""
        from database.store import Store
        symbol = query.get("symbol")
        try:
            with Store() as store:
                freq = store.pattern_frequency(symbol=symbol)
                return {"symbol": symbol, "patterns": freq}
        except Exception as e:
            return {"error": str(e)}

    @router.get("/research/bars/range")
    def bar_range(params, query, body):
        """Get cached bar range for a symbol/timeframe."""
        from database.store import Store
        symbol = query.get("symbol")
        timeframe = query.get("timeframe", "M1")
        try:
            with Store() as store:
                r = store.bar_range(symbol, timeframe)
                return {"symbol": symbol, "timeframe": timeframe, **r}
        except Exception as e:
            return {"error": str(e)}

    @router.get("/research/reports/best")
    def best_reports(params, query, body):
        """Get best reports ranked by t-statistic."""
        from database.store import Store
        limit = int(query.get("limit", 20))
        try:
            with Store() as store:
                reports = store.best_reports(limit=limit)
                return {"reports": reports, "count": len(reports)}
        except Exception as e:
            return {"error": str(e)}

    @router.get("/research/hits/context")
    def hit_context(params, query, body):
        """Get indicator context at pattern hits."""
        from database.store import Store
        run_id = query.get("run_id")
        symbol = query.get("symbol")
        pattern = query.get("pattern")
        limit = int(query.get("limit", 100))
        try:
            with Store() as store:
                hits = store.hits(pattern=pattern, symbol=symbol, limit=limit)
                return {"run_id": run_id, "hits": hits, "count": len(hits)}
        except Exception as e:
            return {"error": str(e)}

    # ── Strategy Versioning & Export/Import ──────────────────────────────

    @router.get("/research/strategy/{name}/history")
    def strategy_history(params, query, body):
        """Get all versions of a strategy."""
        from database.store import Store
        name = params["name"]
        try:
            with Store() as store:
                history = store.get_strategy_history(name)
                return {"name": name, "versions": history}
        except Exception as e:
            return {"error": str(e)}

    @router.get("/research/strategy/{name}/version/{version}")
    def strategy_version(params, query, body):
        """Get a specific version of a strategy."""
        from database.store import Store
        name = params["name"]
        version = int(params["version"])
        try:
            with Store() as store:
                version_data = store.get_strategy_version(name, version)
                if not version_data:
                    raise NotFound(f"Version {version} of strategy '{name}' not found")
                return version_data
        except NotFound:
            raise
        except Exception as e:
            return {"error": str(e)}

    @router.post("/research/strategy/{name}/clone")
    def clone_strategy(params, query, body):
        """Clone a strategy with a new name."""
        from database.store import Store
        name = params["name"]
        body = body or {}
        new_name = body.get("new_name")
        description = body.get("description")
        if not new_name:
            raise BadRequest("'new_name' is required")
        try:
            with Store() as store:
                new_id = store.clone_strategy(name, new_name, description)
                return {"success": True, "new_name": new_name, "id": new_id}
        except Exception as e:
            return {"error": str(e)}

    @router.post("/research/strategy/export")
    def export_strategies(params, query, body):
        """Export strategies to JSON."""
        from database.store import Store
        import json
        names = body.get("names") if body else None
        try:
            with Store() as store:
                if names:
                    strategies = []
                    for name in names:
                        s = store.load_strategy(name)
                        if s:
                            strategies.append(s.to_dict())
                else:
                    raw_strategies = store.list_strategies()
                    strategies = []
                    for s in raw_strategies:
                        # Parse JSON fields
                        s = dict(s)
                        s["entry_params"] = json.loads(s.get("entry_params") or "{}")
                        s["exit_rule"] = json.loads(s.get("exit_rule") or "{}")
                        s["sizing"] = json.loads(s.get("sizing") or "{}")
                        s["tags"] = json.loads(s.get("tags") or "[]")
                        strategies.append(s)
                return {
                    "exported_at": datetime.now().isoformat(),
                    "count": len(strategies),
                    "strategies": strategies
                }
        except Exception as e:
            return {"error": str(e)}

    @router.post("/research/strategy/import")
    def import_strategies(params, query, body):
        """Import strategies from JSON."""
        from database.store import Store
        from knowledgebase.strategies import Strategy
        strategies_data = body.get("strategies") if body else None
        if not strategies_data:
            raise BadRequest("'strategies' array required")
        try:
            with Store() as store:
                imported = []
                for s_data in strategies_data:
                    try:
                        plan = Strategy.from_dict(s_data)
                        store.save_strategy(plan)
                        imported.append(plan.name)
                    except Exception as e:
                        imported.append(f"FAILED: {s_data.get('name', 'unknown')} - {e}")
                return {"imported": imported, "count": len(imported)}
        except Exception as e:
            return {"error": str(e)}

    return len(router.list_routes()) - before