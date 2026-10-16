"""
cony — Serializers
===================
Convert MT5 namedtuples, numpy arrays, and native types to JSON-serializable dicts.
"""

from typing import Any
import datetime
import numpy as np


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
    """Convert a numpy array (from copy_rates, etc.) to a list of dicts."""
    if arr is None:
        return []
    if len(arr) == 0:
        return []
    if hasattr(arr.dtype, "names") and arr.dtype.names:
        names = arr.dtype.names
    else:
        return arr.tolist()
    result = []
    for row in arr:
        d = {}
        for name in names:
            val = row[name]
            d[name] = _serialize_value(val)
        result.append(d)
    return result


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
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, np.ndarray):
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
