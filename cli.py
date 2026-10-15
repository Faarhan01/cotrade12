"""Root shim for the unified Cotrade CLI."""
import importlib.util
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(_ROOT, "backend")
_GATEWAY = os.path.join(_BACKEND, "gateway")
for _d in (_ROOT, _BACKEND, _GATEWAY):
    if _d not in sys.path:
        sys.path.insert(0, _d)

_MODULE_PATH = os.path.join(_BACKEND, "gateway", "cli", "app.py")
_spec = importlib.util.spec_from_file_location("_cotrade_cli_app", _MODULE_PATH)
_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_main)

main = _main.main

if __name__ == "__main__":
    sys.exit(main())
