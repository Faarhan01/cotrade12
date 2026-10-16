"""
cony — MT5 Engine
=================
High-level wrapper over the MetaTrader5 package.

Every public function the package exposes is reachable from here, so a caller
never has to drop down to the raw module. The engine holds no HTTP concepts
and no configuration of its own beyond the connection manager it is given.
"""

from datetime import datetime
import threading
import time
from typing import List, Optional

from cony import enums
from cony.connection import ConnectionManager
from cony.marketbook import MarketBook
from cony.serializers import serialize_array, serialize_namedtuple


class MT5Error(Exception):
    """Base exception for engine errors."""


class MT5ConnectionError(MT5Error):
    """The terminal is not connected."""


class SymbolNotFoundError(MT5Error):
    """The broker does not expose that symbol."""


class NotFoundError(MT5Error):
    """A position or order ticket does not exist."""


class InvalidRequestError(MT5Error):
    """The terminal rejected the request before it reached the broker."""


class OrderRejectedError(MT5Error):
    """The broker or terminal refused the order."""

    def __init__(self, message: str, retcode: int = 0, result: Optional[dict] = None):
        super().__init__(message)
        self.retcode = retcode
        self.result = result or {}


class MT5Engine:
    """All MetaTrader 5 operations, one method per package capability."""

    def __init__(
        self,
        connection_manager: ConnectionManager,
        symbol_cache_ttl: int = 300,
    ):
        self._conn = connection_manager
        self._book = MarketBook(self)

        # Cache of UPPERCASE -> broker spelling, so a name given in the wrong
        # case resolves without asking the terminal for all 731 symbols with
        # their full specs. That call measures ~236 ms against ~0.04 ms for the
        # lookup, which made every typo cost 12x a valid request.
        self._name_cache: dict = {}
        self._name_cache_at: float = 0.0
        self._name_lock = threading.Lock()
        self._name_ttl = symbol_cache_ttl

    # ─── Plumbing ───────────────────────────────────────────────────────

    @property
    def mt5(self):
        """The raw MetaTrader5 module. None until connected."""
        return self._conn.mt5

    @property
    def is_connected(self) -> bool:
        return self._conn.is_connected

    @property
    def market_book(self) -> MarketBook:
        return self._book

    def ensure_connected(self):
        self._conn.ensure_connected()

    def package_version(self) -> Optional[str]:
        """Version of the loaded MetaTrader5 package."""
        module = enums.load()
        return getattr(module, "__version__", None) if module else None

    def clock_offset(self) -> Optional[float]:
        """
        Seconds between broker server time and this machine's UTC clock.

        Every timestamp MT5 returns is broker server time, which need not match
        local or UTC - this account ran ~30s ahead. Without this a consumer
        comparing a tick's `time` against its own clock sees data from the
        future and cannot tell whether a stream has stalled. Returns None when
        no tick is available to compare against.
        """
        self.ensure_connected()
        for name in self.mt5.symbols_get() or ():
            if name.select:
                tick = self.mt5.symbol_info_tick(name.name)
                if tick is not None and tick.time:
                    return round(tick.time - time.time(), 3)
        return None

    def last_error(self) -> dict:
        """Most recent terminal error code and description."""
        self.ensure_connected()
        code = self.mt5.last_error()
        return {"code": code, "description": enums.retcode_name(code)}

    def login(
        self,
        login: int,
        password: str,
        server: Optional[str] = None,
    ) -> dict:
        """
        Authenticate a specific account, switching away from the terminal's
        current session. Separate from initialize, which just attaches to
        whatever account the terminal is already logged into.
        """
        self.ensure_connected()
        args = {"login": login, "password": password}
        if server:
            args["server"] = server
        result = self.mt5.login(**args)
        if not result:
            err = self.mt5.last_error()
            raise MT5ConnectionError(f"login() failed: {err}")
        info = self.mt5.account_info()
        return {"login": info.login if info else None, "server": info.server if info else None}

    # ─── Account and terminal ───────────────────────────────────────────

    def get_account_info(self) -> dict:
        self.ensure_connected()
        info = self.mt5.account_info()
        if info is None:
            raise MT5Error(f"account_info() failed: {self.mt5.last_error()}")
        result = serialize_namedtuple(info)
        # Replace raw enum integers with names so a reader knows what they mean.
        result["_trade_mode"] = enums.TRADE_MODE_NAMES.get(result.get("trade_mode"))
        result["_margin_mode"] = enums.MARGIN_MODE_NAMES.get(result.get("margin_mode"))
        return result

    def get_terminal_info(self) -> dict:
        self.ensure_connected()
        info = self.mt5.terminal_info()
        if info is None:
            raise MT5Error(f"terminal_info() failed: {self.mt5.last_error()}")
        return serialize_namedtuple(info)

    # ─── Counters ───────────────────────────────────────────────────────
    # Cheap checks before fetching lists that could be large.

    def symbols_total(self) -> int:
        self.ensure_connected()
        return self.mt5.symbols_total()

    def positions_total(self, symbol: Optional[str] = None) -> int:
        self.ensure_connected()
        return self.mt5.positions_total(symbol) if symbol else self.mt5.positions_total()

    def orders_total(self, symbol: Optional[str] = None) -> int:
        self.ensure_connected()
        return self.mt5.orders_total(symbol) if symbol else self.mt5.orders_total()

    def get_totals(self) -> dict:
        """Every counter in one call, so a caller can size the work ahead."""
        self.ensure_connected()
        return {
            "symbols": self.mt5.symbols_total(),
            "positions": self.mt5.positions_total(),
            "orders": self.mt5.orders_total(),
        }

    def history_deals_total(self, date_from: datetime, date_to: datetime) -> int:
        self.ensure_connected()
        return self.mt5.history_deals_total(date_from, date_to)

    def history_orders_total(self, date_from: datetime, date_to: datetime) -> int:
        self.ensure_connected()
        return self.mt5.history_orders_total(date_from, date_to)

    # ─── Symbols ────────────────────────────────────────────────────────

    def invalidate_symbol_cache(self):
        """Drop the cached name map, e.g. after reconnecting to another account."""
        with self._name_lock:
            self._name_cache = {}
            self._name_cache_at = 0.0

    def symbol_cache_info(self) -> dict:
        """Cache state, for observability."""
        with self._name_lock:
            age = time.monotonic() - self._name_cache_at if self._name_cache_at else None
            return {
                "entries": len(self._name_cache),
                "ttl_seconds": self._name_ttl,
                "age_seconds": round(age, 1) if age is not None else None,
                "valid": bool(self._name_cache)
                and (time.monotonic() - self._name_cache_at) < self._name_ttl,
            }

    def _symbol_name_map(self) -> dict:
        """
        UPPERCASE -> broker spelling, rebuilt at most once per TTL.

        Double-checked so that concurrent misses do not each pay the terminal
        round trip; the rebuild happens under the lock, the read does not.
        """
        if self._name_cache and (time.monotonic() - self._name_cache_at) < self._name_ttl:
            return self._name_cache

        with self._name_lock:
            if self._name_cache and (time.monotonic() - self._name_cache_at) < self._name_ttl:
                return self._name_cache
            everything = self.mt5.symbols_get() or ()
            self._name_cache = {s.name.upper(): s.name for s in everything}
            self._name_cache_at = time.monotonic()
            return self._name_cache

    def resolve_symbol(self, symbol: str) -> str:
        """
        Return the symbol spelled exactly as the broker spells it.

        MT5 names are case-sensitive and mixed ("Step Index 200", not
        "STEP INDEX 200"), so a mistyped name cannot be repaired by changing
        case. An exact hit is used as-is; otherwise the cached name map is
        consulted and the broker's canonical spelling returned. That keeps
        "eurusd" working without ever inventing a name the terminal rejects.

        A miss does not force a rebuild - doing so would make every typo pay
        the full scan again, which is the case the cache exists to avoid.
        Freshness is bounded by the TTL, and POST /symbol-cache/clear forces
        an immediate rebuild for anyone who cannot wait.
        """
        self.ensure_connected()

        if self.mt5.symbol_info(symbol) is not None:
            return symbol

        found = self._symbol_name_map().get(symbol.strip().upper())
        if found:
            return found

        raise SymbolNotFoundError(f"Symbol '{symbol}' not found")

    def get_symbols(self, group: Optional[str] = None) -> List[dict]:
        """
        All symbols the broker exposes.

        group filters by substring, e.g. "*EUR*" using the broker's own
        wildcard syntax.
        """
        self.ensure_connected()
        symbols = self.mt5.symbols_get(group) if group else self.mt5.symbols_get()
        if symbols is None:
            raise MT5Error(f"symbols_get() failed: {self.mt5.last_error()}")
        result = [serialize_namedtuple(s) for s in symbols]
        for entry in result:
            entry["_trade_mode"] = enums.SYMBOL_TRADE_MODE_NAMES.get(entry.get("trade_mode"))
        return result

    def get_symbol_info(self, symbol: str) -> dict:
        """
        Everything about one symbol, plus a _derived block giving an agent the
        pip size, lot rules, spread, margin and money-per-pip it needs to
        reason about the instrument and size a position.
        """
        info = self.mt5.symbol_info(self.resolve_symbol(symbol))
        if info is None:
            raise SymbolNotFoundError(f"Symbol '{symbol}' not found")
        result = serialize_namedtuple(info)
        result["_derived"] = self._derive_symbol_fields(info)
        result["_trade_mode"] = enums.SYMBOL_TRADE_MODE_NAMES.get(result.get("trade_mode"))
        return result

    def _derive_symbol_fields(self, info) -> dict:
        """
        Fields a caller would otherwise have to derive from MT5 internals.

        A point is the smallest quoted increment. A pip is ten points, so one
        decimal place further left: EURUSD at 5 digits gives 0.0001, USDJPY at
        3 digits gives 0.01. The broker's own `point` field is preferred over
        computing it from `digits`, since that is what it actually trades on.

        Every read goes through _get, because the exact field set on SymbolInfo
        varies with package version and a missing field should degrade the
        response rather than raise a 500.
        """
        def _get(name, default=None):
            return getattr(info, name, default)

        digits = _get("digits", 0)
        point = _get("point") or (10.0 ** -digits)
        pip_size = point * 10.0
        points_per_pip = 10

        # Min/max lot are expressed in lots; the *_low/_high pair is in units.
        min_lot = _get("volume_min", 0.0)
        max_lot = _get("volume_max", 0.0)
        step = _get("volume_step", 0.01)
        contract = _get("trade_contract_size", 0.0)

        derived = {
            "digits": digits,
            "point_size": point,
            "pip_size": pip_size,
            "pip_decimals": max(digits - 1, 0),
            "points_per_pip": points_per_pip,
            "pip_description": (
                f"1 point = {point:g}; 1 pip = {pip_size:g} "
                f"({points_per_pip:g} points)"
            ),
            "rounding": (
                f"Quote prices to {digits} decimal places. "
                f"Measure stops in pips of {pip_size:g}."
            ),
            "lot_info": {
                "min_lot": min_lot,
                "max_lot": max_lot,
                "lot_step": step,
                "contract_size": contract,
                "current_volume": _get("volume"),
                "limit_per_direction": _get("volume_limit"),
            },
            "margin": {
                "initial": _get("margin_initial"),
                "maintenance": _get("margin_maintenance"),
                "hedged": _get("margin_hedged"),
                "calc_mode": _get("trade_calc_mode"),
                "currency": _get("currency_margin"),
            },
            "trade_mode": enums.SYMBOL_TRADE_MODE_NAMES.get(
                _get("trade_mode"), "UNKNOWN"
            ),
            "spread": {
                "current_points": _get("spread"),
                "is_floating": bool(_get("spread_float")),
                "bid": _get("bid"),
                "ask": _get("ask"),
                "session_high": _get("bidhigh"),
                "session_low": _get("bidlow"),
            },
            "swap": {
                "long": _get("swap_long"),
                "short": _get("swap_short"),
                "mode": _get("swap_mode"),
                "rollover_day": _get("swap_rollover3days"),
            },
            "currencies": {
                "base": _get("currency_base"),
                "profit": _get("currency_profit"),
                "margin": _get("currency_margin"),
            },
            # Limits an order has to respect. Placing a stop inside
            # trade_stops_level is rejected with retcode 10016, so this is
            # the difference between a valid order and a guaranteed failure.
            "order_rules": {
                "min_stop_distance_points": _get("trade_stops_level", 0),
                "freeze_distance_points": _get("trade_freeze_level", 0),
                "min_stop_distance_pips": round(
                    (_get("trade_stops_level", 0) or 0) / points_per_pip, 2
                ),
                "expiration_mode": _get("expiration_mode"),
                "session_deals": _get("session_deals"),
                "session_buy_orders": _get("session_buy_orders"),
                "session_sell_orders": _get("session_sell_orders"),
                "note": (
                    "Stops must sit at least min_stop_distance_pips from the "
                    "current price, or the terminal rejects the order."
                ),
            },
            # Broker-declared filling modes, as a bitfield. An unsupported
            # type_filling is rejected with retcode 10030, and brokers differ
            # on which they allow, so this is what stops a caller guessing.
            "filling": {
                "supported": enums.supported_filling_modes(_get("filling_mode")),
                "flag": _get("filling_mode"),
                "note": (
                    "Leave type_filling unset and the gateway picks one of "
                    "these. Sending an unsupported mode is rejected with "
                    "retcode 10030."
                ),
            },
            "session": {
                "deals": _get("session_deals"),
                "buy_orders": _get("session_buy_orders"),
                "sell_orders": _get("session_sell_orders"),
                "volume": _get("session_volume"),
                "turnover": _get("session_turnover"),
                "open": _get("session_open"),
                "close": _get("session_close"),
                "settlement": _get("session_price_settlement"),
            },
            "market_book": {
                "book_depth": _get("ticks_bookdepth", 0),
                "available": bool(_get("ticks_bookdepth", 0)),
                "note": (
                    "Depth of market requires a book_depth above zero; "
                    "brokers often restrict this to exchange-traded symbols."
                ),
            },
        }

        # Money per pip is what turns a stop distance into a risk figure.
        tick_size = _get("trade_tick_size") or point
        tick_value = _get("trade_tick_value")
        if tick_value and tick_size:
            per_lot = tick_value * (pip_size / tick_size)
            derived["tick_value"] = tick_value
            derived["tick_size"] = tick_size
            currency = _get("currency_profit") or ""
            derived["pip_value_per_lot"] = round(per_lot, 8)
            derived["value_note"] = (
                f"1 standard lot moves {per_lot:g} {currency} per pip. "
                f"Risk on a stop d pips away with n lots is d * n * {per_lot:g}."
            )
            derived["sizing_formula"] = (
                "lots = risk_amount / (stop_distance_in_pips * pip_value_per_lot)"
            )
        else:
            derived["tick_value"] = None
            derived["pip_value_per_lot"] = None
            derived["value_note"] = (
                "Broker published no tick value; measure it with POST /calc/profit "
                "using a known pip distance."
            )
        return derived

    def select_symbol(self, symbol: str, enable: bool = True) -> bool:
        """Add or remove a symbol from MarketWatch so its tick keeps flowing."""
        self.ensure_connected()
        name = self.resolve_symbol(symbol) if enable else symbol
        if not self.mt5.symbol_select(name, enable):
            raise MT5Error(f"symbol_select('{name}') failed: {self.mt5.last_error()}")
        return True

    def _ready_symbol(self, symbol: str) -> str:
        """
        Resolve a name and make sure it is in MarketWatch.

        The terminal only serves ticks and candles for symbols it is watching;
        anything else returns -1 or -4 rather than data. Reads select first so
        asking about a symbol the user never added still works.
        """
        name = self.resolve_symbol(symbol)
        self.mt5.symbol_select(name, True)
        return name

    # ─── Ticks ──────────────────────────────────────────────────────────

    def _fail(self, operation: str, symbol: str, error):
        """
        Raise the right error for a failed MT5 read.

        An unknown name surfaces as -1 "Invalid symbol" from most calls but as
        -4 "Not found" from others, so both map to SymbolNotFoundError.
        Without this an unknown symbol returned HTTP 500 and read as a server
        fault rather than a bad request.
        """
        code = error[0] if isinstance(error, tuple) else error
        text = str(error)
        if code in (-1, -2, -4) or "invalid symbol" in text.lower():
            raise SymbolNotFoundError(f"'{symbol}' is not available: {error}")
        raise MT5Error(f"{operation}('{symbol}') failed: {error}")

    def get_tick(self, symbol: str) -> dict:
        self.ensure_connected()
        name = self._ready_symbol(symbol)
        tick = self.mt5.symbol_info_tick(name)
        if tick is None:
            self._fail("symbol_info_tick", symbol, self.mt5.last_error())
        return serialize_namedtuple(tick)

    def get_all_ticks(self, symbols: Optional[List[str]] = None) -> dict:
        """Ticks for the named symbols, or every MarketWatch entry."""
        self.ensure_connected()
        if symbols is None:
            watched = self.mt5.symbols_get()
            if watched is None:
                return {}
            symbols = [s.name for s in watched if s.select]

        result = {}
        for name in symbols:
            try:
                result[name] = self.get_tick(name)
            except MT5Error:
                result[name] = None
        return result

    def copy_ticks_from(
        self,
        symbol: str,
        date_from: datetime,
        count: int,
        flags: Optional[int] = None,
    ) -> List[dict]:
        """
        `count` ticks counting forward from date_from.

        flags selects which fields come back: COPY_TICKS_INFO (bid/ask only),
        COPY_TICKS_TRADE (last/volume, needs permission) or COPY_TICKS_ALL.
        """
        self.ensure_connected()
        name = self._ready_symbol(symbol)
        if flags is None:
            flags = enums.COPY_TICKS_FLAGS["all"]
        ticks = self.mt5.copy_ticks_from(name, date_from, count, flags)
        if ticks is None:
            self._fail("copy_ticks_from", name, self.mt5.last_error())
        return serialize_array(ticks)

    def copy_ticks_range(
        self,
        symbol: str,
        date_from: datetime,
        date_to: datetime,
        flags: Optional[int] = None,
    ) -> List[dict]:
        """Every tick between two instants."""
        self.ensure_connected()
        name = self._ready_symbol(symbol)
        if flags is None:
            flags = enums.COPY_TICKS_FLAGS["all"]
        ticks = self.mt5.copy_ticks_range(name, date_from, date_to, flags)
        if ticks is None:
            self._fail("copy_ticks_range", name, self.mt5.last_error())
        return serialize_array(ticks)

    # ─── Candles ────────────────────────────────────────────────────────

    def copy_rates(
        self,
        symbol: str,
        timeframe: int,
        count: int,
        date_from: Optional[datetime] = None,
    ) -> List[dict]:
        """`count` bars counting forward from date_from (default: now)."""
        self.ensure_connected()
        name = self._ready_symbol(symbol)
        rates = (
            self.mt5.copy_rates_from(name, timeframe, datetime.now(), count)
            if date_from is None
            else self.mt5.copy_rates_from(name, timeframe, date_from, count)
        )
        if rates is None:
            self._fail("copy_rates_from", name, self.mt5.last_error())
        return serialize_array(rates)

    def copy_rates_from_pos(
        self,
        symbol: str,
        timeframe: int,
        start: int,
        count: int,
    ) -> List[dict]:
        """`count` bars starting at bar offset `start`, where 0 is the current bar."""
        self.ensure_connected()
        name = self._ready_symbol(symbol)
        rates = self.mt5.copy_rates_from_pos(name, timeframe, start, count)
        if rates is None:
            self._fail("copy_rates_from_pos", name, self.mt5.last_error())
        return serialize_array(rates)

    def copy_rates_range(
        self,
        symbol: str,
        timeframe: int,
        date_from: datetime,
        date_to: datetime,
    ) -> List[dict]:
        """Every bar between two instants - the form to use for backtests."""
        self.ensure_connected()
        name = self._ready_symbol(symbol)
        rates = self.mt5.copy_rates_range(name, timeframe, date_from, date_to)
        if rates is None:
            self._fail("copy_rates_range", name, self.mt5.last_error())
        return serialize_array(rates)

    # ─── Positions and orders ───────────────────────────────────────────

    def get_positions(self, symbol: Optional[str] = None, ticket: Optional[int] = None) -> List[dict]:
        self.ensure_connected()
        if symbol:
            found = self.mt5.positions_get(symbol=symbol)
        elif ticket:
            found = self.mt5.positions_get(ticket=ticket)
        else:
            found = self.mt5.positions_get()
        if found is None:
            return []
        result = [serialize_namedtuple(p) for p in found]
        for entry in result:
            entry["_type"] = enums.POSITION_TYPE_NAMES.get(entry.get("type"))
        return result

    def get_position(self, ticket: int) -> dict:
        found = self.get_positions(ticket=ticket)
        if not found:
            raise NotFoundError(f"Position #{ticket} not found")
        return found[0]

    def get_orders(self, symbol: Optional[str] = None, ticket: Optional[int] = None) -> List[dict]:
        self.ensure_connected()
        if symbol:
            found = self.mt5.orders_get(symbol=symbol)
        elif ticket:
            found = self.mt5.orders_get(ticket=ticket)
        else:
            found = self.mt5.orders_get()
        if found is None:
            return []
        result = [serialize_namedtuple(o) for o in found]
        for entry in result:
            entry["_type"] = enums.ORDER_TYPE_NAMES.get(entry.get("type"))
            entry["_state"] = enums.ORDER_STATE_NAMES.get(entry.get("state"))
        return result

    # ─── Trading ────────────────────────────────────────────────────────

    def check_order(self, request: dict) -> dict:
        """
        Dry run. Returns what the terminal would do with the request and the
        margin it would reserve, without sending anything. Always run this
        before a live order.
        """
        self.ensure_connected()
        result = self.mt5.order_check(request)
        if result is None:
            raise MT5Error(f"order_check() failed: {self.mt5.last_error()}")
        response = serialize_namedtuple(result)
        response["_retcode"] = response.get("retcode")
        response["_retcode_description"] = enums.retcode_name(response.get("retcode", 0))
        return response

    def _accepted_retcodes(self) -> tuple:
        return enums.accepted_retcodes()

    def _send_request(self, request: dict, operation: str) -> dict:
        """
        Send an order request and confirm the terminal accepted it.

        order_send returns a result object carrying a retcode rather than
        raising when the terminal refuses a request, so every sending path has
        to inspect it. Without this a cancel against a stale ticket would
        report success with retcode 10013 and the caller would never know.
        """
        result = self.mt5.order_send(request)
        if result is None:
            raise MT5Error(f"{operation}: order_send() failed: {self.mt5.last_error()}")

        response = serialize_namedtuple(result)
        retcode = result.retcode
        accepted = retcode in self._accepted_retcodes()
        response["_success"] = accepted
        response["_retcode"] = retcode
        response["_retcode_description"] = enums.retcode_name(retcode)

        # order_send echoes back the request it actually processed. Lifting the
        # fields an agent cares about to the top level means it can confirm the
        # symbol, fills and stops it intended, rather than re-reading the
        # position afterwards.
        resolved = response.get("request") or {}
        if isinstance(resolved, dict):
            for field in ("symbol", "volume", "type", "price", "sl", "tp",
                          "deviation", "magic", "comment", "type_time",
                          "position", "order"):
                if resolved.get(field) not in (None, "", False):
                    response.setdefault(field, resolved[field])
            # type_filling is kept even when 0, since ORDER_FILLING_FOK is a
            # real mode rather than an absent value.
            if "type_filling" in resolved:
                response.setdefault("type_filling", resolved["type_filling"])
            response["_resolved_request"] = resolved

        if not accepted:
            raise OrderRejectedError(
                f"{operation} rejected: {enums.retcode_name(retcode)} (code {retcode})",
                retcode=retcode,
                result=response,
            )
        return response

    def execute_order(self, request: dict) -> dict:
        """
        Send an order request.

        The caller supplies MT5's request shape. `symbol`, `volume` and `type`
        are required; `price` is required for pending orders and optional for
        market ones, where the live tick is used.
        """
        self.ensure_connected()
        for field in ("symbol", "volume"):
            if request.get(field) is None:
                raise InvalidRequestError(f"Missing required field: '{field}'")
        if request.get("type") is None:
            raise InvalidRequestError("Missing required field: 'type'")

        # Resolve the broker's own spelling and make sure it is watched, so a
        # correct name in any case and a symbol the user never added both work.
        name = self._ready_symbol(request["symbol"])
        request["symbol"] = name

        # Fill in a market price when the caller did not supply one.
        if request.get("price") in (None, 0) and request["type"] in enums.MARKET_ORDER_TYPES:
            tick = self.get_tick(name)
            request["price"] = (
                tick["ask"] if request["type"] == enums.ORDER_TYPES["buy"] else tick["bid"]
            )

        request.setdefault("action", enums.TRADE_ACTIONS["deal"])
        request.setdefault("deviation", 20)
        request.setdefault("type_time", enums.ORDER_TIMES["gtc"])

        # Honour what the broker declares for this symbol. Sending an
        # unsupported filling mode is refused with retcode 10030, so resolve
        # it from the symbol's own bitfield rather than assuming.
        if request.get("type_filling") is None:
            symbol_info = self.mt5.symbol_info(name)
            flag = getattr(symbol_info, "filling_mode", 0) if symbol_info else 0
            request["type_filling"], supported = enums.choose_filling_mode(flag)
            if supported:
                request["_filling_supported"] = supported

        return self._send_request(request, "Order")

    def close_position(
        self,
        ticket: int,
        volume: Optional[float] = None,
        deviation: int = 20,
        magic: int = 0,
        comment: str = "",
    ) -> dict:
        """
        Close a position, in full or in part.

        A full close names the position so the terminal retires the ticket. A
        partial close deliberately leaves it off, so the opposing deal nets the
        exposure down instead.
        """
        self.ensure_connected()
        pos = self.get_position(ticket)

        order_type = (
            enums.ORDER_TYPES["sell"]
            if pos["type"] == enums.POSITION_TYPES["buy"]
            else enums.ORDER_TYPES["buy"]
        )
        tick = self.get_tick(pos["symbol"])
        price = (
            tick["ask"] if pos["type"] == enums.POSITION_TYPES["buy"] else tick["bid"]
        )

        request = {
            "action": enums.TRADE_ACTIONS["deal"],
            "symbol": pos["symbol"],
            "volume": volume if volume is not None else pos["volume"],
            "type": order_type,
            "price": price,
            "deviation": deviation,
            "magic": magic,
            "comment": comment or f"Close #{ticket}",
            "type_time": enums.ORDER_TIMES["gtc"],
        }
        if volume is None or volume >= pos["volume"]:
            request["position"] = ticket

        return self.execute_order(request)

    def modify_position(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> dict:
        """Change a position's stop loss and/or take profit."""
        self.ensure_connected()
        if sl is None and tp is None:
            raise InvalidRequestError("Provide at least one of 'sl', 'tp'")

        pos = self.get_position(ticket)
        request = {
            "action": enums.TRADE_ACTIONS["sltp"],
            "symbol": pos["symbol"],
            "position": ticket,
            "sl": pos["sl"] if sl is None else sl,
            "tp": pos["tp"] if tp is None else tp,
        }
        return self._send_request(request, "Modify")

    def cancel_order(self, ticket: int) -> dict:
        """Cancel a pending order."""
        self.ensure_connected()
        request = {"action": enums.TRADE_ACTIONS["remove"], "order": ticket}
        return self._send_request(request, "Cancel")

    def close_all(
        self,
        symbol: Optional[str] = None,
        magic: int = 0,
    ) -> List[dict]:
        """
        Close every matching position.

        magic filters by strategy, so one agent can liquidate only its own
        positions and leave other strategies running.
        """
        self.ensure_connected()
        positions = self.get_positions(symbol=symbol)
        results = []
        for pos in positions:
            if magic and pos["magic"] != magic:
                continue
            entry = {"ticket": pos["ticket"], "symbol": pos["symbol"], "volume": pos["volume"]}
            try:
                entry["result"] = self.close_position(pos["ticket"])
                entry["success"] = True
            except MT5Error as exc:
                entry["success"] = False
                entry["error"] = str(exc)
            results.append(entry)
        return results

    # ─── One-shot helpers ───────────────────────────────────────────────
    # Thin wrappers over execute_order/close_position for the common cases,
    # so a caller can act without assembling a request dict.

    def buy(
        self,
        symbol: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "",
        magic: int = 0,
        deviation: int = 20,
    ) -> dict:
        return self.execute_order(
            {
                "action": enums.TRADE_ACTIONS["deal"],
                "symbol": symbol,
                "volume": volume,
                "type": enums.ORDER_TYPES["buy"],
                "sl": sl,
                "tp": tp,
                "comment": comment,
                "magic": magic,
                "deviation": deviation,
            }
        )

    def sell(
        self,
        symbol: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "",
        magic: int = 0,
        deviation: int = 20,
    ) -> dict:
        return self.execute_order(
            {
                "action": enums.TRADE_ACTIONS["deal"],
                "symbol": symbol,
                "volume": volume,
                "type": enums.ORDER_TYPES["sell"],
                "sl": sl,
                "tp": tp,
                "comment": comment,
                "magic": magic,
                "deviation": deviation,
            }
        )

    def close_by_symbol(self, symbol: str, magic: int = 0) -> List[dict]:
        """Close every open position on one symbol."""
        return self.close_all(symbol=symbol, magic=magic)

    # ─── History ────────────────────────────────────────────────────────

    def get_history_deals(
        self,
        date_from: datetime,
        date_to: datetime,
        symbol: Optional[str] = None,
        ticket: Optional[int] = None,
    ) -> List[dict]:
        self.ensure_connected()
        if symbol:
            found = self.mt5.history_deals_get(date_from, date_to, symbol=symbol)
        elif ticket:
            found = self.mt5.history_deals_get(date_from, date_to, ticket=ticket)
        else:
            found = self.mt5.history_deals_get(date_from, date_to)
        if found is None:
            return []
        result = []
        for raw in found:
            entry = serialize_namedtuple(raw)
            # _asdict covers whatever fields this version exposes, so these
            # annotations stay safe even if a field is absent.
            entry["_type"] = enums.DEAL_TYPE_NAMES.get(entry.get("type"))
            entry["_entry"] = enums.DEAL_ENTRY_NAMES.get(entry.get("entry"))
            result.append(entry)
        return result

    def get_history_orders(
        self,
        date_from: datetime,
        date_to: datetime,
        symbol: Optional[str] = None,
        ticket: Optional[int] = None,
    ) -> List[dict]:
        self.ensure_connected()
        if symbol:
            found = self.mt5.history_orders_get(date_from, date_to, symbol=symbol)
        elif ticket:
            found = self.mt5.history_orders_get(date_from, date_to, ticket=ticket)
        else:
            found = self.mt5.history_orders_get(date_from, date_to)
        if found is None:
            return []
        result = [serialize_namedtuple(o) for o in found]
        for entry in result:
            entry["_type"] = enums.ORDER_TYPE_NAMES.get(entry.get("type"))
            entry["_state"] = enums.ORDER_STATE_NAMES.get(entry.get("state"))
        return result

    # ─── Calculators ────────────────────────────────────────────────────

    def calc_margin(
        self,
        symbol: str,
        volume: float,
        order_type: int,
        price: float,
    ) -> Optional[float]:
        """Account currency consumed by holding the position."""
        self.ensure_connected()
        return self.mt5.order_calc_margin(order_type, symbol, volume, price)

    def calc_profit(
        self,
        symbol: str,
        volume: float,
        order_type: int,
        open_price: float,
        close_price: float,
    ) -> Optional[float]:
        """Profit or loss in account currency if the price moved as given."""
        self.ensure_connected()
        return self.mt5.order_calc_profit(order_type, symbol, volume, open_price, close_price)
