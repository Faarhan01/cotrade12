"""cony — Serializers
===================
Convert MT5 namedtuples, numpy arrays, and native types to JSON-serializable dicts.
Gracefully handles environments where numpy is not installed, preserving maximum flexibility.
"""
from typing import Any
import datetime

try:
    import numpy as np
except ImportError:
    np = None


def serialize_namedtuple(obj) -> dict:
    """Convert an MT5 namedtuple (or any object with _asdict()) to a plain dict."""
    if obj is None:
        return None
    if hasattr(obj, "_asdict"):
        d = obj._asdict()
    elif isinstance(obj, dict):
        d = obj
    else:
        return obj
    return _deep_serialize(d)


def serialize_array(arr) -> list:
    """Convert an array (from copy_rates, etc.) to a list of dicts."""
    if arr is None:
        return []
    if len(arr) == 0:
        return []

    # Check for numpy structured array
    if hasattr(arr, "dtype") and hasattr(arr.dtype, "names") and arr.dtype.names:
        names = arr.dtype.names
        result = []
        for row in arr:
            d = {}
            for name in names:
                val = row[name]
                d[name] = _serialize_value(val)
            result.append(d)
        return result

    if hasattr(arr, "tolist"):
        return _deep_serialize(arr.tolist())

    if isinstance(arr, (list, tuple)):
        return _deep_serialize(list(arr))

    return [arr]


def _deep_serialize(obj: Any) -> Any:
    """Recursively serialize all values in a dict/list structure."""
    if isinstance(obj, dict):
        return {k: _serialize_value(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_serialize_value(v) for v in obj]
    else:
        return _serialize_value(obj)


def _serialize_value(val: Any) -> Any:
    """Serialize a single value: numpy types, datetime, bytes, etc."""
    if val is None:
        return None

    # If numpy is available, use exact numpy type checks
    if np is not None:
        if isinstance(val, np.integer):
            return int(val)
        if isinstance(val, np.floating):
            return float(val)
        if isinstance(val, np.bool_):
            return bool(val)
        if isinstance(val, np.ndarray):
            return val.tolist()
    else:
        # Fallback type detection without numpy
        type_name = type(val).__name__
        if "int" in type_name and hasattr(val, "item"):
            return int(val.item())
        if "float" in type_name and hasattr(val, "item"):
            return float(val.item())
        if "bool" in type_name and hasattr(val, "item"):
            return bool(val.item())
        if hasattr(val, "tolist"):
            return val.tolist()

    if isinstance(val, bytes):
        try:
            return val.decode("utf-8")
        except UnicodeDecodeError:
            return val.hex()

    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()

    if isinstance(val, datetime.timedelta):
        return val.total_seconds()

    if hasattr(val, "_asdict"):
        return _deep_serialize(val._asdict())

    if not isinstance(val, (str, int, float, bool, dict, list)):
        return str(val)

    return val
