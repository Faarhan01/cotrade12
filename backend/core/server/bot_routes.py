"""
server — Bot Routes
====================
HTTP endpoints for algorithmic bot management, strategy queries, and signal evaluations.
Integrates the knowledgebase strategy evaluation with the live MT5 engine feed.
"""

import logging
from datetime import datetime

logger = logging.getLogger("cony.server.bot")


def register(router, engine=None) -> int:
    """Register bot monitoring and signal evaluation routes."""
    before = len(router.list_routes())

    @router.get("/bot/status")
    def bot_status(params, query, body):
        is_conn = bool(getattr(engine, "is_connected", False)) if engine else False
        return {
            "status": "ready",
            "connected_to_mt5": is_conn,
            "engine": "live_mt5_bridge" if is_conn else "detached",
            "subscribed_books": engine.market_book.subscribed if engine else [],
        }

    @router.get("/bot/strategies")
    def bot_strategies(params, query, body):
        try:
            from knowledgebase import strategies as kstrategies
            builtin = [s.name for s in kstrategies.library()]
        except Exception:
            builtin = []

        stored = []
        try:
            from database.store import Store
            with Store() as store:
                stored = [s["name"] for s in store.list_strategies()]
        except Exception:
            pass

        return {
            "builtin_strategies": builtin,
            "stored_strategies": stored,
            "total": len(builtin) + len(stored),
        }

    # ── Bot Session Management ───────────────────────────────────────────

    @router.post("/bot/sessions")
    def create_bot_session(params, query, body):
        """Create a new bot trading session."""
        body = body or {}
        from database.store import Store
        try:
            with Store() as store:
                session_id = body.get("session_id") or f"bot_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
                strategy_name = body.get("strategy_name")
                symbol = body.get("symbol")
                timeframe = body.get("timeframe", "M1")
                magic = int(body.get("magic", 0))
                dry_run = bool(body.get("dry_run", True))

                if not strategy_name:
                    raise ValueError("'strategy_name' is required")
                if not symbol:
                    raise ValueError("'symbol' is required")

                sid = store.create_bot_session(session_id, strategy_name, symbol, timeframe, magic, dry_run)
                return {
                    "success": True,
                    "session_id": session_id,
                    "id": sid,
                    "strategy_name": strategy_name,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "magic": magic,
                    "dry_run": dry_run,
                    "status": "running",
                    "started_at": datetime.now().isoformat()
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @router.get("/bot/sessions")
    def list_bot_sessions(params, query, body):
        """List all bot sessions."""
        from database.store import Store
        try:
            with Store() as store:
                limit = int(query.get("limit", 50))
                sessions = store.list_bot_sessions(limit=limit)
                return {"sessions": sessions, "count": len(sessions)}
        except Exception as e:
            return {"sessions": [], "count": 0, "error": str(e)}

    @router.get("/bot/sessions/{session_id}")
    def get_bot_session(params, query, body):
        """Get details of a specific bot session including logs."""
        session_id = params["session_id"]
        from database.store import Store
        try:
            with Store() as store:
                sessions = store.list_bot_sessions(limit=1000)
                session = next((s for s in sessions if s.get("session_id") == session_id), None)
                if not session:
                    from core.server.errors import NotFound
                    raise NotFound("Session not found")

                logs = store.list_bot_logs(session_id=session_id, limit=200)
                return {"session": session, "logs": logs}
        except Exception as e:
            from core.server.errors import HTTPError, BadRequest
            if isinstance(e, HTTPError):
                raise
            raise BadRequest(str(e))

    @router.post("/bot/sessions/{session_id}/pause")
    def pause_bot_session(params, query, body):
        session_id = params["session_id"]
        from database.store import Store
        try:
            with Store() as store:
                store.update_bot_session(session_id, trades_count=0, pnl_pips=0.0,
                                       status="paused", stopped=False)
                return {"success": True, "session_id": session_id, "status": "paused"}
        except Exception as e:  # noqa: BLE001
            from core.server.errors import BadRequest, HTTPError
            if isinstance(e, HTTPError):
                raise
            raise BadRequest(str(e))

    @router.post("/bot/sessions/{session_id}/resume")
    def resume_bot_session(params, query, body):
        session_id = params["session_id"]
        from database.store import Store
        try:
            with Store() as store:
                store.update_bot_session(session_id, trades_count=0, pnl_pips=0.0,
                                       status="running", stopped=False)
                return {"success": True, "session_id": session_id, "status": "running"}
        except Exception as e:  # noqa: BLE001
            from core.server.errors import BadRequest, HTTPError
            if isinstance(e, HTTPError): raise
            raise BadRequest(str(e))

    @router.post("/bot/sessions/{session_id}/stop")
    def stop_bot_session(params, query, body):
        """Stop a running bot session."""
        session_id = params["session_id"]
        body = body or {}
        from database.store import Store
        try:
            with Store() as store:
                trades_count = int(body.get("trades_count", 0))
                pnl_pips = float(body.get("pnl_pips", 0.0))
                store.update_bot_session(
                    session_id,
                    trades_count=trades_count,
                    pnl_pips=pnl_pips,
                    status="stopped",
                    stopped=True
                )
                return {"success": True, "session_id": session_id, "status": "stopped"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @router.get("/bot/sessions/{session_id}/logs")
    def get_bot_logs(params, query, body):
        """Get execution logs for a bot session."""
        session_id = params["session_id"]
        limit = int(query.get("limit", 200))
        from database.store import Store
        try:
            with Store() as store:
                logs = store.list_bot_logs(session_id=session_id, limit=limit)
                return {"session_id": session_id, "logs": logs, "count": len(logs)}
        except Exception as e:
            return {"logs": [], "count": 0, "error": str(e)}

    @router.post("/bot/sessions/{session_id}/log")
    def log_bot_action(params, query, body):
        """Record a bot action (order, evaluation, etc.)"""
        session_id = params["session_id"]
        body = body or {}
        from database.store import Store
        try:
            with Store() as store:
                log_id = store.log_bot_action(
                    session_id=session_id,
                    action=body.get("action", "unknown"),
                    symbol=body.get("symbol", ""),
                    side=body.get("side"),
                    volume=body.get("volume"),
                    price=body.get("price"),
                    success=bool(body.get("success", True)),
                    details=body.get("details", "")
                )
                return {"success": True, "log_id": log_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @router.post("/bot/sessions/{session_id}/update")
    def update_bot_session(params, query, body):
        """Update session performance metrics."""
        session_id = params["session_id"]
        body = body or {}
        from database.store import Store
        try:
            with Store() as store:
                trades_count = int(body.get("trades_count", 0))
                pnl_pips = float(body.get("pnl_pips", 0.0))
                status = body.get("status", "running")
                stopped = bool(body.get("stopped", False))
                store.update_bot_session(
                    session_id,
                    trades_count=trades_count,
                    pnl_pips=pnl_pips,
                    status=status,
                    stopped=stopped
                )
                return {"success": True, "session_id": session_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return len(router.list_routes()) - before