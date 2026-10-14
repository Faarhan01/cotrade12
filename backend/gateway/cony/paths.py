"""
cony — Package Discovery
==========================
Locates the MetaTrader5 Python package.

Search order:
  1. An explicit path passed in.
  2. The CONY_MT5_PACKAGE / PERON_PACKAGE_PATH environment variable.
  3. A copy sitting next to the gateway.
  4. Whatever is already importable on sys.path.

No absolute workspace paths are baked in; the known-layout check only
verifies that a candidate actually contains a MetaTrader5 directory.
"""

import os
import sys
from typing import Optional

ENV_VARS = ("CONY_MT5_PACKAGE", "PERON_PACKAGE_PATH")

# Relative to this file: gateway/cony/paths.py -> gateway/../metatrader5_package
_LOCAL_CANDIDATES = (
    os.path.join("..", "metatrader5_package"),
    os.path.join("..", "..", "metatrader5_package"),
    os.path.join("..", "..", "..", "metatrader5_package"),
)


def is_package_dir(path: str) -> bool:
    """True when `path` is a directory containing the MetaTrader5 package."""
    if not path:
        return False
    return os.path.isdir(os.path.join(path, "MetaTrader5"))


def find_mt5_package(explicit: Optional[str] = None) -> Optional[str]:
    """
    Best-effort resolution of the directory that should be on sys.path.

    Returns None when MetaTrader5 is already importable without help, which
    is the normal case for a pip-installed copy.
    """
    if explicit and is_package_dir(explicit):
        return os.path.abspath(explicit)

    for name in ENV_VARS:
        value = os.getenv(name)
        if value and is_package_dir(value):
            return os.path.abspath(value)

    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in _LOCAL_CANDIDATES:
        resolved = os.path.abspath(os.path.join(here, candidate))
        if is_package_dir(resolved):
            return resolved

    return None


def ensure_on_path(explicit: Optional[str] = None) -> Optional[str]:
    """Put the package on sys.path if we can find it. Returns the path used."""
    resolved = find_mt5_package(explicit)
    if resolved and resolved not in sys.path:
        sys.path.insert(0, resolved)
    return resolved
