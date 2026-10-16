"""
server — HTTP API Layer
=========================
URL routing, request handlers, validation and HTTP error types for the
MetaTrader 5 gateway.

Imports cony as its engine, so this layer never touches the MetaTrader5
package directly and can be swapped for a different transport without
changing anything below it.
"""

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
