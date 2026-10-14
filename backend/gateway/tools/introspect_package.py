"""
Introspect the MetaTrader5 package: list every public function/constant.

Used to confirm the gateway exposes the whole package surface, not a subset.
"""

import os
import sys
import inspect

PKG = r"C:\Users\faarh\Workspaces\Tools\peron\metatrader5_package"
if PKG not in sys.path:
    sys.path.insert(0, PKG)

import MetaTrader5 as mt5

FUNCS = []
CONSTS = []
TYPES = []

for name in dir(mt5):
    if name.startswith("_"):
        continue
    obj = getattr(mt5, name)
    if inspect.isroutine(obj):
        try:
            sig = str(inspect.signature(obj))
        except (ValueError, TypeError):
            sig = "(...)"
        FUNCS.append((name, sig))
    elif inspect.ismodule(obj):
        continue
    elif name.isupper():
        CONSTS.append((name, obj))
    else:
        TYPES.append((name, type(obj).__name__))

print(f"MetaTrader5 version: {mt5.__version__}")
print(f"\nFUNCTIONS ({len(FUNCS)}):")
for name, sig in sorted(FUNCS):
    print(f"  {name}{sig}")

print(f"\nCONSTANTS ({len(CONSTS)}) - first 40:")
for name, val in sorted(CONSTS)[:40]:
    print(f"  {name} = {val!r}")

print(f"\nTOTAL callable API: {len(FUNCS)} functions, {len(CONSTS)} constants")

# Persist for gap analysis against the gateway
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mt5_api.json")
import json

with open(out, "w", encoding="utf-8") as fh:
    json.dump(
        {
            "version": mt5.__version__,
            "functions": [n for n, _ in FUNCS],
            "constants": [n for n, _ in CONSTS],
        },
        fh,
        indent=2,
    )
print(f"\nWrote {out}")
