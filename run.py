#!/usr/bin/env python3
"""
Cotrade — Unified Application Runner & Dev Server
=================================================
Runs the MetaTrader 5 gateway daemon, research lab, algorithmic trading bot,
and database explorer.

Usage:
  python run.py                     # Start the dev server & dashboard (default: 0.0.0.0:3000)
  python run.py dev                 # Explicit dev server start
  python run.py server --port 8890  # Start on custom port
  python run.py server --open       # Start and open browser
  python run.py routes              # Print all available API routes
  python run.py db                  # Show database statistics and integrity
  python run.py bot sweep EURUSD    # Run strategy sweep over instrument data
  python run.py bot scan EURUSD     # Run pattern detector over instrument data
"""

import argparse
import os
import sys
import threading
import time

# Wire backend into sys.path
_root = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.join(_root, "backend")
_gateway = os.path.join(_backend, "gateway")

for _dir in (_root, _backend, _gateway):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)


def _open_browser_delayed(url: str, delay: float = 1.0):
    def _worker():
        time.sleep(delay)
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


def cmd_server(args):
    """Start the Cotrade gateway daemon and dashboard server."""
    port = args.port or os.environ.get("CONY_PORT") or os.environ.get("PORT") or 3000
    host = args.host or os.environ.get("CONY_HOST") or os.environ.get("HOST") or "0.0.0.0"

    os.environ["CONY_PORT"] = str(port)
    os.environ["CONY_HOST"] = str(host)

    if hasattr(args, "log_level") and args.log_level:
        os.environ["CONY_LOG_LEVEL"] = str(args.log_level).upper()

    if getattr(args, "open_browser", False):
        target_host = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
        _open_browser_delayed(f"http://{target_host}:{port}/")

    from deamon.__main__ import main as daemon_main
    return daemon_main()


def cmd_db(args):
    """Inspect the SQLite database stats and verify integrity."""
    from database.store import Store
    with Store() as store:
        print("Database stats:")
        for k, v in store.stats().items():
            print(f"  {k:<16}: {v}")
        integrity = store.check_integrity()
        print(f"  integrity check : {integrity}")
    return 0


def cmd_bot(args):
    """Delegate to the bot runner."""
    from tools.bot.runner import main as bot_main
    return bot_main(args.bot_args)


def cmd_routes(args):
    """Print all configured endpoints and UI routes."""
    from cony import MT5Engine, ConnectionManager
    from deamon.config import config
    from server import Router, RouteHandlers

    conn = ConnectionManager({"package_path": config.mt5_package_path})
    engine = MT5Engine(conn)
    router = Router()
    handlers = RouteHandlers(engine, router, base=f"http://localhost:{config.port}")

    print("\n" + "=" * 60)
    print("Cotrade — Route Directory")
    print("=" * 60)
    for method, pattern, _ in router._routes:
        print(f"  {method:<6} {pattern}")
    print("=" * 60 + "\n")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Cotrade — MetaTrader 5 gateway & trading dashboard"
    )
    sub = parser.add_subparsers(dest="command")

    # Dev server runner
    dev_parser = sub.add_parser("dev", help="Start development server (default: 0.0.0.0:3000)")
    dev_parser.add_argument("--port", "-p", type=int, default=None, help="Port to bind (default: 3000)")
    dev_parser.add_argument("--host", "-H", default=None, help="Host to bind (default: 0.0.0.0)")
    dev_parser.add_argument("--open", dest="open_browser", action="store_true", help="Open browser on start")
    dev_parser.add_argument("--log-level", default=None, help="Logging level (DEBUG, INFO, WARNING)")

    # Explicit server runner
    srv = sub.add_parser("server", help="Start the gateway server and dashboard")
    srv.add_argument("--port", "-p", type=int, default=None, help="Port to bind (default: 3000)")
    srv.add_argument("--host", "-H", default=None, help="Host to bind (default: 0.0.0.0)")
    srv.add_argument("--open", dest="open_browser", action="store_true", help="Open browser on start")
    srv.add_argument("--log-level", default=None, help="Logging level (DEBUG, INFO, WARNING)")

    # Database inspector
    sub.add_parser("db", help="Show database statistics and verify integrity")

    # Bot runner
    bot = sub.add_parser("bot", help="Run strategy backtests, sweeps, and pattern scans")
    bot.add_argument("bot_args", nargs=argparse.REMAINDER, help="Arguments passed to bot.runner")

    # Routes directory
    sub.add_parser("routes", help="Display all registered API and UI endpoints")

    # Default to server when no subcommand passed
    if len(sys.argv) == 1:
        class DefaultArgs:
            port = None
            host = None
            open_browser = False
            log_level = None
        return cmd_server(DefaultArgs())

    args = parser.parse_args()
    if args.command in ("server", "dev"):
        return cmd_server(args)
    elif args.command == "db":
        return cmd_db(args)
    elif args.command == "bot":
        return cmd_bot(args)
    elif args.command == "routes":
        return cmd_routes(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
