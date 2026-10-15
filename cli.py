"""Root shim for the unified Cotrade CLI (see backend/cli)."""
import os, sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(_ROOT, "backend")
_GATEWAY = os.path.join(_BACKEND, "gateway")
for _d in (_ROOT, _BACKEND, _GATEWAY):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from cli.app import main as _main

if __name__ == "__main__":
    sys.exit(_main())
