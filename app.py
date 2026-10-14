#!/usr/bin/env python3
"""
Cotrade Application Entry Point for AI Studio
==============================================
Runs the Cotrade gateway daemon and dashboard web server on host 0.0.0.0:3000.
"""

import os
import sys

_root = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.join(_root, "backend")
_gateway = os.path.join(_backend, "gateway")

for _d in (_root, _backend, _gateway):
    if _d not in sys.path:
        sys.path.insert(0, _d)

port = int(os.environ.get("PORT", "3000"))
host = os.environ.get("HOST", "0.0.0.0")

os.environ["CONY_PORT"] = str(port)
os.environ["CONY_HOST"] = host

from deamon.__main__ import main as daemon_main

if __name__ == "__main__":
    sys.exit(daemon_main())
