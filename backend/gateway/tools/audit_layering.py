"""Static layering/value checks (best-effort grep, not a substitute for review)."""
import os, sys

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

files = []
for dirpath, dirnames, filenames in os.walk(BACKEND):
    if "__pycache__" in dirpath:
        continue
    for fn in filenames:
        if fn.endswith(".py"):
            files.append(os.path.join(dirpath, fn))

violations = []
for path in files:
    rel = os.path.relpath(path, BACKEND)
    if rel.endswith(os.path.join("tools", "audit_layering.py")):
        continue
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if "engine._" in line:
                violations.append((rel, n, "engine private access", line.strip()))
            if "store._conn" in line:
                violations.append((rel, n, "store private access", line.strip()))
            entry_ok = os.path.basename(rel) in {"app.py", "run.py", "cli.py"}
            if "os.environ" in line and not entry_ok and rel != os.path.join("core", "config.py"):
                violations.append((rel, n, "env read outside config", line.strip()))

print("layering violations:", len(violations))
for v in violations:
    print(f"{v[0]}:{v[1]} {v[2]}: {v[3]}")
sys.exit(1 if violations else 0)
