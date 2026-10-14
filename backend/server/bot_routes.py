"""
server — Bot Routes
====================
HTTP endpoints for algorithmic bot management, strategy queries, and signal evaluations.
Integrates the knowledgebase strategy evaluation with the live MT5 engine feed.
"""

from typing import Optional
import logging

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

    return len(router.list_routes()) - before
