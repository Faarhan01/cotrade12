"""Cotrade unified CLI (Stage 4)."""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = _ROOT
_GATEWAY = os.path.join(_BACKEND, "gateway")

for _d in (_ROOT, _BACKEND, _GATEWAY):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cotrade", description="Cotrade CLI")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("serve", help="Run the daemon (use --port/--host)")
    p.add_argument("--port", "-p", type=int, default=None)
    p.add_argument("--host", "-H", default=None)
    p.add_argument("--open", dest="open_browser", action="store_true")
    p.add_argument("--log-level", default=None)
    sub.add_parser("db", help="Database stats + integrity")
    sub.add_parser("routes", help="List routes")
    ns = sub.add_parser("sweep", help="Run a strategy sweep")
    ns.add_argument("symbol")
    ns.add_argument("--timeframe", "-t", default="M1")
    ns.add_argument("--count", "-c", type=int, default=5000)
    ns.add_argument("--days", "-d", type=int, default=None)
    ns.add_argument("--warmup", type=int, default=60)
    ns.add_argument("--strategy", "-s", action="append")
    sc = sub.add_parser("scan", help="Scan patterns")
    sc.add_argument("symbol")
    sc.add_argument("--timeframe", "-t", default="M1")
    sc.add_argument("--count", "-c", type=int, default=3000)
    sc.add_argument("--days", "-d", type=int, default=None)
    sc.add_argument("--save", action="store_true")
    sub.add_parser("list", help="List strategies/indicators/patterns")
    rp = sub.add_parser("report", help="Show reports")
    rp.add_argument("--limit", "-n", type=int, default=25)

    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "serve"
        args.port = None
        args.host = None
        args.open_browser = False
        args.log_level = None

    if args.command == "serve":
        os.environ.setdefault("CONY_PORT", str(args.port or 3000))
        if args.port:
            os.environ["CONY_PORT"] = str(args.port)
        if args.host:
            os.environ["CONY_HOST"] = args.host
        if args.log_level:
            os.environ["CONY_LOG_LEVEL"] = args.log_level.upper()
        from deamon.__main__ import main as daemon_main
        # run.py-style handling for defaults
        import run as _run  # noqa
        if args.port is None and args.host is None and not getattr(args, "open_browser", False) and args.log_level is None:
            class _D: pass
            d = _D()
            d.port=None; d.host=None; d.open_browser=False; d.log_level=None
            return _run.cmd_server(d)
        # fallback: build args
        class A: pass
        a = A()
        a.port = args.port; a.host = args.host; a.open_browser = getattr(args,'open_browser',False); a.log_level = args.log_level
        return _run.cmd_server(a)

    if args.command == "db":
        from run import cmd_db
        class A: pass
        a=A(); return cmd_db(a)

    if args.command == "routes":
        from run import cmd_routes
        class A: pass
        a=A(); return cmd_routes(a)

    if args.command in ("sweep","scan","list","report"):
        from tools.bot import runner as R
        if args.command == "sweep":
            # map cli args -> runner's expected args (runner uses args.symbol etc)
            return R.cmd_sweep(args)
        if args.command == "scan":
            return R.cmd_scan(args)
        if args.command == "list":
            return R.cmd_list(args)
        if args.command == "report":
            return R.cmd_report(args)

    parser.print_help()
    return 1

if __name__ == "__main__":
    sys.exit(main())
