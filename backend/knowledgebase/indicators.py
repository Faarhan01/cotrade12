"""
knowledgebase — Indicators
============================
Pure-Python technical indicators over plain Python lists.

Design rules, because these get reused everywhere:

  * No I/O, no database, no gateway, no numpy. This package is logic only, so
    it can be unit-tested, imported by a notebook, or stored in the database
    without dragging dependencies along.
  * Indicators return a list the same length as the input, with `None` during
    the warm-up window. Returning a short list would silently shift index
    alignment, which is the classic source of "my backtest disagrees with my
    chart" bugs.
  * Inputs are never mutated.

Every function takes `float` bars and returns `Optional[float]` per bar.
"""

from typing import List, Optional, Sequence, Tuple

Number = Optional[float]
Series = List[Number]


def _clean(values: Sequence[float]) -> List[float]:
    return [float(v) for v in values]


def sma(values: Sequence[float], period: int) -> Series:
    """Simple moving average."""
    if period <= 0:
        raise ValueError("period must be positive")
    data = _clean(values)
    out: Series = [None] * len(data)
    if len(data) < period:
        return out
    total = sum(data[:period])
    out[period - 1] = total / period
    for i in range(period, len(data)):
        total += data[i] - data[i - period]
        out[i] = total / period
    return out


def ema(values: Sequence[float], period: int) -> Series:
    """
    Exponential moving average, seeded with an SMA so the first emitted value
    is not distorted by a single bar.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    data = _clean(values)
    out: Series = [None] * len(data)
    if len(data) < period:
        return out
    k = 2.0 / (period + 1.0)
    prev = sum(data[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(data)):
        prev = data[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def wma(values: Sequence[float], period: int) -> Series:
    """Linearly weighted moving average."""
    data = _clean(values)
    out: Series = [None] * len(data)
    if len(data) < period:
        return out
    weights = list(range(1, period + 1))
    denom = sum(weights)
    for i in range(period - 1, len(data)):
        window = data[i - period + 1:i + 1]
        out[i] = sum(w * v for w, v in zip(weights, window)) / denom
    return out


def rsi(values: Sequence[float], period: int = 14) -> Series:
    """Relative Strength Index using Wilder's smoothing."""
    data = _clean(values)
    out: Series = [None] * len(data)
    if len(data) <= period:
        return out

    gain = loss = 0.0
    for i in range(1, period + 1):
        change = data[i] - data[i - 1]
        gain += max(change, 0.0)
        loss += max(-change, 0.0)
    avg_gain, avg_loss = gain / period, loss / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    for i in range(period + 1, len(data)):
        change = data[i] - data[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def true_range(high: Sequence[float], low: Sequence[float],
               close: Sequence[float]) -> Series:
    """Wilder's True Range. First bar falls back to high-low."""
    h, l, c = _clean(high), _clean(low), _clean(close)
    out: Series = [None] * len(c)
    if not c:
        return out
    out[0] = h[0] - l[0]
    for i in range(1, len(c)):
        out[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return out


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float],
        period: int = 14) -> Series:
    """Average True Range, Wilder-smoothed."""
    tr = true_range(high, low, close)
    values = [v for v in tr if v is not None]
    if len(values) < period:
        return [None] * len(tr)
    smoothed = sma(values, period)
    return smoothed


def bollinger(values: Sequence[float], period: int = 20,
              mult: float = 2.0) -> Tuple[Series, Series, Series]:
    """Returns (lower, middle, upper)."""
    data = _clean(values)
    middle = sma(data, period)
    lower: Series = [None] * len(data)
    upper: Series = [None] * len(data)
    for i in range(len(data)):
        if middle[i] is None:
            continue
        window = data[i - period + 1:i + 1]
        mean = middle[i]
        sd = (sum((v - mean) ** 2 for v in window) / period) ** 0.5
        lower[i] = mean - mult * sd
        upper[i] = mean + mult * sd
    return lower, middle, upper


def macd(values: Sequence[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> Tuple[Series, Series, Series]:
    """Returns (macd_line, signal_line, histogram)."""
    data = _clean(values)
    fast_line, slow_line = ema(data, fast), ema(data, slow)
    macd_line: Series = [None] * len(data)
    for i in range(len(data)):
        if fast_line[i] is not None and slow_line[i] is not None:
            macd_line[i] = fast_line[i] - slow_line[i]

    defined = [i for i, v in enumerate(macd_line) if v is not None]
    signal_line: Series = [None] * len(data)
    histogram: Series = [None] * len(data)
    if len(defined) >= signal:
        offset = defined[0]
        raw = [macd_line[i] for i in defined]
        sig = ema(raw, signal)
        for idx, i in enumerate(defined):
            signal_line[i] = sig[idx]
            if sig[idx] is not None:
                histogram[i] = macd_line[i] - sig[idx]
    return macd_line, signal_line, histogram


def stochastic(high: Sequence[float], low: Sequence[float], close: Sequence[float],
               period: int = 14, smooth: int = 3) -> Series:
    """Stochastic %K, optionally smoothed."""
    h, l, c = _clean(high), _clean(low), _clean(close)
    out: Series = [None] * len(c)
    for i in range(period - 1, len(c)):
        hh = max(h[i - period + 1:i + 1])
        ll = min(l[i - period + 1:i + 1])
        if hh == ll:
            out[i] = 50.0
        else:
            out[i] = 100.0 * (c[i] - ll) / (hh - ll)
    if smooth > 1:
        valid = [v for v in out if v is not None]
        if valid:
            smoothed = sma(valid, smooth)
            it = iter(smoothed)
            for i, v in enumerate(out):
                if v is not None:
                    out[i] = next(it)
    return out


def adx(high: Sequence[float], low: Sequence[float], close: Sequence[float],
        period: int = 14) -> Series:
    """Average Directional Index. Uses Wilder smoothing throughout."""
    h, l, c = _clean(high), _clean(low), _clean(close)
    out: Series = [None] * len(c)
    if len(c) < 2 * period + 1:
        return out

    plus_dm: List[float] = [0.0]
    minus_dm: List[float] = [0.0]
    for i in range(1, len(c)):
        up = h[i] - h[i - 1]
        down = l[i - 1] - l[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    def wilder(seq: List[float]) -> List[Number]:
        acc = sum(seq[1:period + 1])
        result: List[Number] = [None] * len(seq)
        result[period] = acc
        for i in range(period + 1, len(seq)):
            acc = acc - acc / period + seq[i]
            result[i] = acc
        return result

    tr = wilder(true_range(h, l, c))
    plus = wilder(plus_dm)
    minus = wilder(minus_dm)

    dx: List[Number] = [None] * len(c)
    for i in range(period, len(c)):
        if not tr[i]:
            continue
        pdi = 100.0 * plus[i] / tr[i]
        mdi = 100.0 * minus[i] / tr[i]
        total = pdi + mdi
        dx[i] = 0.0 if total == 0 else 100.0 * abs(pdi - mdi) / total

    defined = [v for v in dx if v is not None]
    if len(defined) >= period:
        smoothed = sma(defined, period)
        it = iter(smoothed)
        for i, v in enumerate(dx):
            if v is not None:
                out[i] = next(it)
    return out


def donchian(high: Sequence[float], low: Sequence[float],
             period: int = 20) -> Tuple[Series, Series]:
    """Donchian channels. Returns (upper, lower) excluding the current bar,
    which is what makes them usable as a breakout reference rather than a
    level price is already sitting on."""
    h, l = _clean(high), _clean(low)
    upper: Series = [None] * len(h)
    lower: Series = [None] * len(l)
    for i in range(period, len(h)):
        upper[i] = max(h[i - period:i])
        lower[i] = min(l[i - period:i])
    return upper, lower


def slope(values: Series, lookback: int = 5) -> Series:
    """
    Least-squares slope over a trailing window, normalised by price so the
    result is comparable across instruments.
    """
    out: Series = [None] * len(values)
    for i in range(lookback, len(values)):
        window = values[i - lookback + 1:i + 1]
        if any(v is None for v in window):
            continue
        xs = list(range(lookback))
        ys = [float(v) for v in window]
        n = lookback
        mean_x, mean_y = sum(xs) / n, sum(ys) / n
        denom = sum((x - mean_x) ** 2 for x in xs)
        if denom == 0 or mean_y == 0:
            continue
        out[i] = (sum((xs[k] - mean_x) * (ys[k] - mean_y) for k in range(n)) / denom) / abs(mean_y)
    return out


def vwap(high: Sequence[float], low: Sequence[float], close: Sequence[float],
         volume: Sequence[float]) -> Series:
    """Volume-weighted average price (cumulative over the series)."""
    h, l, c, v = _clean(high), _clean(low), _clean(close), _clean(volume)
    n = len(c)
    out: Series = [None] * n
    cum_pv = 0.0
    cum_vol = 0.0
    for i in range(n):
        typ = (h[i] + l[i] + c[i]) / 3.0
        vol = max(0.0, v[i])
        cum_pv += typ * vol
        cum_vol += vol
        out[i] = (cum_pv / cum_vol) if cum_vol > 0 else typ
    return out


def cci(high: Sequence[float], low: Sequence[float], close: Sequence[float],
        period: int = 20) -> Series:
    """Commodity Channel Index."""
    if period <= 0:
        raise ValueError("period must be positive")
    h, l, c = _clean(high), _clean(low), _clean(close)
    n = len(c)
    out: Series = [None] * n
    if n < period:
        return out
    typ = [(h[i] + l[i] + c[i]) / 3.0 for i in range(n)]
    for i in range(period - 1, n):
        window = typ[i - period + 1:i + 1]
        mean_tp = sum(window) / period
        mad = sum(abs(x - mean_tp) for x in window) / period
        out[i] = ((typ[i] - mean_tp) / (0.015 * mad)) if mad > 0 else 0.0
    return out


def z_score(values: Sequence[float], period: int = 20) -> Series:
    """Z-score (standard score) over trailing window."""
    if period <= 1:
        raise ValueError("period must be greater than 1")
    data = _clean(values)
    n = len(data)
    out: Series = [None] * n
    if n < period:
        return out
    for i in range(period - 1, n):
        window = data[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / (period - 1)
        stdev = variance ** 0.5
        out[i] = ((data[i] - mean) / stdev) if stdev > 0 else 0.0
    return out


REGISTRY = {
    "sma": sma,
    "ema": ema,
    "wma": wma,
    "rsi": rsi,
    "atr": atr,
    "bollinger": bollinger,
    "macd": macd,
    "stochastic": stochastic,
    "adx": adx,
    "donchian": donchian,
    "slope": slope,
    "vwap": vwap,
    "cci": cci,
    "z_score": z_score,
}


def compute(name: str, *args, **kwargs):
    """
    Look up an indicator by name.

    Lets indicator calls be stored as data in the database and replayed without
    the caller importing a specific function.
    """
    if name not in REGISTRY:
        raise KeyError(f"Unknown indicator '{name}'. Known: {sorted(REGISTRY)}")
    return REGISTRY[name](*args, **kwargs)

