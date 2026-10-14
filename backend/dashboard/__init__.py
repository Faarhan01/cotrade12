"""
dashboard — Routes
===================

Registers the web UI into an existing Router. Follows the same contract as
`server/research.py`: return the number of routes added, or 0 if the frontend
could not be loaded, so the caller can log the reason instead of leaving 404s
for someone else to interpret.

URL layout:

    /                  the dashboard            (pages/index.html)
    /ui/{page}         any other page           (pages/<page>.html)
    /assets/{path...}  stylesheets and scripts  (assets/**)

`{path...}` is the router's wildcard form, which spans `/`. Assets genuinely
live in nested folders and their URLs should reflect that rather than being
flattened. Because a wildcard also matches `..`, every asset request is
resolved to a real path and checked to be inside the assets root before the
file is opened.

`/ui/` exists because `/research` and friends are the agent-facing JSON API.
Keeping the two prefixes apart means an agent never has to distinguish a page
from a payload, and a browser never has to guess which is which.

Kept out of `gateway/` deliberately: the gateway is a MetaTrader 5 bridge and
should not know what a web page is. This is one optional extension among
others; a stripped-down gateway serves JSON and nothing else.
"""

from server import responses
from server.errors import NotFound

from dashboard import assets, views

# What each page needs from the server.
#
#   account, terminal - the shared header and footer show the account number,
#                       server, package build, terminal build, clock offset
#                       and trading permissions, so every page needs them.
#   watchlist, deals  - heavy. The symbol listing is 1.5 MB for this broker and
#                       the deal history is a separate query; only the account
#                       overview displays either.
_SECTIONS = {
    "index": ("account", "terminal", "totals", "positions",
              "orders", "deals", "watchlist"),
    "symbols": ("account", "terminal"),
    "research": ("account", "terminal"),
}

_DEFAULT_SECTIONS = ("account", "terminal")


def register(router, engine) -> int:
    """Attach the UI routes. Returns how many were added."""
    before = len(router.list_routes())

    def serve(page: str):
        if assets.read_page(page if page.endswith(".html") else page + ".html") is None:
            raise NotFound(
                f"No page named '{page}'. Available: "
                f"{', '.join(assets.available_pages()) or 'none'}")
        ctx = views.context(engine, page=page,
                            want=_SECTIONS.get(page, _DEFAULT_SECTIONS))
        return responses.html(views.render(page, ctx) or "")

    @router.get("/")
    def index(params, query, body):
        return serve("index")

    @router.get("/ui/{page}")
    def page(params, query, body):
        return serve(params["page"])

    @router.get("/assets/{path...}")
    def asset(params, query, body):
        found = assets.read_asset(params["path"])
        if found is None:
            raise NotFound(f"No such asset: {params['path']}")
        payload, ctype = found
        return responses.asset(payload, ctype)

    return len(router.list_routes()) - before