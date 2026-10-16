"""
dashboard — Views
==================

Two responsibilities, kept apart on purpose:

* `context()` gathers what the backend knows and the browser cannot: account
  figures, the terminal build, the broker clock offset, and the live data
  behind each panel. It is the only place that calls the MT5 engine.

* `render()` turns a page file into a response. It reads
  `frontend/pages/<name>.html`, splices in `frontend/partials/*.html`, and
  injects the runtime JSON block. It knows nothing about trading.

Keeping them separate is what allows the frontend to be edited without touching
any other backend file: change a page, change a partial, change a stylesheet,
and nothing in here needs to know.

Page markers recognised by `render()`:

    <!--#include head-->      splice in partials/head.html
    <!--#include footer-->    splice in partials/footer.html
    <!--#bootstrap-->        replaced with <script type="application/json">

`<!--#bootstrap-->` matters for safety as much as convenience. The payload
holds broker-supplied strings - symbol names, deal comments - and `<` is
escaped to its unicode form so none of it can close the script tag early.
"""

import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from dashboard import assets

# How many Market Watch instruments to show. The broker exposes 731 symbols
# but only a few dozen are flagged visible/selected; the rest are noise here.
WATCHLIST_LIMIT = 24

# How many closed deals to render.
DEAL_LIMIT = 25

# `clock_offset()` asks the terminal for a tick on every selected symbol, so it
# costs dozens of round trips. It drifts by seconds, so it is cached rather
# than recomputed per render.
OFFSET_TTL_SECONDS = 300

# One pass over the page, matching three things in order of specificity: an
# include marker, the bootstrap marker, or an ordinary HTML comment.
#
# Ordinary comments are matched so they can be preserved verbatim, and that is
# the entire reason they are handled here rather than left alone. A page that
# documents the marker syntax - "the bootstrap marker is replaced with..." -
# would otherwise have its own documentation substituted away, silently. On
# this dashboard that produced *two* bootstrap blocks, the second sitting
# inside a comment and carrying roughly 30 KB of duplicate payload.
_TOKEN = re.compile(
    r"(?P<include><!--\#include\s+(?P<name>[A-Za-z0-9_-]+)\s*-->)"
    r"|(?P<boot><!--\#bootstrap\s*-->)"
    r"|(?P<comment><!--.*?-->)",
    re.S,
)


def esc(value) -> str:
    """HTML-escape a value that came from outside this process."""
    return html.escape("" if value is None else str(value), quote=True)


def json_for_script(payload) -> str:
    """
    Serialise for embedding in a <script> block.

    `<` is escaped to its unicode escape because that is the one character that
    could otherwise close the tag early and turn broker-supplied text into
    markup. `>` and `&` are escaped too so the payload cannot terminate an
    HTML comment or entity early.
    """
    raw = json.dumps(payload, default=str, separators=(",", ":"))
    return (raw.replace("<", "\\u003c")
               .replace(">", "\\u003e")
               .replace("&", "\\u0026"))


class _OffsetCache:
    """One cached broker-clock offset, shared across renders."""

    def __init__(self):
        self._value = None
        self._at = 0.0

    def get(self, engine) -> Optional[float]:
        now = time.monotonic()
        if self._value is not None and now - self._at < OFFSET_TTL_SECONDS:
            return self._value
        try:
            # A method, not a property. Reading it without calling hands back
            # the bound function, which then stringifies into the footer.
            raw = engine.clock_offset()
            value = round(float(raw), 1) if raw is not None else None
        except Exception:                                # noqa: BLE001
            return self._value
        self._value, self._at = value, now
        return value


_OFFSET = _OffsetCache()


def _watchlist(engine) -> List[Dict]:
    """
    Market Watch instruments, projected down to what the table renders.

    `/symbols` is 1.5 MB for this broker's 731 instruments. Sending it to the
    browser would be unusable, so only the selected instruments are kept and
    only the fields displayed. Live prices arrive over SSE instead.
    """
    rows = engine.get_symbols() or []
    picked = [s for s in rows if s.get("visible") or s.get("select")]
    if not picked:
        picked = rows[:WATCHLIST_LIMIT]
    picked = sorted(picked[:WATCHLIST_LIMIT], key=lambda s: str(s.get("name") or ""))

    out = []
    for s in picked:
        name = s.get("name")
        pip_size = None
        # `symbol_info` carries the derived pip size; `get_symbols` does not.
        # The lookup is served from the gateway's symbol cache and is the only
        # way to get the pip size right on instruments whose scale is not
        # obvious from the quote.
        try:
            info = engine.get_symbol_info(name) or {}
            pip_size = (info.get("_derived") or {}).get("pip_size")
        except Exception:                               # noqa: BLE001
            pip_size = None
        if not pip_size and s.get("point"):
            pip_size = float(s["point"]) * 10
        out.append({
            "name": name,
            "bid": s.get("bid"),
            "ask": s.get("ask"),
            "digits": s.get("digits"),
            "point": s.get("point"),
            "pip_size": pip_size,
            "spread": s.get("spread"),
            "description": s.get("description") or s.get("path") or "",
            "trade_mode": s.get("_trade_mode"),
            "session_open": s.get("session_open"),
        })
    return out


def _recent_deals(engine) -> List[Dict]:
    end = datetime.now(timezone.utc)
    found = engine.get_history_deals(end - timedelta(days=2), end) or []
    # The broker returns oldest-first, which would push the most recent trade -
    # the one actually wanted - off the bottom.
    found = sorted(found,
                   key=lambda d: d.get("time_msc") or d.get("time") or 0,
                   reverse=True)
    return found[:DEAL_LIMIT]


def context(engine, page: str = "index",
            want=("account", "terminal", "totals", "positions",
                  "orders", "deals", "watchlist")) -> Dict:
    """
    Gather what a page needs, in one pass.

    `want` names the sections to collect. Every page needs `account`,
    `terminal` and the clock offset because the shared header and footer show
    them, so those are always fetched. The heavier sections - the symbol list
    and the deal history - are opt-in: the symbol browser has no use for either
    and should not pay for them on every load.

    Each piece is fetched independently and any failure is recorded rather than
    raised: a dashboard showing seven of eight panels is far more useful than
    one that 500s because the history call was slow.
    """
    out: Dict = {"errors": []}
    want = set(want)

    def grab(key, fn, default):
        if key not in want:
            return default
        try:
            out[key] = fn()
        except Exception as exc:                       # noqa: BLE001
            out["errors"].append({"panel": key, "error": str(exc)})
            out[key] = default
        return out[key]

    # Always present: the header and footer reference all three.
    account = grab("account", engine.get_account_info, {})
    terminal = grab("terminal", engine.get_terminal_info, {})
    grab("totals", engine.get_totals, {})
    grab("positions", engine.get_positions, [])
    grab("orders", engine.get_orders, [])
    grab("deals", lambda: _recent_deals(engine), [])
    watch = grab("watchlist", lambda: _watchlist(engine), [])

    out["connected"] = bool(getattr(engine, "is_connected", False))
    try:
        out["package_version"] = engine.package_version()
    except Exception:                                  # noqa: BLE001
        out["package_version"] = None
    out["clock_offset"] = _OFFSET.get(engine)

    watch_names = [str(s.get("name") or "") for s in watch]
    out["bootstrap"] = {
        "page": page,
        "connected": out["connected"],
        "clock_offset": out["clock_offset"],
        "package_version": out["package_version"],
        "terminal": terminal,
        "account": account,
        "totals": out.get("totals") or {},
        "positions": out.get("positions") or [],
        "orders": out.get("orders") or [],
        "deals": out.get("deals") or [],
        "watchlist": watch_names,
        "watchlist_rows": watch,
        "default_symbol": (watch_names[0] if watch_names else "EURUSD"),
        "portfolio_stream": "/stream/portfolio?interval=1",
        "tick_stream": ("/stream/ticks?symbols=" + ",".join(watch_names)
                        + "&interval=1") if watch_names else None,
        "pages": assets.available_pages(),
    }
    return out


# ── Rendering ──────────────────────────────────────────────────────────


def render(page: str, ctx: Dict) -> Optional[str]:
    """
    Read a page file and return it with partials and bootstrap spliced in.

    Returns None when the page does not exist, so the caller can answer 404.
    """
    found = assets.read_page(page if page.endswith(".html") else page + ".html")
    if found is None:
        return None
    markup = found[0].decode("utf-8")

    def substitute(match):
        if match.group("include") is not None:
            return assets.read_partial(match.group("name")) or ""
        if match.group("boot") is not None:
            return ('<script type="application/json" id="bootstrap">'
                    + json_for_script(ctx["bootstrap"]) + "</script>")
        return match.group("comment")

    markup = _TOKEN.sub(substitute, markup)

    banner = ""
    if ctx["errors"]:
        items = "".join("<li><strong>" + esc(e["panel"]) + "</strong>: "
                        + esc(e["error"]) + "</li>" for e in ctx["errors"])
        banner = ('<div class="banner"><b>Some panels could not load.</b>'
                  "<ul>" + items + "</ul></div>")
    return markup.replace("<body>", "<body>\n" + banner, 1) if banner else markup