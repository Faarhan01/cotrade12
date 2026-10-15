"""
server — Database Routes
=========================
HTTP endpoints for database monitoring, reporting, and maintenance.
Keeps data layer visibility accessible to both browser dashboards and automation agents.
"""

from typing import Optional
import logging

logger = logging.getLogger("cony.server.db")


def register(router) -> int:
    """Register database inspection routes onto the router."""
    try:
        from database.store import Store
    except ImportError:
        logger.warning("database package not importable; skipping /database endpoints")
        return 0

    before = len(router.list_routes())

    @router.get("/database/stats")
    @router.get("/db/stats")
    def db_stats(params, query, body):
        with Store() as store:
            return store.stats()

    @router.get("/database/reports")
    @router.get("/db/reports")
    def db_reports(params, query, body):
        limit = int(query.get("limit", 50))
        strategy = query.get("strategy")
        verdict = query.get("verdict")
        with Store() as store:
            return {
                "count": limit,
                "reports": store.reports(strategy=strategy, verdict=verdict, limit=limit),
            }

    @router.get("/database/integrity")
    @router.get("/db/integrity")
    def db_integrity(params, query, body):
        with Store() as store:
            return {"status": store.check_integrity(), "path": store.path}

    @router.post("/database/vacuum")
    @router.post("/db/vacuum")
    def db_vacuum(params, query, body):
        with Store() as store:
            store.vacuum()
            return {"success": True, "message": "Vacuum completed successfully"}

    @router.get("/database/sessions")
    @router.get("/db/sessions")
    def db_sessions(params, query, body):
        limit = int(query.get("limit", 25))
        with Store() as store:
            return {"sessions": store.list_bot_sessions(limit=limit)}

    return len(router.list_routes()) - before
