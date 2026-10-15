"""Cotrade unified CLI (Stage 4)."""

from __future__ import annotations

import argparse
import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = _BACKEND_ROOT
_BACKEND = _BACKEND_ROOT
_GATEWAY = os.path.join(_BACKEND_ROOT, "gateway")

for _directory in (_ROOT, _BACKEND, _GATEWAY):
    if _directory not in sys.path:
        sys.path.insert(0, _directory)

from run import cmd_db, cmd_routes


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="cotrade", description="Cotrade CLI")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Run the daemon")
    serve_parser.add_argument("--port", "-p", type=int, default=None)
    serve_parser.add_argument("--host", "-H", default=None)
    serve_parser.add_argument(
        "--open", dest="open_browser", action="store_true")
    serve_parser.add_argument("--log-level", default=None)

    sub.add_parser("db", help="Database stats + integrity")
    sub.add_parser("routes", help="List routes")

    sweep_parser = sub.add_parser("sweep", help="Run a strategy sweep")
    sweep_parser.add_argument("symbol")
    sweep_parser.add_argument("--timeframe", "-t", default="M1")
    sweep_parser.add_argument("--count", "-c", type=int, default=5000)
    sweep_parser.add_argument("--days", "-d", type=int, default=None)
    sweep_parser.add_argument("--warmup", type=int, default=60)
    sweep_parser.add_argument("--strategy", "-s", action="append")

    scan_parser = sub.add_parser("scan", help="Scan patterns")
    scan_parser.add_argument("symbol")
    scan_parser.add_argument("--timeframe", "-t", default="M1")
    scan_parser.add_argument("--count", "-c", type=int, default=3000)
    scan_parser.add_argument("--days", "-d", type=int, default=None)
    scan_parser.add_argument("--save", action="store_true")

    sub.add_parser("list", help="List strategies/indicators/patterns")

    report_parser = sub.add_parser("report", help="Show reports")
    report_parser.add_argument("--limit", "-n", type=int, default=25)

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.command is None:
        args.command = "serve"
        args.port = None
        args.host = None
        args.open_browser = False
        args.log_level = None

    if args.command == "serve":
        from run import cmd_server

        class _Args:
            pass

        a = _Args()
        a.port = args.port
        a.host = args.host
        a.open_browser = getattr(args, "open_browser", False)
        a.log_level = args.log_level
        if (
            args.port is None
            and args.host is None
            and not a.open_browser
            and args.log_level is None
        ):

            class _Default:
                port = None
                host = None
                open_browser = False
                log_level = None

            return cmd_server(_Default())
        return cmd_server(a)

    if args.command == "db":
        return cmd_db(argparse.Namespace())

    if args.command == "routes":
        return cmd_routes(argparse.Namespace())

    from tools.bot import runner as bot_runner

    if args.command == "sweep":
        return bot_runner.cmd_sweep(args)
    if args.command == "scan":
        return bot_runner.cmd_scan(args)
    if args.command == "list":
        return bot_runner.cmd_list(args)
    if args.command == "report":
        return bot_runner.cmd_report(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
