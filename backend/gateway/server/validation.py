"""
server — Validation
=====================
Input parsing shared by the handlers.

Kept out of cony so the engine stays usable without HTTP semantics, and out
of the handlers so every endpoint validates the same way. Each helper raises
BadRequest with a message that names the offending field and what was
expected, because the caller is usually an agent acting on the text.
"""

from datetime import datetime, timedelta
from typing import Optional

from server.errors import BadRequest
from cony import enums

MAX_CANDLES = 10000

# A full day of EURUSD ticks is ~150k rows and ~29 MB of JSON, which a single
# careless request will happily ask for. The ceiling is high enough for real
# analysis and low enough that one call cannot stall the daemon.
MAX_TICKS = 50000


# ─── Scalars ──────────────────────────────────────────────────────────


def symbol(value, field: str = "symbol") -> str:
    """
    Validate a symbol name, preserving the broker's own spelling.

    MT5 symbol names are case-sensitive and not uniformly upper case -
    "Step Index 200" is a real symbol while "STEP INDEX 200" is not. The value
    is trimmed but never rewritten. Callers wanting forgiving matching resolve
    against the broker's list instead; see MT5Engine.resolve_symbol.
    """
    if value is None or value == "":
        raise BadRequest(f"'{field}' is required")
    if not isinstance(value, str):
        raise BadRequest(f"'{field}' must be a string, got {type(value).__name__}")
    cleaned = value.strip()
    if not cleaned:
        raise BadRequest(f"'{field}' must not be empty")
    return cleaned


def optional_symbol(value, field: str = "symbol") -> Optional[str]:
    return None if value in (None, "") else symbol(value, field)


def integer(value, field: str, minimum=None, maximum=None, default=None) -> int:
    if value is None or value == "":
        if default is not None:
            return default
        raise BadRequest(f"'{field}' is required")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise BadRequest(f"'{field}' must be an integer, got {value!r}")
    if minimum is not None and result < minimum:
        raise BadRequest(f"'{field}' must be >= {minimum}, got {result}")
    if maximum is not None and result > maximum:
        raise BadRequest(f"'{field}' must be <= {maximum}, got {result}")
    return result


def number(value, field: str, minimum=None, maximum=None, default=None) -> float:
    if value is None or value == "":
        if default is not None:
            return default
        raise BadRequest(f"'{field}' is required")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise BadRequest(f"'{field}' must be a number, got {value!r}")
    if minimum is not None and result < minimum:
        raise BadRequest(f"'{field}' must be >= {minimum}, got {result}")
    if maximum is not None and result > maximum:
        raise BadRequest(f"'{field}' must be <= {maximum}, got {result}")
    return result


def optional_number(value, field: str):
    if value is None or value == "":
        return None
    return number(value, field)


def boolean(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def order_id(value, field: str = "ticket") -> int:
    return integer(value, field, minimum=1)


def magic(value, default: int = 0) -> int:
    return integer(value, "magic", minimum=0, default=default)


def comment(value, limit: int = 31) -> str:
    """Comments are capped by the terminal; warn loudly rather than truncate silently."""
    text = "" if value is None else str(value)
    if len(text) > limit:
        raise BadRequest(
            f"'comment' is {len(text)} characters; the terminal accepts {limit}"
        )
    return text


# ─── Time ─────────────────────────────────────────────────────────────


def when(value, field: str, default=None) -> datetime:
    """Parse an ISO datetime, or fall back to a default."""
    if value is None or value == "":
        if default is not None:
            return default
        raise BadRequest(
            f"'{field}' is required. Use ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS"
        )
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for parser in (datetime.fromisoformat,):
        try:
            return parser(text.replace("Z", "+00:00"))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise BadRequest(
        f"'{field}' is not a recognised date: {value!r}. "
        f"Use ISO format, e.g. 2026-01-31T00:00:00"
    )


def date_range(from_value, to_value, default_days: int = 7):
    """Resolve a from/to pair, checking the order."""
    now = datetime.now()
    start = when(from_value, "from", default=now - timedelta(days=default_days))
    end = when(to_value, "to", default=now)
    if start > end:
        raise BadRequest(f"'from' ({start.isoformat()}) must be before 'to' ({end.isoformat()})")
    return start, end


# ─── Enums ────────────────────────────────────────────────────────────


def _from_map(value, mapping, names, field: str, allow_none: bool = False):
    if value is None or value == "":
        if allow_none:
            return None
        raise BadRequest(
            f"'{field}' is required. Use one of: {', '.join(sorted(mapping))} "
            f"or the MT5 integer."
        )
    if isinstance(value, bool):
        raise BadRequest(f"'{field}' must be a name or integer, got a boolean")
    if isinstance(value, str):
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        if key in mapping:
            return mapping[key]
        if key.lstrip("-").isdigit():
            return int(key)
        raise BadRequest(
            f"Unknown {field} {value!r}. Use one of: {', '.join(sorted(mapping))} "
            f"or the MT5 integer."
        )
    try:
        return int(value)
    except (TypeError, ValueError):
        raise BadRequest(f"'{field}' must be a name or integer, got {value!r}")


def order_type(value, default="buy") -> int:
    if value in (None, ""):
        if default is None:
            raise BadRequest(
                f"'order_type' is required. Use one of: "
                f"{', '.join(sorted(enums.ORDER_TYPES))} or the MT5 integer."
            )
        return enums.ORDER_TYPES[default]
    return _from_map(value, enums.ORDER_TYPES, enums.ORDER_TYPE_NAMES, "order_type")


def trade_action(value, default: str = "deal") -> int:
    if value in (None, ""):
        return enums.TRADE_ACTIONS[default]
    return _from_map(value, enums.TRADE_ACTIONS, enums.TRADE_ACTION_NAMES, "action")


def filling_mode(value, default: str = "return") -> int:
    if value in (None, ""):
        return enums.FILLING_MODES[default]
    return _from_map(value, enums.FILLING_MODES, enums.FILLING_NAMES, "type_filling")


def order_time(value, default: str = "gtc") -> int:
    if value in (None, ""):
        return enums.ORDER_TIMES[default]
    return _from_map(value, enums.ORDER_TIMES, enums.ORDER_TIME_NAMES, "type_time")


def timeframe(value, default="M1") -> int:
    if value is None or value == "":
        return enums.TIMEFRAMES[default]
    if isinstance(value, str):
        key = value.strip().upper()
        if key in enums.TIMEFRAMES:
            return enums.TIMEFRAMES[key]
        if key.lstrip("-").isdigit():
            return int(key)
        raise BadRequest(
            f"Unknown timeframe {value!r}. Use one of: "
            f"{', '.join(sorted(enums.TIMEFRAMES, key=lambda k: enums.TIMEFRAMES[k]))}"
        )
    return integer(value, "timeframe")


def copy_ticks_flag(value, default="all") -> int:
    if value is None or value == "":
        return enums.COPY_TICKS_FLAGS[default]
    return _from_map(value, enums.COPY_TICKS_FLAGS, enums.COPY_TICKS_NAMES, "flags")


def symbol_list(value, field: str = "symbols") -> list:
    """
    Accept a comma-separated string or a JSON list of symbol names.

    Names keep their original spelling; resolution against the broker's list
    happens in the engine.
    """
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [symbol(item, field) for item in value]
    return [symbol(part, field) for part in str(value).split(",") if part.strip()]
