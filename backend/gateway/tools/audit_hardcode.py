"""
Scan the gateway for hardcoded values that should be configurable or derived.

Run:  python tools/audit_hardcode.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Absolute Windows paths - valid only inside the local workspace, never in source.
ABS_PATH = re.compile(r"[A-Za-z]:\\\\?[\w\\.\-]+")

# Ports. 8888 is the Cotrade peron_bridge port and must not appear as a default.
HARDCODED_PORT = re.compile(r"\b(8888|8890|8899)\b")

# Documented MT5 enum values duplicated outside cony/enums.py, which is the
# single place allowed to hold them. The lookbehind excludes qualified
# references such as enums.ORDER_TYPE_NAMES, which are our own names.
MT5_LITERAL = re.compile(
    r"(?<![\w.])(TRADE_RETCODE_[A-Z_]+|ORDER_TYPE_[A-Z_]+|TIMEFRAME_[A-Z0-9]+)\b"
)

# Magic defaults / account numbers.
SUSPECT_NUMBER = re.compile(r"(?<![\w.])(\d{7,})(?![\w.])")

SKIP_DIRS = {"__pycache__", ".git", "tools", "docs", "node_modules"}

# cony/enums.py legitimately reads these names from the package.
ALLOWED = {"cony/enums.py"}

findings = []


def scan():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
            for number, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                where = f"{rel}:{number}"

                for match in ABS_PATH.finditer(line):
                    findings.append((where, "absolute path", match.group(0).strip()))

                if rel not in ALLOWED:
                    for match in MT5_LITERAL.finditer(line):
                        findings.append((where, "MT5 constant outside enums.py", match.group(0)))

                for match in SUSPECT_NUMBER.finditer(line):
                    findings.append((where, "long numeric literal", match.group(1)))

    # Port defaults are checked separately so the gateway's own default is
    # not flagged, and comments are skipped for the same reason as above.
    config = os.path.join(ROOT, "deamon", "config.py")
    with open(config, encoding="utf-8") as fh:
        for number, line in enumerate(fh.readlines(), 1):
            if line.strip().startswith("#"):
                continue
            for match in HARDCODED_PORT.finditer(line):
                # 8890 is this gateway's own default and belongs here.
                if match.group(1) == "8890":
                    continue
                findings.append(
                    (f"deamon/config.py:{number}", "foreign port default", match.group(1))
                )


def main():
    scan()
    if not findings:
        print("No hardcoded paths, ports, MT5 constants or magic numbers found.")
        return 0

    print(f"{len(findings)} finding(s):\n")
    for where, kind, value in findings:
        print(f"  {kind:32} {value:40} {where}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
