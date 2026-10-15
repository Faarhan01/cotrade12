"""
server — Raw Responses
========================

One wrapper a handler can return to have its bytes sent verbatim instead of
being JSON-encoded.

The rest of the gateway speaks JSON, which is right for an agent. The
dashboard is not an agent-facing surface, so rather than wrap HTML in a JSON
string - which would force the browser through `JSON.parse` and leave a page
that fails to render if anything upstream re-encoded it - a handler returns
this and the transport sends it as-is.

Living in `server/` rather than in the site package keeps the dependency
direction intact: the transport knows about a response type, not about a web
page.
"""

from typing import Dict, Optional, Union


class RawResponse:
    """A handler result to send verbatim.

    `body` is `bytes` or `str`; `str` is encoded as UTF-8, which is the only
    encoding the dashboard uses.
    """

    __slots__ = ("body", "content_type", "status", "headers")

    def __init__(self, body: Union[bytes, str],
                 content_type: str = "text/html; charset=utf-8",
                 status: int = 200,
                 headers: Optional[Dict[str, str]] = None):
        self.body = (body.encode("utf-8") if isinstance(body, str)
                     else bytes(body))
        self.content_type = content_type
        self.status = status
        self.headers = headers or {}

    def __len__(self) -> int:
        return len(self.body)

    def __repr__(self) -> str:
        return (f"RawResponse(status={self.status}, "
                f"content_type={self.content_type!r}, {len(self.body)} bytes)")


def html(markup: str, status: int = 200,
         headers: Optional[Dict[str, str]] = None) -> RawResponse:
    return RawResponse(markup, "text/html; charset=utf-8", status, headers)


def asset(payload: bytes, content_type: str, status: int = 200,
          headers: Optional[Dict[str, str]] = None) -> RawResponse:
    return RawResponse(payload, content_type, status, headers)