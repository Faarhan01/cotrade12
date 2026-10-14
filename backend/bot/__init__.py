"""
bot — Algorithmic Trading & Research Bot
=========================================
Top-level package for bot execution, backtesting, pattern checking, and live trade management.
Aliases the tools/bot implementation for clean architectural imports.
"""

import sys
import os

_bot_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_bot_dir)
_tools_bot = os.path.join(_backend_dir, "tools", "bot")

for _p in (_backend_dir, _tools_bot):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from tools.bot import engine, runner, live, patternchecker, datafeed
    __all__ = ["engine", "runner", "live", "patternchecker", "datafeed"]
except ImportError:
    pass
