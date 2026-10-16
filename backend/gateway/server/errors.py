"""
server — HTTP Error Types
==========================
Request-level errors that carry an HTTP status.

Engine errors live in cony and stay generic; these express the HTTP
contract, so the transport can translate one into a response without
knowing anything about trading.
"""


class HTTPError(Exception):
    """Base for errors that map onto an HTTP status."""

    status = 500
    type_name = "HTTPError"

    def __init__(self, message: str):
        super().__init__(message)


class BadRequest(HTTPError):
    """Missing, malformed or unusable parameter. HTTP 400."""

    status = 400
    type_name = "BadRequest"


class NotFound(HTTPError):
    """No such route or resource. HTTP 404."""

    status = 404
    type_name = "NotFound"


class Conflict(HTTPError):
    """Valid request the terminal or broker refused. HTTP 409."""

    status = 409
    type_name = "Conflict"


class UpstreamUnavailable(HTTPError):
    """MT5 terminal is not reachable. HTTP 503."""

    status = 503
    type_name = "UpstreamUnavailable"
