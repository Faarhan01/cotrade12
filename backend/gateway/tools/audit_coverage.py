"""
Gap analysis: MetaTrader5 package surface vs what the gateway exposes.

Run:  python tools/audit_coverage.py
Exits non-zero while any package function is unwrapped.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

with open(os.path.join(HERE, "mt5_api.json"), encoding="utf-8") as fh:
    pkg = json.load(fh)

# package function -> the cony method that wraps it ("" means not wrapped)
WRAPPERS = {
    "initialize": "ConnectionManager.connect",
    "shutdown": "ConnectionManager.disconnect",
    "login": "MT5Engine.login",
    "account_info": "get_account_info",
    "terminal_info": "get_terminal_info",
    "last_error": "last_error",
    "version": "package_version",
    "symbols_get": "get_symbols",
    "symbols_total": "symbols_total",
    "symbol_info": "get_symbol_info",
    "symbol_info_tick": "get_tick",
    "symbol_select": "select_symbol",
    "copy_rates_from": "copy_rates",
    "copy_rates_from_pos": "copy_rates_from_pos",
    "copy_rates_range": "copy_rates_range",
    "copy_ticks_from": "copy_ticks_from",
    "copy_ticks_range": "copy_ticks_range",
    "orders_get": "get_orders",
    "orders_total": "orders_total",
    "positions_get": "get_positions",
    "positions_total": "positions_total",
    "order_send": "execute_order / close_position / modify_position / cancel_order",
    "order_check": "check_order",
    "order_calc_margin": "calc_margin",
    "order_calc_profit": "calc_profit",
    "history_deals_get": "get_history_deals",
    "history_deals_total": "history_deals_total",
    "history_orders_get": "get_history_orders",
    "history_orders_total": "history_orders_total",
    "market_book_add": "MarketBook.subscribe",
    "market_book_get": "MarketBook.get",
    "market_book_release": "MarketBook.unsubscribe",
    # Convenience helpers from the package's own __init__, each a thin
    # wrapper over order_send that we reimplement on top of the engine.
    "Buy": "MT5Engine.buy",
    "Sell": "MT5Engine.sell",
    "Close": "MT5Engine.close_position",
}

missing = [f for f in pkg["functions"] if not WRAPPERS.get(f)]
unknown = [f for f in WRAPPERS if f not in pkg["functions"]]
covered = [f for f in pkg["functions"] if WRAPPERS.get(f)]

# Cross-check the wrappers still exist on the engine.
from cony import ConnectionManager, MT5Engine  # noqa: E402

engine = MT5Engine(ConnectionManager())
missing_methods = []
for func, target in WRAPPERS.items():
    for method in re.findall(r"MT5Engine\.(\w+)|MarketBook\.(\w+)", target):
        name = method[0] or method[1]
        cls = engine.market_book if "MarketBook." in target else engine
        if not hasattr(cls, name):
            missing_methods.append(f"{func} -> {target}")

print(f"Package API: {len(pkg['functions'])} functions, "
      f"{len(pkg['constants'])} constants")
print(f"\nWRAPPED ({len(covered)}):")
for name in sorted(covered):
    print(f"  {name:22} -> {WRAPPERS[name]}")

if missing:
    print(f"\nNOT WRAPPED ({len(missing)}):")
    for name in sorted(missing):
        print(f"  {name}")

if unknown:
    print(f"\nWRAPPER FOR UNKNOWN SYMBOL ({len(unknown)}):")
    for name in sorted(unknown):
        print(f"  {name}")

if missing_methods:
    print(f"\nWRAPPER TARGET MISSING ({len(missing_methods)}):")
    for name in missing_methods:
        print(f"  {name}")

total = len(pkg["functions"])
print(f"\nFunction coverage: {len(covered)}/{total} "
      f"({100 * len(covered) // total}%)")

problems = len(missing) + len(unknown) + len(missing_methods)
if problems:
    print(f"\n{problems} problem(s) found.")
    sys.exit(1)
print("Full package surface covered.")
