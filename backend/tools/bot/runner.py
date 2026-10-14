"""
tools.bot — Orchestration
==========================
Runs strategy sweeps and records everything in the database.

    python -m tools.bot.runner sweep --symbol "Step Index 200" --days 7
    python -m tools.bot.runner scan  --symbol EURUSD --timeframe H1
    python -m tools.bot.runner list
    python -m tools.bot.runner report

The sweep deliberately seeds the knowledgebase library into the database and
writes a report per strategy, so a result stays reproducible: the snapshot
stored with each report captures the entry rule *and* its parameters, which is
what turns "we made money on this" into something reproducible months later.
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from database import Store                                  # noqa: E402
from database.store import new_run_id                       # noqa: E402
from knowledgebase import indicators as kind                # noqa: E402
from knowledgebase import patterns as kpatterns             # noqa: E402
from knowledgebase import strategies as kstrategies         # noqa: E402
from tools.bot import datafeed, engine, patternchecker      # noqa: E402


def open_store() -> Store:
    store = Store()
    store.migrate()
    return store


def sync_knowledgebase(store: Store):
    """Copy the knowledgebase catalogue into the database for querying."""
    indicator_meta = {
        "sma": {"category": "trend", "description": "Simple moving average"},
        "ema": {"category": "trend", "description": "Exponential moving average"},
        "wma": {"category": "trend", "description": "Weighted moving average"},
        "rsi": {"category": "momentum", "description": "Relative Strength Index"},
        "atr": {"category": "volatility", "inputs": ["high", "low", "close"],
                "description": "Average True Range"},
        "bollinger": {"category": "volatility", "description": "Bollinger Bands"},
        "macd": {"category": "momentum", "description": "MACD"},
        "stochastic": {"category": "momentum", "inputs": ["high", "low", "close"],
                       "description": "Stochastic oscillator"},
        "adx": {"category": "trend", "inputs": ["high", "low", "close"],
                "description": "Average Directional Index"},
        "donchian": {"category": "volatility", "inputs": ["high", "low"],
                     "description": "Donchian channels"},
        "slope": {"category": "trend", "description": "Least-squares slope"},
    }
    descriptions = kpatterns.describe()
    pattern_meta = {
        name: {
            "family": ("candlestick" if name in kpatterns.CANDLESTICK
                       else "price_action"),
            "direction": "neutral",
            "description": desc,
        }
        for name, desc in descriptions.items()
    }

    store.sync_indicators(indicator_meta)
    store.sync_patterns(pattern_meta)
    for plan in kstrategies.library():
        store.save_strategy(plan)
    return len(indicator_meta), len(pattern_meta), len(kstrategies.library())


def seed_library(store: Optional[Store] = None):
    """Create the database and populate the reference tables."""
    own = store is None
    store = store or open_store()
    counts = sync_knowledgebase(store)
    if own:
        store.close()
    return counts


def _print_table(headers: List[str], rows: List[List], indent: str = "  "):
    widths = [max(len(str(headers[i])), *(len(str(r[i])) for r in rows)) if rows
              else len(str(headers[i])) for i in range(len(headers))]
    line = indent + "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print(indent + "  ".join("-" * w for w in widths))
    for row in rows:
        print(indent + "  ".join(str(c).ljust(w) for c, w in zip(row, widths)))


def _pips(net_points: float, pip: float) -> float:
    """Price units to pips. Guards against a zero or missing pip size."""
    return net_points / (pip or 1.0)


def cmd_sweep(args) -> int:
    store = open_store()
    seed_library(store)

    print(f"fetching {args.symbol} {args.timeframe} ...")
    bars = datafeed.fetch(args.symbol, args.timeframe,
                          count=args.count, days=args.days, store=store)
    if len(bars) < 200:
        print(f"only {len(bars)} bars available - not enough to test")
        store.close()
        return 1
    inst = datafeed.instrument(args.symbol)
    print(f"{len(bars)} bars, spread {inst['spread_pips']:.2f} pips, "
          f"min lot {inst['min_lot']}, trade mode {inst['trade_mode']}\n")

    if args.strategy:
        plans = []
        for name in args.strategy:
            stored = store.load_strategy(name)
            if stored is None:
                known = [p.name for p in kstrategies.library()]
                if name not in known:
                    print(f"unknown strategy '{name}'. Known: {known}")
                    store.close()
                    return 1
                plans.append(next(p for p in kstrategies.library() if p.name == name))
            else:
                plans.append(stored)
    else:
        plans = kstrategies.library()
    run_id = new_run_id("sweep")
    results = []

    for plan in plans:
        plan.symbol = args.symbol
        plan.timeframe = args.timeframe
        plan.spread_pips = inst["spread_pips"]
        result = engine.run(plan, bars, inst, warmup=args.warmup)
        record = result.to_dict()
        store.save_report({
            "run_id": run_id,
            "strategy_name": plan.name,
            "strategy_snapshot": plan.to_dict(),
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "pip": inst.get("pip") or 1.0,
            "bars": len(bars),
            "from_ts": record["from_ts"],
            "to_ts": record["to_ts"],
            "split": "full",
            "trades": record["trades"],
            "resolved": record["resolved"],
            "win_rate": record["win_rate"],
            "resolved_win_rate": record["resolved_win_rate"],
            "profit_factor": record["profit_factor"],
            "net_points": record["net_points"],
            "gross_points": record["gross_points"],
            "spread_cost": record["trades"] * 2 * inst["spread_pips"] * (inst["pip"] or 1),
            "max_drawdown": record["max_drawdown"],
            "expectancy": record["expectancy"],
            "t_statistic": record["t_statistic"],
            "verdict": record["verdict"],
        })
        results.append((plan.name, record))
        store.save_strategy(plan)

    per_pip = datafeed.money_per_pip(inst)
    print(f"run {run_id}\n")
    print(f"  {per_pip:g} per pip per 1.0 lot "
          f"({per_pip * inst['min_lot']:g} at the {inst['min_lot']:g} lot minimum)\n")
    _print_table(
        ["strategy", "trades", "resolved", "win%", "tp/sl%", "PF", "net pips",
         "net $/lot", "net $/min", "t", "verdict"],
        [[r["strategy_name"], r["trades"], r["resolved"],
          f"{r['win_rate']:.1f}%" if r["win_rate"] is not None else "-",
          f"{r['resolved_win_rate']:.1f}%" if r["resolved_win_rate"] is not None else "-",
          f"{r['profit_factor']:.2f}" if r["profit_factor"] not in (None, float("inf")) else "-",
          f"{r['net_pips']:+.1f}",
          f"{r['net_pips']*per_pip:+.2f}",
          f"{r['net_pips']*per_pip*inst['min_lot']:+.2f}",
          f"{r['t_statistic']:+.2f}" if r["t_statistic"] is not None else "-",
          r["verdict"]] for _, r in results])

    ranked = sorted(results, key=lambda kv: abs(kv[1]["t_statistic"] or 0), reverse=True)
    if ranked:
        best_name, best = ranked[0]
        t = best["t_statistic"]
        print(f"\nhighest |t|: {best_name}  t={t:+.2f} -> {best['verdict']}"
              if t is not None else f"\nhighest |t|: {best_name} (no t-stat)")
        if best["verdict"] in ("noise", "insufficient", "unresolvable"):
            print("  no result here is distinguishable from chance on this data.")
    print(f"\nreports saved under run_id {run_id}")
    store.close()
    return 0


def cmd_scan(args) -> int:
    store = open_store()
    seed_library(store)
    report = patternchecker.check(args.symbol, args.timeframe, args.count,
                                  args.days, store=store)
    print(report.summary())
    if args.save:
        rid = new_run_id("scan")
        payload = [{"pattern": m.pattern, "index": m.index,
                    "time": report.bars[m.index].time, "direction": m.direction,
                    "strength": m.strength, "price": report.bars[m.index].close,
                    "meta": m.meta} for m in report.matches]
        n = store.save_hits(rid, args.symbol, args.timeframe, payload)
        print(f"\nsaved {n} hits as run {rid}")
    store.close()
    return 0


def cmd_list(args) -> int:
    store = open_store()
    seed_library(store)
    rows = store.list_strategies()
    _print_table(["name", "symbol", "timeframe", "entry", "enabled"],
                 [[r["name"], r["symbol"] or "-", r["timeframe"],
                   r["entry_name"], "yes" if r["enabled"] else "no"] for r in rows])
    print(f"\n{len(rows)} strategies, {len(store.list_indicators())} indicators, "
          f"{len(store.list_patterns())} patterns")
    store.close()
    return 0


def cmd_report(args) -> int:
    store = open_store()
    seed_library(store)
    stats = store.stats()
    print("database\n")
    for key, value in stats.items():
        print(f"  {key:<14} {value}")
    rows = store.reports(limit=args.limit)
    if rows:
        print("\nrecent reports (ranked by t-statistic)\n")
        _print_table(["strategy", "symbol", "trades", "resolved", "win%",
                      "tp/sl%", "net pips", "t", "verdict"],
                     [[r["strategy_name"], r["symbol"], r["trades"], r["resolved"],
                       f"{r['win_rate']:.1f}%" if r["win_rate"] is not None else "-",
                       f"{r['resolved_win_rate']:.1f}%" if r["resolved_win_rate"] is not None else "-",
                       f"{r['net_points'] / (r.get('pip') or 1.0):+.1f}",
                       f"{r['t_statistic']:+.2f}" if r["t_statistic"] is not None else "-",
                       r["verdict"]] for r in rows])
    store.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tools.bot.runner", description="Peron strategy runner")
    sub = parser.add_subparsers(dest="command", required=True)

    sweep = sub.add_parser("sweep", help="backtest strategies over live data")
    sweep.add_argument("symbol")
    sweep.add_argument("--timeframe", "-t", default="M1")
    sweep.add_argument("--count", "-c", type=int, default=5000)
    sweep.add_argument("--days", "-d", type=int, default=None)
    sweep.add_argument("--warmup", type=int, default=60)
    sweep.add_argument("--strategy", "-s", action="append")
    sweep.set_defaults(func=cmd_sweep)

    scan = sub.add_parser("scan", help="find chart patterns")
    scan.add_argument("symbol")
    scan.add_argument("--timeframe", "-t", default="M1")
    scan.add_argument("--count", "-c", type=int, default=3000)
    scan.add_argument("--days", "-d", type=int, default=None)
    scan.add_argument("--save", action="store_true")
    scan.set_defaults(func=cmd_scan)

    listing = sub.add_parser("list", help="list stored strategies and reference data")
    listing.set_defaults(func=cmd_list)

    report = sub.add_parser("report", help="show stored reports")
    report.add_argument("--limit", "-n", type=int, default=25)
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
