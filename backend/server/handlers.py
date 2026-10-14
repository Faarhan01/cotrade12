"""
server — HTTP Request Handlers
===============================
Binds the HTTP surface onto the cony engine.

Every route takes the same shape - validate, delegate, shape the response -
and does no MT5 work itself, so the engine stays the only place that knows
how MetaTrader 5 is actually called.
"""

from datetime import datetime, timedelta
import logging
import math
import os
import traceback

from server import validation as v
from server.errors import BadRequest
from server.routes import Router
from cony import enums
from cony.mt5_engine import MT5Engine

# Standard logging only. server/ must not import deamon/, or the dependency
# would point backwards (deamon -> server -> deamon) and the layering that
# makes either half swappable would collapse.
logger = logging.getLogger("cony.server")

# History grows without bound, so both the window and the row count are capped.
HISTORY_MAX_DAYS = 365
HISTORY_MAX_ROWS = 20000


class RouteHandlers:
    """Registers every API route against a router."""

    def __init__(self, engine: MT5Engine, router: Router,
                 base: str = "http://127.0.0.1:8890"):
        # Where this gateway is listening. Passed in rather than imported
        # because `server/` must not reach up into `deamon/`; the caller owns
        # the configuration and hands it down.
        self.base = base
        self.engine = engine
        self.router = router
        self.setup_routes()

    def setup_routes(self):
        r = self.router
        engine = self.engine

        # ─── Discovery ─────────────────────────────────────────────────
        # An agent calls these first to learn what it may send.

        @r.get("/health")
        def health(params, query, body):
            payload = {
                "status": "ok",
                "service": "cony-gateway",
                "mt5_connected": engine.is_connected,
                "connection": engine._conn.get_connection_info(),
            }
            if engine.is_connected:
                # MT5 reports broker server time, so publish the offset rather
                # than let a caller mistake it for UTC.
                payload["time_source"] = {
                    "mt5": "broker server time",
                    "offset_seconds": engine.clock_offset(),
                }
                payload["symbol_cache"] = engine.symbol_cache_info()
            return payload

        @r.post("/symbol-cache/clear")
        def clear_symbol_cache(params, query, body):
            """
            Drop the cached symbol-name map.

            Only needed if the broker adds symbols mid-session and a caller
            needs the new name immediately; normal misses already force one
            rebuild before reporting a name as unknown.
            """
            engine.invalidate_symbol_cache()
            return {"success": True, "symbol_cache": engine.symbol_cache_info()}

        @r.get("/routes")
        def routes(params, query, body):
            return {
                "routes": r.list_routes(),
                "count": len(r.list_routes()),
            }

        @r.get("/enums")
        def enums_map(params, query, body):
            """
            Every name-to-integer map the gateway accepts, plus the full
            trade return code glossary.
            """
            return {
                "enums": enums.all_enums(),
                "retcodes": enums.retcode_glossary(),
                "package_version": engine.package_version(),
            }

        @r.get("/streams")
        def streams(params, query, body):
            """
            The live feeds, so a caller can discover streaming without being
            told the URLs. Each is plain SSE: send Accept: text/event-stream
            and read the frames.
            """
            return {
                "protocol": "text/event-stream",
                "streams": [
                    {
                        "path": "/stream/ticks",
                        "params": "symbols=EURUSD,GBPUSD&interval=1&book=false",
                        "emits": "tick",
                        "note": "Only symbols whose price moved are sent. "
                                "symbols defaults to whatever is open.",
                    },
                    {
                        "path": "/stream/marketbook",
                        "params": "symbols=EURUSD&interval=1",
                        "emits": "marketbook",
                        "note": "Depth of market; subscribes on connect.",
                    },
                    {
                        "path": "/stream/portfolio",
                        "params": "interval=2&book=false",
                        "emits": "portfolio",
                        "note": "Account and open positions together, for live PnL.",
                    },
                ],
            }

        # ─── Connection ─────────────────────────────────────────────────

        @r.post("/connect")
        def connect(params, query, body):
            info = engine._conn.connect(
                login=body.get("login"),
                password=body.get("password"),
                server=body.get("server"),
                path=body.get("path"),
                timeout=body.get("timeout"),
            )
            engine._conn.start_auto_reconnect()
            return {"success": True, "connection": info}

        @r.post("/disconnect")
        def disconnect(params, query, body):
            engine._conn.disconnect()
            return {"success": True, "mt5_connected": False}

        @r.post("/login")
        def login(params, query, body):
            """
            Switch to a specific account. Distinct from /connect, which just
            attaches to whichever account the terminal is already on.
            """
            account = v.integer(body.get("login"), "login", minimum=1)
            password = body.get("password")
            if not password:
                raise BadRequest("'password' is required")
            return {"success": True, "account": engine.login(
                account, str(password), body.get("server")
            )}

        @r.get("/last-error")
        def last_error(params, query, body):
            return engine.last_error()

        # ─── Account and terminal ──────────────────────────────────────

        @r.get("/account")
        def account(params, query, body):
            return engine.get_account_info()

        @r.get("/terminal")
        def terminal(params, query, body):
            return engine.get_terminal_info()

        @r.get("/totals")
        def totals(params, query, body):
            """Counts only, for deciding whether a full fetch is worth it."""
            return engine.get_totals()

        # ─── Symbols ───────────────────────────────────────────────────

        @r.get("/symbols")
        def symbols(params, query, body):
            group = query.get("group")
            found = engine.get_symbols(group=group)
            if "visible" in query:
                want = v.boolean(query.get("visible"), default=True)
                found = [s for s in found if bool(s.get("visible")) is want]
            if query.get("trade_mode"):
                mode = v._from_map(
                    query["trade_mode"], enums.SYMBOL_TRADE_MODES,
                    enums.SYMBOL_TRADE_MODE_NAMES, "trade_mode",
                )
                found = [s for s in found if s.get("trade_mode") == mode]
            return {"count": len(found), "symbols": found}

        @r.get("/symbols/search")
        def symbol_search(params, query, body):
            """Substring match on symbol name or description."""
            needle = (query.get("q") or "").strip().upper()
            if not needle:
                raise BadRequest("'q' is required")
            found = engine.get_symbols()
            hits = [
                s for s in found
                if needle in s.get("name", "").upper()
                or needle in (s.get("description") or "").upper()
            ]
            return {"count": len(hits), "query": needle, "symbols": hits}

        @r.get("/symbol/{symbol}")
        def symbol_info(params, query, body):
            return engine.get_symbol_info(v.symbol(params["symbol"]))

        @r.post("/symbol/{symbol}/select")
        def symbol_select(params, query, body):
            name = v.symbol(params["symbol"])
            enable = v.boolean(body.get("enable"), default=True)
            engine.select_symbol(name, enable)
            return {"success": True, "symbol": name, "selected": enable}

        # ─── Ticks ─────────────────────────────────────────────────────

        @r.get("/tick/{symbol}")
        def tick(params, query, body):
            return engine.get_tick(v.symbol(params["symbol"]))

        @r.get("/ticks")
        def ticks(params, query, body):
            names = v.symbol_list(query.get("symbols")) or None
            return engine.get_all_ticks(names)

        @r.get("/ticks/history")
        def tick_history(params, query, body):
            """
            Historical ticks. Either ?count=N from ?from=, or a ?from=/?to=
            range. Use flags=trade for last/volume when the broker allows it.

            Both forms are capped at MAX_TICKS. A single day of EURUSD is
            ~150k rows and ~29 MB of JSON, so an unbounded range would happily
            monopolise the daemon for one request.
            """
            name = v.symbol(query.get("symbol"))
            flags = v.copy_ticks_flag(query.get("flags"))

            if query.get("to"):
                start, end = v.date_range(query.get("from"), query.get("to"), default_days=1)
                ticks = engine.copy_ticks_range(name, start, end, flags)
            else:
                count = v.integer(query.get("count", 1000), "count",
                                  minimum=1, maximum=v.MAX_TICKS)
                if query.get("from"):
                    start = v.when(query["from"], "from")
                else:
                    raise BadRequest(
                        "Provide 'from' (ISO datetime) with 'count', or both "
                        "'from' and 'to'"
                    )
                ticks = engine.copy_ticks_from(name, start, count, flags)

            limit = v.MAX_TICKS
            truncated = len(ticks) > limit
            if truncated:
                ticks = ticks[:limit]

            payload = {
                "symbol": name,
                "count": len(ticks),
                "returned": len(ticks),
                "truncated": truncated,
                "max_ticks": limit,
                "ticks": ticks,
            }
            if truncated:
                payload["note"] = (
                    f"Result capped at {limit} ticks. Narrow the from/to "
                    f"window, or request several smaller ranges."
                )
            return payload

        # ─── Candles ───────────────────────────────────────────────────

        @r.get("/candles/{symbol}")
        def candles(params, query, body):
            """
            Bars, newest last. Three ways to ask:
              ?count=N                 - N bars back from now
              ?from=&to=               - every bar in the window
              ?start=N&count=M         - positional, 0 is the forming bar

            A date window is narrowed to what MAX_CANDLES can hold *before* it
            reaches the terminal. Truncating afterwards would be useless: asking
            for a decade of M1 still makes MT5 read every bar in that decade.
            """
            name = v.symbol(params["symbol"])
            tf = v.timeframe(query.get("timeframe"))
            narrowed = False

            if query.get("to") or query.get("from"):
                start, end = v.date_range(query.get("from"), query.get("to"), default_days=7)
                narrowed = False
                span = enums.timeframe_seconds(tf)
                if span:
                    widest = timedelta(seconds=span * v.MAX_CANDLES)
                    if end - start > widest:
                        end = start + widest
                        narrowed = True
                        logger.info(
                            "narrowed %s %s window to %d bars",
                            name, tf, v.MAX_CANDLES,
                        )
                bars = engine.copy_rates_range(name, tf, start, end)
            elif query.get("start") is not None:
                offset = v.integer(query["start"], "start", minimum=0, maximum=v.MAX_CANDLES)
                count = v.integer(query.get("count", 100), "count",
                                  minimum=1, maximum=v.MAX_CANDLES)
                bars = engine.copy_rates_from_pos(name, tf, offset, count)
            else:
                count = v.integer(query.get("count", 100), "count",
                                  minimum=1, maximum=v.MAX_CANDLES)
                bars = engine.copy_rates(name, tf, count)

            # A wide from/to window can return far more than was asked for.
            limit = v.MAX_CANDLES
            truncated = len(bars) > limit
            if truncated:
                bars = bars[:limit]

            payload = {
                "symbol": name,
                "timeframe": tf,
                "timeframe_name": enums.TIMEFRAME_NAMES.get(tf),
                "count": len(bars),
                "candles": bars,
            }
            # Report either kind of trimming: the window being narrowed, or
            # more bars surviving than one response carries.
            if narrowed or truncated:
                payload["truncated"] = True
                payload["max_candles"] = limit
                payload["note"] = (
                    f"Window narrowed to {v.MAX_CANDLES} bars from "
                    f"{start.isoformat()}. Use ?count=N for the most recent "
                    f"bars, or a narrower from/to range."
                )
            return payload

        # ─── Positions and orders ───────────────────────────────────────

        @r.get("/positions")
        def positions(params, query, body):
            found = engine.get_positions(
                symbol=v.optional_symbol(query.get("symbol")),
                ticket=v.order_id(query["ticket"]) if query.get("ticket") else None,
            )
            if query.get("magic") is not None:
                magic = v.magic(query["magic"])
                found = [p for p in found if p.get("magic") == magic]
            return {"count": len(found), "positions": found}

        @r.get("/positions/{ticket}")
        def position(params, query, body):
            return engine.get_position(v.order_id(params["ticket"]))

        @r.get("/orders")
        def orders(params, query, body):
            found = engine.get_orders(
                symbol=v.optional_symbol(query.get("symbol")),
                ticket=v.order_id(query["ticket"]) if query.get("ticket") else None,
            )
            if query.get("magic") is not None:
                magic = v.magic(query["magic"])
                found = [o for o in found if o.get("magic") == magic]
            return {"count": len(found), "orders": found}

        @r.get("/portfolio")
        def portfolio(params, query, body):
            """
            Account plus open risk in one call: positions carry live PnL, and
            the exposure summary shows total risk against equity.
            """
            info = engine.get_account_info()
            open_positions = engine.get_positions()
            exposure = 0.0
            for pos in open_positions:
                exposure += abs(pos.get("volume", 0))
            floating = sum(p.get("profit", 0.0) for p in open_positions)
            return {
                "account": {
                    "balance": info.get("balance"),
                    "equity": info.get("equity"),
                    "margin": info.get("margin"),
                    "margin_free": info.get("margin_free"),
                    "margin_level": info.get("margin_level"),
                    "currency": info.get("currency"),
                    "leverage": info.get("leverage"),
                },
                "summary": {
                    "position_count": len(open_positions),
                    "total_volume": round(exposure, 8),
                    "floating_profit": round(floating, 2),
                },
                "positions": open_positions,
            }

        # ─── Trading ───────────────────────────────────────────────────

        def _build_request(payload):
            """
            Turn caller input into an MT5 order_send request dict.

            type_filling is only set when the caller asked for one; otherwise
            it is left out so the engine can pick a mode the broker declares
            support for, which avoids retcode 10030 on stricter brokers.
            """
            request = {
                "symbol": v.symbol(payload.get("symbol")),
                "volume": v.number(payload.get("volume"), "volume", minimum=1e-5),
                "type": v.order_type(payload.get("order_type")),
                "action": v.trade_action(payload.get("action")),
                "type_filling": (
                    v.filling_mode(payload["type_filling"])
                    if payload.get("type_filling") not in (None, "")
                    else None
                ),
                "type_time": v.order_time(payload.get("type_time")),
                "deviation": v.integer(payload.get("deviation", 20), "deviation", minimum=0),
                "magic": v.magic(payload.get("magic", 0)),
                "comment": v.comment(payload.get("comment", "")),
                "sl": v.optional_number(payload.get("sl"), "sl"),
                "tp": v.optional_number(payload.get("tp"), "tp"),
                "price": v.optional_number(payload.get("price"), "price"),
                "position": v.order_id(payload["position"]) if payload.get("position") else None,
                "order": v.order_id(payload["order"]) if payload.get("order") else None,
                "expiration": v.when(payload["expiration"], "expiration") if payload.get("expiration") else None,
            }
            request = {k: val for k, val in request.items() if val is not None}

            # A pending order is meaningless without its trigger level. Catch it
            # here for a clear 400 rather than letting the broker refuse it
            # with an opaque retcode.
            pending = {
                enums.ORDER_TYPES["buy_limit"],
                enums.ORDER_TYPES["sell_limit"],
                enums.ORDER_TYPES["buy_stop"],
                enums.ORDER_TYPES["sell_stop"],
                enums.ORDER_TYPES["buy_stop_limit"],
                enums.ORDER_TYPES["sell_stop_limit"],
            }
            if request["type"] in pending and not request.get("price"):
                name = enums.ORDER_TYPE_NAMES.get(request["type"], request["type"])
                raise BadRequest(
                    f"'price' is required for a {name} order. "
                    f"Market orders (buy/sell) may omit it."
                )
            return request

        @r.post("/order/check")
        def order_check(params, query, body):
            """
            Dry run. Shows what the terminal would do and the margin it would
            reserve, without placing anything. Call this before /order.
            """
            result = engine.check_order(_build_request(body))
            retcode = result.get("retcode", 0)
            accepted = enums.retcode_name(retcode) in ("Done", "Done Partial")
            return {
                "success": accepted,
                "accepted": accepted,
                "retcode": retcode,
                "retcode_description": result.get("_retcode_description"),
                "check": result,
            }

        @r.post("/order")
        def order(params, query, body):
            request = _build_request(body)
            result = engine.execute_order(request)
            return {
                "success": True,
                "order_type": enums.ORDER_TYPE_NAMES.get(request["type"]),
                "result": result,
            }

        @r.post("/buy")
        def buy(params, query, body):
            """Market buy without assembling a request dict."""
            result = engine.buy(
                symbol=v.symbol(body.get("symbol")),
                volume=v.number(body.get("volume"), "volume", minimum=1e-5),
                sl=v.optional_number(body.get("sl"), "sl"),
                tp=v.optional_number(body.get("tp"), "tp"),
                comment=v.comment(body.get("comment", "")),
                magic=v.magic(body.get("magic", 0)),
                deviation=v.integer(body.get("deviation", 20), "deviation", minimum=0),
            )
            return {"success": True, "side": "buy", "result": result}

        @r.post("/sell")
        def sell(params, query, body):
            """Market sell without assembling a request dict."""
            result = engine.sell(
                symbol=v.symbol(body.get("symbol")),
                volume=v.number(body.get("volume"), "volume", minimum=1e-5),
                sl=v.optional_number(body.get("sl"), "sl"),
                tp=v.optional_number(body.get("tp"), "tp"),
                comment=v.comment(body.get("comment", "")),
                magic=v.magic(body.get("magic", 0)),
                deviation=v.integer(body.get("deviation", 20), "deviation", minimum=0),
            )
            return {"success": True, "side": "sell", "result": result}

        @r.post("/close")
        def close(params, query, body):
            ticket = v.order_id(body.get("ticket"))
            result = engine.close_position(
                ticket=ticket,
                volume=v.optional_number(body.get("volume"), "volume"),
                deviation=v.integer(body.get("deviation", 20), "deviation", minimum=0),
                magic=v.magic(body.get("magic", 0)),
                comment=v.comment(body.get("comment", "")),
            )
            return {"success": True, "ticket": ticket, "result": result}

        @r.post("/close-all")
        def close_all(params, query, body):
            results = engine.close_all(
                symbol=v.optional_symbol(body.get("symbol")),
                magic=v.magic(body.get("magic", 0)),
            )
            succeeded = sum(1 for entry in results if entry.get("success"))
            return {
                "success": True,
                "closed": succeeded,
                "attempted": len(results),
                "results": results,
            }

        @r.post("/modify")
        def modify(params, query, body):
            ticket = v.order_id(body.get("ticket"))
            sl = v.optional_number(body.get("sl"), "sl")
            tp = v.optional_number(body.get("tp"), "tp")
            if sl is None and tp is None:
                raise BadRequest("Provide at least one of 'sl' or 'tp'")
            result = engine.modify_position(ticket=ticket, sl=sl, tp=tp)
            return {"success": True, "ticket": ticket, "result": result}

        @r.post("/cancel")
        def cancel(params, query, body):
            ticket = v.order_id(body.get("ticket"))
            return {"success": True, "ticket": ticket,
                    "result": engine.cancel_order(ticket=ticket)}

        # ─── Calculators ───────────────────────────────────────────────

        @r.post("/calc/margin")
        def calc_margin(params, query, body):
            name = v.symbol(body.get("symbol"))
            volume = v.number(body.get("volume"), "volume", minimum=1e-5)
            otype = v.order_type(body.get("order_type"))
            price = v.optional_number(body.get("price"), "price")
            if price is None:
                tick = engine.get_tick(name)
                price = tick["ask"] if otype == enums.ORDER_TYPES["buy"] else tick["bid"]
            return {
                "symbol": name,
                "volume": volume,
                "price": price,
                "margin": engine.calc_margin(name, volume, otype, price),
            }

        @r.post("/calc/profit")
        def calc_profit(params, query, body):
            name = v.symbol(body.get("symbol"))
            volume = v.number(body.get("volume"), "volume", minimum=1e-5)
            otype = v.order_type(body.get("order_type"))
            open_price = v.number(body.get("open_price"), "open_price")
            close_price = v.number(body.get("close_price"), "close_price")
            return {
                "symbol": name,
                "volume": volume,
                "price_move": round(close_price - open_price, 12),
                "profit": engine.calc_profit(name, volume, otype, open_price, close_price),
            }

        @r.post("/calc/size")
        def calc_size(params, query, body):
            """
            Risk-based lot sizing, the calculation an agent otherwise has to
            assemble from pip_size and pip_value_per_lot by hand.

            Give a stop distance in pips and an amount to risk; get the lot
            size, already rounded to the symbol's step and clamped to its
            limits. Requires risk_amount to be present, which is the whole
            point of the endpoint.
            """
            name = v.symbol(body.get("symbol"))
            risk = v.number(body.get("risk_amount"), "risk_amount", minimum=0)
            stop_pips = v.number(body.get("stop_pips"), "stop_pips", minimum=1e-9)

            info = engine.get_symbol_info(name)
            derived = info.get("_derived", {})
            pip_value = derived.get("pip_value_per_lot")
            if not pip_value:
                raise BadRequest(
                    f"'{name}' has no published pip value, so risk cannot be "
                    f"converted to lots. Use POST /calc/profit with a known pip "
                    f"distance instead."
                )

            raw = risk / (stop_pips * pip_value)
            step = derived.get("lot_info", {}).get("lot_step") or 0.01
            minimum = derived.get("lot_info", {}).get("min_lot") or 0.01
            maximum = derived.get("lot_info", {}).get("max_lot") or raw

            # Round down to the lot step so sizing never exceeds the stated
            # risk. The epsilon absorbs binary float error, which otherwise
            # loses a whole step on exact values: 0.25 // 0.01 is 24, not 25.
            epsilon = 1e-9
            lots = math.floor(raw / step + epsilon) * step
            clamped = max(minimum, min(lots, maximum))
            actual_risk = clamped * stop_pips * pip_value

            return {
                "symbol": name,
                "risk_amount": risk,
                "stop_pips": stop_pips,
                "pip_value_per_lot": pip_value,
                "raw_lots": round(raw, 8),
                "lots": round(clamped, 8),
                "lot_step": step,
                "rounded": round(clamped, 8) != round(raw, 8),
                "actual_risk": round(actual_risk, 2),
                "within_limits": minimum <= clamped <= maximum,
            }

        # ─── History ───────────────────────────────────────────────────

        def _history_window(query):
            """
            Resolve a from/to pair for history, bounded.

            Deals and orders accumulate without limit, so a wide window turns
            into a very large response. The span is capped and reported back
            rather than silently truncated.
            """
            start, end = v.date_range(query.get("from"), query.get("to"))
            if end - start > timedelta(days=HISTORY_MAX_DAYS):
                start = end - timedelta(days=HISTORY_MAX_DAYS)
            return start, end

        @r.get("/history/deals")
        def history_deals(params, query, body):
            start, end = _history_window(query)
            found = engine.get_history_deals(
                start, end, symbol=v.optional_symbol(query.get("symbol"))
            )
            payload = {"count": len(found), "from": start.isoformat(),
                       "to": end.isoformat(), "deals": found}
            if len(found) >= HISTORY_MAX_ROWS:
                payload["truncated"] = True
                payload["note"] = (
                    f"Result capped at {HISTORY_MAX_ROWS} deals. "
                    f"Narrow the from/to window for detail."
                )
            return payload

        @r.get("/history/orders")
        def history_orders(params, query, body):
            start, end = _history_window(query)
            found = engine.get_history_orders(
                start, end, symbol=v.optional_symbol(query.get("symbol"))
            )
            payload = {"count": len(found), "from": start.isoformat(),
                       "to": end.isoformat(), "orders": found}
            if len(found) >= HISTORY_MAX_ROWS:
                payload["truncated"] = True
                payload["note"] = (
                    f"Result capped at {HISTORY_MAX_ROWS} orders. "
                    f"Narrow the from/to window for detail."
                )
            return payload

        @r.get("/history/totals")
        def history_totals(params, query, body):
            """Counts before fetching, so a wide window is not a surprise cost."""
            start, end = _history_window(query)
            return {
                "from": start.isoformat(),
                "to": end.isoformat(),
                "deals": engine.history_deals_total(start, end),
                "orders": engine.history_orders_total(start, end),
            }

        @r.get("/history/summary")
        def history_summary(params, query, body):
            """Realised PnL over a window, split by direction."""
            start, end = _history_window(query)
            deals = engine.get_history_deals(
                start, end, symbol=v.optional_symbol(query.get("symbol"))
            )
            realized = 0.0
            commission = 0.0
            swaps = 0.0
            by_side = {"buy": 0.0, "sell": 0.0}
            for deal in deals:
                profit = deal.get("profit", 0.0)
                realized += profit
                commission += deal.get("commission", 0.0)
                swaps += deal.get("swap", 0.0)
                side = deal.get("_type")
                if side in by_side:
                    by_side[side] += profit
            return {
                "from": start.isoformat(),
                "to": end.isoformat(),
                "deal_count": len(deals),
                "realized_profit": round(realized, 2),
                "commission": round(commission, 2),
                "swap": round(swaps, 2),
                "net": round(realized + swaps, 2),
                "by_side": {k: round(x, 2) for k, x in by_side.items()},
            }

        # ─── Market book (level 2) ─────────────────────────────────────
        # Literal paths are registered before the {symbol} patterns so that
        # /marketbook/subscribed is not captured as a symbol named
        # "subscribed" by the /marketbook/{symbol} route.

        @r.get("/marketbook/subscribed")
        def book_subscribed(params, query, body):
            return {"subscribed": engine.market_book.subscribed}

        # ─── Research (optional extension) ─────────────────────────────
        # Registers the strategy/pattern/backtest surface when the
        # knowledgebase is importable alongside the gateway. Absent in a
        # standalone deployment, which stays a pure MetaTrader 5 gateway.
        try:
            from server import research as _research_routes

            added = _research_routes.register(r, engine, base=self.base)
            if added:
                logger.info("research API enabled: %d routes under /research", added)
            else:
                # Report the underlying import error rather than leaving the
                # caller to infer it from unexplained 404s later.
                logger.warning(
                    "research API unavailable (%s) - the knowledgebase is not "
                    "importable from this gateway; market data endpoints are "
                    "unaffected.",
                    _research_routes.load_error() or "no routes registered")
        except Exception:                              # noqa: BLE001
            # The stack, not just the message: an extension that fails to
            # load is otherwise indistinguishable from one that was never
            # installed. Formatted before the log call so no newline escapes
            # into the message prefix.
            logger.warning("research API failed to load. Traceback follows.")
            logger.warning("%s", traceback.format_exc())

        # ─── Database & Bot APIs (modular extensions) ─────────────────
        try:
            from server import db_routes as _db_routes
            n_db = _db_routes.register(r)
            if n_db:
                logger.info("database API enabled: %d routes under /db", n_db)
        except Exception:                              # noqa: BLE001
            logger.debug("database API not registered: %s", traceback.format_exc())

        try:
            from server import bot_routes as _bot_routes
            n_bot = _bot_routes.register(r, engine=engine)
            if n_bot:
                logger.info("bot API enabled: %d routes under /bot", n_bot)
        except Exception:                              # noqa: BLE001
            logger.debug("bot API not registered: %s", traceback.format_exc())

        # ─── Dashboard (optional extension) ─────────────────────────────
        # The web control panel at GET /. Same contract as the research API:
        # absent means the dashboard could not load, and the reason is logged.
        # Named `dashboard`, not `site` - `site` is a stdlib module frozen
        # into the interpreter and already in sys.modules at startup, so a
        # package called `site` is unreachable however the path is arranged.
        # The expected location is named up front so a failure says where the
        # frontend should be, not merely that something would not import.
        _workspace_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _frontend_hint = os.environ.get("CONY_FRONTEND_DIR") or os.path.join(_workspace_root, "frontend")
        try:
            from dashboard import register as _dashboard_routes

            added = _dashboard_routes(r, engine)
            if added:
                from dashboard import assets as _assets
                logger.info("dashboard enabled: / and /ui/{page} from %s "
                            "(pages: %s)", _assets.FRONTEND_DIR,
                            ", ".join(_assets.available_pages()) or "none")
            else:
                logger.warning(
                    "dashboard unavailable - no pages found under %s. Set "
                    "CONY_FRONTEND_DIR to point elsewhere.", _frontend_hint)
        except Exception:                              # noqa: BLE001
            logger.warning("dashboard failed to load (frontend expected at %s). "
                           "Traceback follows.", _frontend_hint)
            logger.warning("%s", traceback.format_exc())

        @r.get("/marketbook")
        def marketbooks(params, query, body):
            names = v.symbol_list(query.get("symbols"))
            if not names:
                raise BadRequest("'symbols' is required, e.g. ?symbols=EURUSD,GBPUSD")
            return {"books": engine.market_book.get_many(names)}

        @r.get("/marketbook/{symbol}")
        def marketbook(params, query, body):
            """Depth of market for one symbol. Subscribes on first read."""
            return engine.market_book.get(v.symbol(params["symbol"]))

        @r.post("/marketbook/{symbol}/subscribe")
        def book_subscribe(params, query, body):
            name = v.symbol(params["symbol"])
            added = engine.market_book.subscribe(name)
            return {"success": True, "symbol": name,
                    "subscribed": engine.market_book.subscribed,
                    "newly_added": added}

        @r.post("/marketbook/{symbol}/unsubscribe")
        def book_unsubscribe(params, query, body):
            name = v.symbol(params["symbol"])
            released = engine.market_book.unsubscribe(name)
            return {"success": True, "symbol": name,
                    "subscribed": engine.market_book.subscribed,
                    "released": released}
