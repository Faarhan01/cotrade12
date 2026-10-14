"""
Verification suite for the cony gateway.

Exercises every endpoint group against a live MT5 terminal, including the
error paths and the live streams.

    python tools/verify.py            # against http://127.0.0.1:8890
    CONY_URL=http://host:port python tools/verify.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.getenv("CONY_URL", "http://127.0.0.1:8890").rstrip("/")

passed = 0
failed = []


def call(method, path, payload=None, timeout=25):
    """Return (status, parsed_json) for one request."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def call_raw(method, path, timeout=25):
    """
    Return (status, body_text) for one request, without parsing JSON.

    `call` assumes every response is JSON, which is true of the API and false
    of the pages and assets. Using it on `GET /` would parse a web page as
    JSON and report a parse failure that says nothing about the page.
    """
    req = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def check(label, ok, detail=""):
    global passed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed.append(label)
        print(f"  FAIL  {label}   {detail}")


def section(title):
    print(f"\n{title}")


def read_stream(path, accept="text/event-stream", max_events=3, timeout=12):
    """
    Open an SSE stream and collect up to max_events data frames.

    Returns (events, error) where error is a status code when the server
    refused the stream before sending anything.
    """
    req = urllib.request.Request(
        BASE + path,
        headers={"Accept": accept, "Cache-Control": "no-cache"},
    )
    events = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = ""
            deadline = __import__("time").monotonic() + timeout
            while len(events) < max_events and __import__("time").monotonic() < deadline:
                chunk = resp.read(1)
                if not chunk:
                    break
                raw += chunk.decode("utf-8", "replace")
                while "\n\n" in raw:
                    frame, raw = raw.split("\n\n", 1)
                    for line in frame.splitlines():
                        if line.startswith("data: "):
                            try:
                                events.append(json.loads(line[6:]))
                            except json.JSONDecodeError:
                                pass
            return events, None
    except urllib.error.HTTPError as exc:
        return [], exc.code


def main():
    print(f"Verifying {BASE}")

    # ─── Discovery ──────────────────────────────────────────────────────
    section("Discovery")
    status, health = call("GET", "/health")
    check("GET /health", status == 200, status)
    check("status ok", health.get("status") == "ok", health)
    connected = health.get("mt5_connected", False)
    check("MT5 connected", connected, "is the terminal running and logged in?")

    status, routes = call("GET", "/routes")
    check("GET /routes", status == 200, status)
    check("routes registered", len(routes.get("routes", [])) >= 40,
          routes.get("count"))
    print(f"        {routes.get('count')} routes")

    status, enums_map = call("GET", "/enums")
    check("GET /enums", status == 200, status)
    e = enums_map.get("enums", {})
    check("order_types advertised", "buy" in e.get("order_types", {}), list(e))
    check("timeframes advertised", "M1" in e.get("timeframes", {}))
    check("trade_actions advertised", "deal" in e.get("trade_actions", {}))
    check("filling_modes advertised", "return" in e.get("filling_modes", {}))
    check("retcode glossary present", len(enums_map.get("retcodes", {})) > 20,
          len(enums_map.get("retcodes", {})))
    check("package version reported", bool(enums_map.get("package_version")),
          enums_map.get("package_version"))

    status, streams = call("GET", "/streams")
    check("GET /streams", status == 200, status)
    check("streams documented", len(streams.get("streams", [])) >= 3)

    status, totals = call("GET", "/totals")
    check("GET /totals", status == 200, status)
    check("symbol count reported", totals.get("symbols", 0) > 0, totals)

    if not connected:
        print("\nMT5 not connected - stopping after discovery checks.")
        return report()

    # ─── Account ─────────────────────────────────────────────────────────
    section("Account")
    status, account = call("GET", "/account")
    check("GET /account", status == 200, status)
    for field in ("balance", "equity", "margin_free", "leverage", "currency"):
        check(f"has {field}", field in account)
    check("trade mode named", account.get("_trade_mode") is not None,
          account.get("_trade_mode"))
    check("margin mode named", account.get("_margin_mode") is not None)
    print(f"        balance={account.get('balance')} {account.get('currency')} "
          f"mode={account.get('_trade_mode')}")

    status, terminal = call("GET", "/terminal")
    check("GET /terminal", status == 200, status)
    check("build present", bool(terminal.get("build")))

    status, err = call("GET", "/last-error")
    check("GET /last-error", status == 200, status)
    check("error has code", "code" in err, err)

    # ─── Symbols ────────────────────────────────────────────────────────
    section("Symbols")
    status, symbols = call("GET", "/symbols")
    check("GET /symbols", status == 200, status)
    check("symbols found", symbols.get("count", 0) > 0, symbols.get("count"))

    target = None
    for name in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
        if any(s["name"] == name for s in symbols.get("symbols", [])):
            target = name
            break
    target = target or symbols["symbols"][0]["name"]
    print(f"        probing {target}")

    status, sym = call("GET", f"/symbol/{target}")
    check("GET /symbol/{symbol}", status == 200, status)
    check("has digits", isinstance(sym.get("digits"), int))
    check("has volume_min", sym.get("volume_min", 0) > 0)
    check("trade mode named", sym.get("_trade_mode") is not None, sym.get("_trade_mode"))

    d = sym.get("_derived", {})
    check("derived present", bool(d))
    check("has pip_size", d.get("pip_size", 0) > 0, d.get("pip_size"))
    check("has point_size", d.get("point_size", 0) > 0, d.get("point_size"))
    check("pip = 10 * point",
          abs(d.get("pip_size", 0) - 10 * d.get("point_size", 0)) < 1e-12,
          f"pip={d.get('pip_size')} point={d.get('point_size')}")
    check("pip_decimals consistent",
          d.get("pip_decimals") == max(sym.get("digits", 0) - 1, 0),
          d.get("pip_decimals"))
    check("trade_mode in derived",
          str(d.get("trade_mode", "")).upper() in
          ("FULL", "LONG_ONLY", "SHORT_ONLY", "CLOSE_ONLY", "DISABLED", "UNKNOWN"),
          d.get("trade_mode"))
    # Lowercase so the value round-trips: the same string is accepted back by
    # GET /symbols?trade_mode=
    check("trade_mode matches an enums key",
          d.get("trade_mode") in e.get("symbol_trade_modes", {}),
          d.get("trade_mode"))
    check("lot_info has step", d.get("lot_info", {}).get("lot_step", 0) > 0)
    check("order_rules present", "min_stop_distance_points" in d.get("order_rules", {}))
    check("market_book info present", "available" in d.get("market_book", {}))

    digits = sym.get("digits", 5)
    if digits >= 2:
        expected = 10 ** (1 - digits)
        check("pip size matches digit convention",
              abs(d.get("pip_size", 0) - expected) < 1e-15,
              f"got {d.get('pip_size')} expected {expected}")

    pip_value = d.get("pip_value_per_lot")
    print(f"        {target}: {digits}d pip={d.get('pip_size')} "
          f"pip_value/lot={pip_value} "
          f"min_stop={d.get('order_rules', {}).get('min_stop_distance_points')}pt "
          f"mode={d.get('trade_mode')}")

    status, _ = call("POST", f"/symbol/{target}/select", {"enable": True})
    check("POST /symbol/{symbol}/select", status == 200, status)

    status, found = call("GET", f"/symbols/search?q={target[:3]}")
    check("GET /symbols/search", status == 200, status)
    check("search finds the symbol", found.get("count", 0) > 0, found.get("count"))

    status, bad = call("GET", "/symbol/NOT_A_REAL_SYMBOL_XYZ")
    check("unknown symbol -> 404", status == 404, status)
    check("404 body is JSON", "error" in bad, bad)

    # ─── Market data ────────────────────────────────────────────────────
    section("Market data")
    status, tick = call("GET", f"/tick/{target}")
    check("GET /tick/{symbol}", status == 200, status)
    check("has bid", tick.get("bid", 0) > 0, tick)
    check("has ask", tick.get("ask", 0) > 0)
    check("ask >= bid", tick.get("ask", 0) >= tick.get("bid", 0))

    status, ticks = call("GET", "/ticks")
    check("GET /ticks", status == 200, status)
    check("ticks is a dict", isinstance(ticks, dict))

    status, scoped = call("GET", f"/ticks?symbols={target}")
    check("GET /ticks?symbols=", status == 200, status)
    check("scoped tick present", target in scoped, list(scoped))

    status, candles = call("GET", f"/candles/{target}?timeframe=M5&count=5")
    check("GET /candles (count)", status == 200, status)
    check("candles returned", candles.get("count", 0) > 0, candles.get("count"))
    check("timeframe named", candles.get("timeframe_name") == "M5",
          candles.get("timeframe_name"))
    bar = (candles.get("candles") or [{}])[0]
    check("candle has OHLC", all(k in bar for k in ("open", "high", "low", "close")))
    check("high >= low", bar.get("high", 0) >= bar.get("low", 0))

    status, pos_bars = call("GET", f"/candles/{target}?timeframe=M1&start=0&count=3")
    check("GET /candles (positional)", status == 200, status)
    check("positional bars returned", pos_bars.get("count", 0) > 0)

    status, ranged = call(
        "GET",
        f"/candles/{target}?timeframe=H1&from=2026-09-01&to=2026-09-05",
    )
    check("GET /candles (range)", status == 200, status)
    check("range bars returned", isinstance(ranged.get("candles"), list))

    status, _ = call("GET", f"/candles/{target}?timeframe=BOGUS")
    check("bad timeframe -> 400", status == 400, status)

    status, _ = call("GET", f"/candles/{target}?count=99999")
    check("oversized count -> 400", status == 400, status)

    status, th = call(
        "GET",
        f"/ticks/history?symbol={target}&from=2026-09-01&to=2026-09-02&flags=info",
    )
    check("GET /ticks/history", status == 200, status)
    check("ticks history is a list", isinstance(th.get("ticks"), list))

    status, _ = call("GET", f"/ticks/history?symbol={target}")
    check("ticks/history without from -> 400", status == 400, status)

    # ─── Positions and orders ───────────────────────────────────────────
    section("Positions and orders")
    status, positions = call("GET", "/positions")
    check("GET /positions", status == 200, status)
    check("positions is a list", isinstance(positions.get("positions"), list))
    check("count matches list", positions.get("count") == len(positions.get("positions", [])))

    status, orders = call("GET", "/orders")
    check("GET /orders", status == 200, status)

    status, portfolio = call("GET", "/portfolio")
    check("GET /portfolio", status == 200, status)
    check("portfolio has summary", "summary" in portfolio, list(portfolio))
    check("portfolio has account", "account" in portfolio)

    # ─── Calculators ────────────────────────────────────────────────────
    section("Calculators")
    status, margin = call("POST", "/calc/margin",
                          {"symbol": target, "volume": 0.01, "order_type": "buy"})
    check("POST /calc/margin", status == 200, status)
    check("margin computed", margin.get("margin", 0) > 0, margin)
    check("price defaulted to tick", margin.get("price", 0) > 0)

    status, by_name = call("POST", "/calc/margin",
                           {"symbol": target, "volume": 0.01, "order_type": "sell"})
    check("calc/margin accepts order_type name", status == 200, status)

    status, profit = call("POST", "/calc/profit",
                          {"symbol": target, "volume": 0.01, "order_type": "buy",
                           "open_price": tick["bid"],
                           "close_price": tick["bid"] + d["pip_size"]})
    check("POST /calc/profit", status == 200, status)
    check("1 pip on 0.01 lot is positive", profit.get("profit", 0) > 0, profit)
    expected = 0.01 * (pip_value or 0)
    if expected:
        check("profit matches pip_value_per_lot",
              abs(profit["profit"] - expected) / expected < 0.05,
              f"got {profit['profit']} expected ~{expected}")

    status, sized = call("POST", "/calc/size",
                         {"symbol": target, "risk_amount": 50, "stop_pips": 20})
    check("POST /calc/size", status == 200, status)
    check("lots computed", sized.get("lots", 0) > 0, sized)
    check("actual risk within target",
          sized.get("actual_risk", 1e9) <= 50 * 1.05,
          f"risk={sized.get('actual_risk')} lots={sized.get('lots')}")
    print(f"        risk 50 over 20 pips -> {sized.get('lots')} lots "
          f"(risk {sized.get('actual_risk')})")

    status, _ = call("POST", "/calc/size", {"symbol": target, "stop_pips": 20})
    check("calc/size without risk_amount -> 400", status == 400, status)

    # ─── Order validation ───────────────────────────────────────────────
    section("Order validation (no orders placed)")
    status, _ = call("POST", "/order", {})
    check("order without symbol -> 400", status == 400, status)

    status, _ = call("POST", "/order", {"symbol": target, "volume": 0})
    check("order with zero volume -> 400", status == 400, status)

    status, _ = call("POST", "/order", {"symbol": target, "volume": 0.01, "order_type": "wat"})
    check("order with bad type -> 400", status == 400, status)

    status, _ = call("POST", "/order", {"symbol": target, "volume": 0.01,
                                         "order_type": "buy_limit"})
    check("pending order without price -> 400", status == 400, status)

    status, _ = call("POST", "/order", {"symbol": "NOT_A_SYMBOL", "volume": 0.01,
                                         "order_type": "buy"})
    check("order on unknown symbol -> 404", status == 404, status)

    status, _ = call("POST", "/modify", {"ticket": 1})
    check("modify with no sl/tp -> 400", status == 400, status)

    status, _ = call("POST", "/close", {"ticket": 0})
    check("close ticket 0 -> 400", status == 400, status)

    status, _ = call("POST", "/close", {"ticket": 999999999})
    check("close unknown ticket -> non-200", status != 200, status)

    status, _ = call("POST", "/cancel", {"ticket": 999999999})
    check("cancel unknown ticket -> non-200", status != 200, status)

    status, _ = call("POST", "/order/check", {"symbol": target, "volume": -1})
    check("negative volume -> 400", status == 400, status)

    status, _ = call("POST", "/buy", {"symbol": target, "volume": 0.01,
                                       "comment": "x" * 100})
    check("over-long comment -> 400", status == 400, status)

    # ─── History ────────────────────────────────────────────────────────
    section("History")
    status, ht = call("GET", "/history/totals")
    check("GET /history/totals", status == 200, status)
    check("deal count present", "deals" in ht, ht)

    status, deals = call("GET", "/history/deals")
    check("GET /history/deals", status == 200, status)
    check("deals is a list", isinstance(deals.get("deals"), list))
    print(f"        {deals.get('count', 0)} deals in the default window")

    status, horders = call("GET", "/history/orders")
    check("GET /history/orders", status == 200, status)

    status, summary = call("GET", "/history/summary")
    check("GET /history/summary", status == 200, status)
    check("summary has net", "net" in summary, summary)

    status, _ = call("GET", "/history/deals?from=bogus")
    check("bad date -> 400", status == 400, status)

    status, _ = call("GET", "/history/deals?from=2026-02-01&to=2026-01-01")
    check("reversed range -> 400", status == 400, status)

    # ─── Market book ────────────────────────────────────────────────────
    section("Market book")
    status, book = call("GET", f"/marketbook/{target}")
    if status == 200:
        check("book has sides", "bids" in book and "asks" in book, list(book))
        check("book reports emptiness", "empty" in book)
        if book.get("empty") is False:
            check("best bid/ask present",
                  book.get("best_bid") is not None and book.get("best_ask") is not None,
                  book)
            check("spread computed", book.get("spread") is not None, book)
            print(f"        depth {book.get('levels')} levels, "
                  f"spread {book.get('spread')}, "
                  f"imbalance {book.get('imbalance')}")
    else:
        # Retail brokers commonly withhold DOM. That must read as a clear,
        # non-server-error answer rather than a 500.
        check("marketbook unavailable -> 409", status == 409, status)
        check("marketbook error explains why",
              "book" in book.get("error", "").lower(), book)
        print(f"        broker does not offer DOM here (HTTP {status})")

    status, subs = call("GET", "/marketbook/subscribed")
    check("GET /marketbook/subscribed", status == 200, status)
    check("subscribed is a list", isinstance(subs.get("subscribed"), list))

    status, books = call("GET", f"/marketbook?symbols={target}")
    check("GET /marketbook (multi)", status == 200, status)
    check("books keyed by symbol", target in books.get("books", {}))

    status, _ = call("GET", "/marketbook")
    check("marketbook without symbols -> 400", status == 400, status)

    # ─── Routing ────────────────────────────────────────────────────────
    section("Routing")
    status, nf = call("GET", "/definitely/not/a/route")
    check("unknown route -> 404", status == 404, status)
    check("404 lists routes endpoint", "/routes" in nf.get("error", ""), nf)

    status, _ = call("GET", "/positions/0")
    check("positions/0 -> 400", status == 400, status)

    status, _ = call("POST", "/order", None)
    check("POST with no body -> 400", status == 400, status)

    # ─── Live streams ───────────────────────────────────────────────────
    section("Live streams (SSE)")
    events, code = read_stream(f"/stream/ticks?symbols={target}&interval=0.5", max_events=2)
    if code:
        check("ticks stream opens", False, f"HTTP {code}")
    else:
        check("ticks stream opens", True)
        opened = [e for e in events if e.get("status") == "streaming"]
        check("stream sends an open event", bool(opened), events[:1])
        check("stream sends tick data",
              any("symbols" in e for e in events), events)

    events, code = read_stream("/stream/portfolio?interval=0.5", max_events=2)
    if code:
        check("portfolio stream opens", False, f"HTTP {code}")
    else:
        check("portfolio stream opens", True)
        check("portfolio sends equity",
              any("equity" in e for e in events), events)

    events, code = read_stream("/stream/nonsense")
    check("unknown stream -> 404", code == 404, code)

    # ─── Threading ──────────────────────────────────────────────────────
    section("Concurrency (streams must not block normal calls)")
    import threading
    results = {}

    def hit(name, path):
        results[name] = call("GET", path)[0]

    stream_thread = threading.Thread(
        target=hit, args=("stream", f"/stream/ticks?symbols={target}&interval=1")
    )
    stream_thread.start()
    import time as _time
    _time.sleep(0.6)
    started = _time.monotonic()
    status = call("GET", "/health")[0]
    elapsed = _time.monotonic() - started
    stream_thread.join(timeout=3)
    check("/health responds while a stream is open", status == 200, status)
    check("health was not blocked", elapsed < 3, f"{elapsed:.2f}s")

    # ── Regressions ───────────────────────────────────────────────────
    # Each of these was a real defect found by exercising the gateway.
    section("Regression guards")
    status, enc = call("GET", "/symbol/" + quote("Step Index 200"))
    check("URL-encoded symbol name decodes", status == 200, status)
    check("symbol keeps the broker's casing", enc.get("name") == "Step Index 200",
          enc.get("name"))

    status, lower = call("GET", "/symbol/" + quote("step index 200"))
    check("wrong-case name still resolves",
          status == 200 and lower.get("name") == "Step Index 200", status)

    status, _ = call("GET", "/candles/" + quote("Step Index 200") + "?timeframe=M1&count=20")
    check("unwatched symbol reads without manual select", status == 200, status)

    for path in ("/candles/NOSUCHSYM?count=5", "/tick/NOSUCHSYM"):
        status, _ = call("GET", path)
        check(f"unknown symbol -> 404 ({path.split('?')[0]})", status == 404, status)

    status, hs = call("GET", "/health")
    check("health reports the broker clock offset",
          isinstance(hs.get("time_source", {}).get("offset_seconds"), (int, float)),
          hs.get("time_source"))

    status, sized = call("POST", "/calc/size",
                         {"symbol": target, "risk_amount": 50, "stop_pips": 20})
    check("calc/size does not lose a step to float error",
          abs(sized.get("lots", 0) - 0.25) < 1e-9, sized.get("lots"))
    check("calc/size risk never exceeds the budget",
          sized.get("actual_risk", 1e9) <= 50.0000001, sized.get("actual_risk"))

    status, _ = call("GET", "/positions?magic=987654")
    check("/positions?magic= filter exists", status == 200, status)
    status, _ = call("GET", "/orders?magic=987654")
    check("/orders?magic= filter exists", status == 200, status)

    wide = (datetime.now() - timedelta(days=400)).date().isoformat()
    status, wc = call("GET", f"/candles/{target}?timeframe=M1&from={wide}&to={wide[:8]}28")
    check("wide candle window is bounded", status == 200, status)
    check("bounded window reports truncation", wc.get("truncated") is True, wc.get("count"))

    status, ht = call("GET", "/history/deals?from=2000-01-01&to=2030-01-01")
    check("wide history window is bounded", status == 200, status)
    check("history window is capped to one year",
          ht.get("from", "")[:4] >= "2025", ht.get("from"))

    # ── Web UI ───────────────────────────────────────────────────────────
    # The dashboard is an optional extension, so its absence is not a failure.
    # What must hold when it is present: pages render, assets resolve, and a
    # wildcard route cannot be used to read outside the assets root.
    section("Web UI")
    status, index_html = call_raw("GET", "/")
    ui_present = status == 200
    if not ui_present:
        print("  skip  web UI not registered (frontend absent?)")
    else:
        check("GET / serves HTML",
              index_html.startswith("<!doctype html"), index_html[:40])
        check("page is not JSON",
              not index_html.lstrip().startswith("{"), "returned JSON to a page")
        check("header partial was spliced in", 'class="topbar"' in index_html)
        check("footer partial was spliced in", 'class="footer"' in index_html)
        check("no unspliced include markers remain",
              "<!--#include" not in index_html)
        check("bootstrap payload injected",
              'id="bootstrap"' in index_html)
        check("page loads no external origins",
              'src="http' not in index_html and 'href="http' not in index_html)
        check("tag balance: html",
              index_html.count("<html") == index_html.count("</html>"))
        check("tag balance: body",
              index_html.count("<body") == index_html.count("</body>"))

        # Assets live in nested folders, so the route is a `{path...}`
        # wildcard. Before it existed, `/assets/{path}` silently matched
        # nothing at all and every stylesheet 404'd.
        status, css = call_raw("GET", "/assets/css/base.css")
        check("nested asset resolves", status == 200, status)
        status, js = call_raw("GET", "/assets/js/lib/api.js")
        check("nested script resolves", status == 200, status)
        status, _ = call_raw("GET", "/assets/css/pages/dashboard.css")
        check("page-scoped stylesheet resolves", status == 200, status)

        # The wildcard spans `/`, so `..` reaches the handler. Confining the
        # resolved path to the assets root is the only thing stopping a read
        # of the Python source, which is why each of these is checked.
        for attempt in ("/assets/../dashboard/views.py",
                        "/assets/../../backend/dashboard/assets.py",
                        "/assets/css/../../../dashboard/__init__.py",
                        "/assets/..%2f..%2fdashboard%2fviews.py",
                        "/assets/css/%2e%2e/%2e%2e/dashboard/views.py"):
            status, body = call_raw("GET", attempt)
            check(f"asset traversal refused: {attempt[-34:]}",
                  status == 404, f"got {status}")

        status, _ = call_raw("GET", "/ui/nope")
        check("unknown page is 404", status == 404, status)
        status, _ = call_raw("GET", "/assets/nope.css")
        check("unknown asset is 404", status == 404, status)

    # ── Research API ──────────────────────────────────────────────────────
    # These are not "is the route registered" checks. The research layer runs
    # *inside* the gateway and reads market data back over HTTP, so a bug in
    # which port it calls leaves every route perfectly registered while every
    # one that touches data returns 500. That is exactly what happened: the
    # port was a literal in two places, so running on any other port broke the
    # research layer completely and no test noticed. Calling the endpoints is
    # the only check that catches it.
    section("Research API")
    status, research = call("GET", "/research")
    if status != 200:
        print("  skip  research API not registered (knowledgebase absent?)")
    else:
        check("GET /research", status == 200, status)

        status, cat = call("GET", "/research/catalogue")
        check("catalogue lists indicators", status == 200 and cat.get("indicators"),
              status)
        check("catalogue lists patterns",
              status == 200 and cat.get("patterns"), status)
        check("catalogue lists entry rules",
              status == 200 and cat.get("entry_rules"), status)

        # The decisive one: this path goes out over HTTP and back.
        status, scan = call("POST", "/research/patterns/scan",
                            {"symbol": target, "timeframe": "M15", "count": 300},
                            timeout=180)
        check("pattern scan reaches its own data source",
              status == 200 and scan.get("matches") is not None,
              f"{status} {str(scan)[:60]}")
        check("pattern scan reports the market baseline",
              status == 200 and "baseline_pct" in
              str(list((scan.get("follow_through") or {}).values())),
              "no baseline in follow-through")
        check("busiest-pattern rate is reported",
              status == 200 and scan.get("busiest_pattern_per_100_bars")
              is not None, "missing")

        status, bt = call("POST", "/research/backtest",
                          {"strategy": "rsi_reversion_14", "symbol": target,
                           "timeframe": "M15", "count": 1500},
                          timeout=180)
        check("backtest runs", status == 200 and bt.get("verdict"),
              f"{status} {str(bt)[:60]}")
        check("backtest reports a train/test split",
              status == 200 and bt.get("split_check") is not None, "missing")

        status, _ = call("POST", "/research/indicator",
                         {"symbol": target, "indicator": "definitely_not_real"})
        check("unknown indicator is rejected", status == 400, status)
        status, _ = call("POST", "/research/strategy/validate", {})
        check("empty strategy spec is rejected", status == 200, status)

    return report()


def report():
    print("\n" + "=" * 62)
    if failed:
        print(f"  {passed} passed, {len(failed)} FAILED")
        for name in failed:
            print(f"    - {name}")
        return 1
    print(f"  all {passed} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
