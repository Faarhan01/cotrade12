"""
server — HTTP API Layer
=========================
URL routing, request handlers, validation and HTTP error types for the
MetaTrader 5 gateway.

Imports cony as its engine, so this layer never touches the MetaTrader5
package directly and can be swapped for a different transport without
changing anything below it.
"""
import os
import sys

# Ensure backend root and gateway are discoverable
_server_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_server_dir)
_gateway_dir = os.path.join(_backend_dir, "gateway")

for _d in (_backend_dir, _gateway_dir):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from server.routes import Router
from server.handlers import RouteHandlers
from server.errors import (
    HTTPError,
    BadRequest,
    NotFound,
    Conflict,
    UpstreamUnavailable,
)

__all__ = [
    "Router",
    "RouteHandlers",
    "HTTPError",
    "BadRequest",
    "NotFound",
    "Conflict",
    "UpstreamUnavailable",
]
