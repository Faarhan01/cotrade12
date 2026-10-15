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
    n = len(tr)
    out: Series = [None] * n
    # Seed with SMA of the first `period` true ranges, then Wilder smooth.
    seed_idx = None
    total = 0.0
    count = 0
    for i in range(n):
        if tr[i] is None:
            continue
        total += tr[i]
        count += 1
        if count == period:
            seed_idx = i
            break
    if seed_idx is None:
        return out
    out[seed_idx] = total / period
    for i in range(seed_idx + 1, n):
        if tr[i] is None or out[i - 1] is None:
            continue
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


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



def obv(close: Sequence[float], volume: Sequence[float]) -> Series:
    """On-Balance Volume."""
    c, v = _clean(close), _clean(volume)
    n = len(c)
    out: Series = [0.0] * n
    s = 0.0
    for i in range(1, n):
        if c[i] > c[i - 1]:
            s += v[i]
        elif c[i] < c[i - 1]:
            s -= v[i]
        out[i] = s
    return out


def cmf(high: Sequence[float], low: Sequence[float], close: Sequence[float],
        volume: Sequence[float], period: int = 20) -> Series:
    """Chaikin Money Flow."""
    if period <= 0:
        raise ValueError("period must be positive")
    h, l, c, vol = _clean(high), _clean(low), _clean(close), _clean(volume)
    n = len(c)
    out: Series = [None] * n
    mfv = []
    for i in range(n):
        rng = max(h[i] - l[i], 1e-12)
        multiplier = ((c[i] - l[i]) - (h[i] - c[i])) / rng
        mfv.append(multiplier * max(vol[i], 0.0))
    for i in range(period - 1, n):
        numerator = sum(mfv[i - period + 1:i + 1])
        denominator = sum(vol[i - period + 1:i + 1]) or 1.0
        out[i] = numerator / denominator
    return out


def parabolic_sar(high: Sequence[float], low: Sequence[float],
                  step: float = 0.02, max_step: float = 0.2) -> Series:
    """Parabolic SAR."""
    h, l = _clean(high), _clean(low)
    n = len(h)
    out: Series = [None] * n
    if n < 2:
        return out
    uptrend = h[1] >= h[0]
    sar = l[0] if uptrend else h[0]
    ep = h[1] if uptrend else l[1]
    af = step
    for i in range(1, n):
        if uptrend:
            sar = sar + af * (ep - sar)
            if sar > min(l[i - 1], l[i]):
                sar = min(l[i - 1], l[i])
            if h[i] > ep:
                ep = h[i]
                af = min(max_step, af + step)
            if l[i] < sar:
                uptrend = False
                sar = ep
                ep = l[i]
                af = step
        else:
            sar = sar + af * (ep - sar)
            if sar < max(h[i - 1], h[i]):
                sar = max(h[i - 1], h[i])
            if l[i] < ep:
                ep = l[i]
                af = min(max_step, af + step)
            if h[i] > sar:
                uptrend = True
                sar = ep
                ep = h[i]
                af = step
        out[i] = sar
    out[0] = sar
    return out


def supertrend(high: Sequence[float], low: Sequence[float],
               close: Sequence[float], period: int = 10,
               multiplier: float = 3.0) -> Tuple[Series, Series]:
    """Return (supertrend values, direction) where direction is +1/-1."""
    tr = list(true_range(high, low, close))
    atr_values = atr(high, low, close, period)
    h, l, c = _clean(high), _clean(low), _clean(close)
    n = len(c)
    upper = [None] * n
    lower = [None] * n
    direction = [1] * n
    final = [None] * n
    for i in range(n):
        if tr[i] is None:
            continue
        hl2 = (h[i] + l[i]) / 2.0
        if atr_values[i] is not None:
            upper[i] = hl2 + multiplier * atr_values[i]
            lower[i] = hl2 - multiplier * atr_values[i]
    for i in range(period, n):
        if lower[i] is None or upper[i] is None:
            final[i] = final[i - 1]
            continue
        if lower[i] < lower[i - 1] and c[i - 1] < lower[i - 1]:
            lower[i] = lower[i - 1]
        if upper[i] > upper[i - 1] and c[i - 1] > upper[i - 1]:
            upper[i] = upper[i - 1]
        if c[i] <= lower[i]:
            direction[i] = -1
            final[i] = upper[i]
        else:
            direction[i] = 1
            final[i] = lower[i]
    return final, [float(x) for x in direction]


def keltner_channels(high: Sequence[float], low: Sequence[float],
                     close: Sequence[float], period: int = 20,
                     multiplier: float = 2.0) -> Tuple[Series, Series, Series]:
    """Return lower/middle/upper Keltner channels."""
    ema_mid = ema(close, period)
    atr_values = atr(high, low, close, period)
    n = len(close)
    lower: Series = [None] * n
    middle: Series = [x for x in ema_mid]
    upper: Series = [None] * n
    for i in range(n):
        if middle[i] is not None and atr_values[i] is not None:
            lower[i] = middle[i] - multiplier * atr_values[i]
            upper[i] = middle[i] + multiplier * atr_values[i]
    return lower, middle, upper


def ichimoku(high: Sequence[float], low: Sequence[float],
             close: Sequence[float]) -> Tuple[Series, Series, Series, Series]:
    """Return tenkan, kijun, senkou A, and senkou B."""
    def _span(period):
        out = [None] * len(close)
        for i in range(period - 1, len(close)):
            window_high = max(high[i - period + 1:i + 1])
            window_low = min(low[i - period + 1:i + 1])
            out[i] = (window_high + window_low) / 2.0
        return out

    tenkan = _span(9)
    kijun = _span(26)
    senkou_a = [None] * len(close)
    senkou_b = [None] * len(close)
    for i in range(25, len(close)):
        if tenkan[i - 25] is not None and kijun[i - 25] is not None:
            senkou_a[i] = (tenkan[i - 25] + kijun[i - 25]) / 2.0
    span_52 = _span(52)
    for i in range(51, len(close)):
        if span_52[i - 25] is not None:
            senkou_b[i] = span_52[i - 25]
    return tenkan, kijun, senkou_a, senkou_b


REGISTRY.update({
    "obv": obv,
    "cmf": cmf,
    "parabolic_sar": parabolic_sar,
    "supertrend": supertrend,
    "keltner": keltner_channels,
    "ichimoku": ichimoku,
})
