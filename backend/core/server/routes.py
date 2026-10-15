"""
server — Router
================
URL routing with path parameter support.
"""

from typing import Callable, List, Tuple, Optional
import re
from urllib.parse import parse_qs, unquote, urlparse


def _compile_pattern(pattern: str):
    """
    Turn '/symbol/{symbol}' into an anchored regex with named groups.

    re.escape() is applied only to the literal segments so the {param}
    placeholders survive intact, which avoids escaping them into
    \\{name\\} and then failing to substitute them back.

    Two parameter forms:

        {name}      one path segment. `[^/]+` is deliberate - a symbol name is
                    a single segment, and allowing slashes would let
                    /symbol/a/b match a route the caller did not intend.

        {name...}   the rest of the path, slashes included. Needed for static
                    assets, where /assets/css/pages/dashboard.css is a real
                    and desirable URL. Only valid as the final segment: a
                    greedy match in the middle is ambiguous about where one
                    parameter stops and the next begins.

    A `{name...}` segment therefore matches anything, including `..`, and the
    handler is responsible for confining it. The static file reader resolves
    the path and checks it is inside the assets root before opening anything.
    """
    segments = pattern.split("/")
    parts = []
    for index, segment in enumerate(segments):
        wildcard = re.fullmatch(r"\{(\w+)\.\.\.\}", segment)
        if wildcard:
            if index != len(segments) - 1:
                raise ValueError(
                    f"Wildcard parameter {{{wildcard.group(1)}...}} must be the "
                    f"last segment of {pattern!r}; a greedy match mid-path is "
                    f"ambiguous.")
            parts.append(f"(?P<{wildcard.group(1)}>.+)")
            continue
        single = re.fullmatch(r"\{(\w+)\}", segment)
        if single:
            parts.append(f"(?P<{single.group(1)}>[^/]+)")
        else:
            parts.append(re.escape(segment))
    return re.compile("^" + "/".join(parts) + "$")


class Router:
    """Simple URL router mapping patterns to handler methods."""

    def __init__(self):
        self._routes: List[Tuple[str, str, Callable]] = []
        self._compiled: List[Tuple[str, object, Callable]] = []

    def add(self, method: str, pattern: str, handler: Callable):
        self._routes.append((method.upper(), pattern, handler))
        self._compiled.append((method.upper(), _compile_pattern(pattern), handler))

    def get(self, pattern: str):
        def decorator(func):
            self.add("GET", pattern, func)
            return func
        return decorator

    def post(self, pattern: str):
        def decorator(func):
            self.add("POST", pattern, func)
            return func
        return decorator

    def put(self, pattern: str):
        def decorator(func):
            self.add("PUT", pattern, func)
            return func
        return decorator

    def delete(self, pattern: str):
        def decorator(func):
            self.add("DELETE", pattern, func)
            return func
        return decorator

    def resolve(self, method: str, path: str) -> Tuple[Optional[Callable], dict, dict]:
        """
        Match a request to a route and extract its parameters.

        Captured path segments are URL-decoded. Without that, a request for
        /symbol/Step%20Index%20200 would hand the handler the literal string
        "STEP%20INDEX%20200", leaving every symbol containing a space, a plus
        or any other reserved character permanently unreachable.
        """
        parsed = urlparse(path)
        clean_path = parsed.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        method = method.upper()
        for route_method, regex, handler in self._compiled:
            if route_method != method:
                continue
            match = regex.match(clean_path)
            if match:
                params = {k: unquote(v) for k, v in match.groupdict().items()}
                return handler, params, query
        return None, {}, query

    def list_routes(self) -> List[dict]:
        return [{"method": m, "pattern": p} for m, p, _ in self._routes]
