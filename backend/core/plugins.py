"""Extension (plugin) loading for the HTTP layer.

All optional features (database, research, bot, dashboard) register through
here. Failures are isolated: one broken extension never stops the rest, and
each failure is logged with its traceback by the caller.
"""
from __future__ import annotations

import logging
import os
import traceback

logger = logging.getLogger("cony.server.plugins")


def register_all(router, engine, base, container=None) -> list:
    """Register every optional extension.

    Returns a list of ``(name, route_count_or_None, error_or_None)`` records so
    the caller can log and account for them uniformly.
    """
    from core.server import db_routes as _db_routes
    from core.server import bot_routes as _bot_routes
    from core.server import research as _research_routes
    from core.frontconnect import register as _dashboard_register

    results = []

    # Database
    try:
        n = _db_routes.register(router)
        results.append(("database", n, None))
        if n:
            logger.info("database API enabled: %d routes under /db", n)
    except Exception:  # noqa: BLE001
        results.append(("database", 0, traceback.format_exc()))
        logger.warning("database API failed to load.\n%s", traceback.format_exc())

    # Research
    try:
        added = _research_routes.register(router, engine, base=base)
        err = _research_routes.load_error() if hasattr(_research_routes, "load_error") else None
        if added:
            logger.info("research API enabled: %d routes under /research", added)
            results.append(("research", added, err))
        else:
            logger.warning("research API unavailable (%s)", err or "no routes registered")
            results.append(("research", 0, err))
    except Exception:  # noqa: BLE001
        results.append(("research", 0, traceback.format_exc()))
        logger.warning("research API failed to load.\n%s", traceback.format_exc())

    # Bot
    try:
        n = _bot_routes.register(router, engine=engine)
        if n:
            logger.info("bot API enabled: %d routes under /bot", n)
        results.append(("bot", n, None))
    except Exception:  # noqa: BLE001
        results.append(("bot", 0, traceback.format_exc()))
        logger.debug("bot API not registered: %s", traceback.format_exc())

    # Dashboard
    try:
        added = _dashboard_register(router, engine)
        if added:
            from core.frontconnect import assets as _assets
            logger.info("dashboard enabled: / and /ui/{page} from %s (pages: %s)",
                        _assets.FRONTEND_DIR,
                        ", ".join(_assets.available_pages()) or "none")
            results.append(("dashboard", added, None))
        else:
            _frontend_hint = (os.environ.get("CONY_FRONTEND_DIR")
                              or os.path.join(os.path.dirname(_ROOT_PLACEHOLDER()), "frontend"))
            logger.warning("dashboard unavailable - no pages found under %s", _frontend_hint)
            results.append(("dashboard", 0, "no pages found"))
    except Exception:  # noqa: BLE001
        results.append(("dashboard", 0, traceback.format_exc()))
        logger.warning("dashboard failed to load.\n%s", traceback.format_exc())

    return results


def _ROOT_PLACEHOLDER():
    # kept as a helper to avoid deeply nested dirname at module load; mirrors
    # handlers' previous location logic (repo root).
    from pathlib import Path
    return Path(__file__).resolve().parents[2]  # backend/core -> backend -> repo
PYEOF
echo created