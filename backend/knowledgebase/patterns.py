"""
knowledgebase — Patterns
=========================
Pattern detection over OHLC bars.

Pure logic again: no I/O, no database, no gateway. Every detector takes bars
and returns matches with the bar index they were found at, so a caller can
line the result up against the original series without guessing.

Two families are provided:

  * Candlestick  - shape of one to three bars (engulfing, hammer, doji...)
  * Price action - structure across many bars (breakout, support touch, trend)

Every detector returns `List[PatternMatch]` sorted by index. A detector that
finds nothing returns an empty list; it never raises for market data.
"""

from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Sequence

Number = float


@dataclass(frozen=True)
class Bar:
    """One OHLC bar. `time` is epoch seconds as delivered by MT5."""
    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def body_ratio(self) -> float:
        """Body as a share of total range. 1.0 is a marubozu, 0.0 a doji."""
        r = self.range
        return self.body / r if r else 0.0

    @classmethod
    def from_dict(cls, d: Dict) -> "Bar":
        return cls(
            time=int(d["time"]), open=float(d["open"]), high=float(d["high"]),
            low=float(d["low"]), close=float(d["close"]),
            tick_volume=int(d.get("tick_volume", 0)),
        )


@dataclass
class PatternMatch:
    """A pattern found at a specific bar."""
    pattern: str
    index: int
    direction: str          # bullish | bearish | neutral
    strength: float         # 0..1, how textbook the shape is
    label: str = ""
    meta: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


def to_bars(rows: Sequence[Dict]) -> List[Bar]:
    """Convert gateway candle dicts into Bar objects."""
    return [Bar.from_dict(r) for r in rows]


# ─── Candlestick detectors ────────────────────────────────────────────
# Each returns a match for bar `i` or None. `i` is the LAST bar of the
# pattern, so a three-bar pattern reports on the third.


def _doji(bars: List[Bar], i: int, max_ratio: float = 0.1) -> Optional[PatternMatch]:
    b = bars[i]
    if b.range == 0 or b.body_ratio > max_ratio:
        return None
    return PatternMatch("doji", i, "neutral", 1.0 - b.body_ratio / max_ratio,
                        "indecision", {"body_ratio": b.body_ratio})


def _hammer(bars: List[Bar], i: int) -> Optional[PatternMatch]:
    b = bars[i]
    if b.range == 0 or b.body_ratio > 0.4:
        return None
    if b.lower_wick < 2 * b.body or b.upper_wick > b.body:
        return None
    strength = min(b.lower_wick / max(b.range, 1e-12), 1.0)
    direction = "bullish" if b.bullish else "bullish"   # hammer signals a reversal up
    return PatternMatch("hammer", i, direction, strength, "reversal up",
                        {"body_ratio": b.body_ratio, "lower_wick": b.lower_wick})


def _shooting_star(bars: List[Bar], i: int) -> Optional[PatternMatch]:
    b = bars[i]
    if b.range == 0 or b.body_ratio > 0.4:
        return None
    if b.upper_wick < 2 * b.body or b.lower_wick > b.body:
        return None
    strength = min(b.upper_wick / max(b.range, 1e-12), 1.0)
    return PatternMatch("shooting_star", i, "bearish", strength, "reversal down",
                        {"body_ratio": b.body_ratio, "upper_wick": b.upper_wick})


def _bullish_engulfing(bars: List[Bar], i: int) -> Optional[PatternMatch]:
    if i < 1:
        return None
    prev, cur = bars[i - 1], bars[i]
    if not (not prev.bullish and cur.bullish):
        return None
    if not (cur.open <= prev.close and cur.close >= prev.open):
        return None
    overlap = cur.body / max(prev.body, 1e-12)
    return PatternMatch("bullish_engulfing", i, "bullish", min(overlap / 2.0, 1.0),
                        "buyers absorbed the prior decline",
                        {"engulf_ratio": overlap})


def _bearish_engulfing(bars: List[Bar], i: int) -> Optional[PatternMatch]:
    if i < 1:
        return None
    prev, cur = bars[i - 1], bars[i]
    if not (prev.bullish and not cur.bullish):
        return None
    if not (cur.open >= prev.close and cur.close <= prev.open):
        return None
    overlap = cur.body / max(prev.body, 1e-12)
    return PatternMatch("bearish_engulfing", i, "bearish", min(overlap / 2.0, 1.0),
                        "sellers absorbed the prior advance",
                        {"engulf_ratio": overlap})


def _morning_star(bars: List[Bar], i: int) -> Optional[PatternMatch]:
    if i < 2:
        return None
    a, b, c = bars[i - 2], bars[i - 1], bars[i]
    if not (not a.bullish and c.bullish):
        return None
    if b.body > a.body * 0.5:            # small middle bar
        return None
    if not (c.close > (a.open + a.close) / 2):
        return None
    return PatternMatch("morning_star", i, "bullish", 0.7, "three-bar bullish reversal",
                        {"middle_body": b.body, "first_body": a.body})


def _evening_star(bars: List[Bar], i: int) -> Optional[PatternMatch]:
    if i < 2:
        return None
    a, b, c = bars[i - 2], bars[i - 1], bars[i]
    if not (a.bullish and not c.bullish):
        return None
    if b.body > a.body * 0.5:
        return None
    if not (c.close < (a.open + a.close) / 2):
        return None
    return PatternMatch("evening_star", i, "bearish", 0.7, "three-bar bearish reversal",
                        {"middle_body": b.body, "first_body": a.body})


def _marubozu(bars: List[Bar], i: int, min_ratio: float = 0.9) -> Optional[PatternMatch]:
    b = bars[i]
    if b.range == 0 or b.body_ratio < min_ratio:
        return None
    direction = "bullish" if b.bullish else "bearish"
    return PatternMatch("marubozu", i, direction, b.body_ratio,
                        "conviction bar, almost no rejection",
                        {"body_ratio": b.body_ratio})


# ─── Price-action detectors ────────────────────────────────────────────


def _approach(bars: List[Bar], i: int, level: float, band: float,
              from_below: bool, min_gap: int = 3) -> bool:
    """
    True when the bars leading up to i were all clearly on one side of a level.

    A level "test" is price arriving at it from a distance, not merely being
    near it. Without this requirement a range-bound instrument produces a
    support hit on over half of all bars, which describes sideways movement
    rather than naming a pattern.
    """
    if i < min_gap:
        return False
    prior = bars[i - min_gap:i]
    if from_below:
        return all(b.high < level - band for b in prior)
    return all(b.low > level + band for b in prior)


def _support_touch(bars: List[Bar], i: int, lookback: int = 100,
                   tolerance: float = 0.001,
                   min_prior_touches: int = 2,
                   max_bars_since: int = 40) -> Optional[PatternMatch]:
    """
    Price dips into a level that has held before, arriving from above.

    Requires the level to have been defended at least twice, not retested very
    recently, and price to have come down to it from a distance. All three are
    needed; dropping any one lets this fire on most bars of a ranging market.
    """
    if i < lookback:
        return None
    window = bars[i - lookback:i]
    lows = sorted(b.low for b in window)
    if len(lows) < 20:
        return None
    level = lows[len(lows) // 10]
    if level <= 0:
        return None
    band = level * tolerance
    if bars[i].low > level + band:
        return None
    if not _approach(bars, i, level, band, from_below=False):
        return None

    touches = [j for j, b in enumerate(window) if abs(b.low - level) <= band]
    if len(touches) < min_prior_touches:
        return None
    last = touches[-1]
    if len(window) - last > max_bars_since:
        return None

    depth = min(max(0.0, (level + band - bars[i].low) / band), 1.0) if band else 0.0
    return PatternMatch("support_touch", i, "bullish", depth,
                        "price tested a repeatedly defended level from above",
                        {"level": round(level, 8), "prior_touches": len(touches),
                         "bars_since": len(window) - last})


def _resistance_touch(bars: List[Bar], i: int, lookback: int = 100,
                      tolerance: float = 0.001,
                      min_prior_touches: int = 2,
                      max_bars_since: int = 40) -> Optional[PatternMatch]:
    """Mirror of support_touch: a ceiling tested from below."""
    if i < lookback:
        return None
    window = bars[i - lookback:i]
    highs = sorted(b.high for b in window)
    if len(highs) < 20:
        return None
    level = highs[-max(1, len(highs) // 10)]
    band = level * tolerance
    if bars[i].high < level - band:
        return None
    if not _approach(bars, i, level, band, from_below=True):
        return None

    touches = [j for j, b in enumerate(window) if abs(b.high - level) <= band]
    if len(touches) < min_prior_touches:
        return None
    last = touches[-1]
    if len(window) - last > max_bars_since:
        return None

    depth = min(max(0.0, (bars[i].high - level + band) / band), 1.0) if band else 0.0
    return PatternMatch("resistance_touch", i, "bearish", depth,
                        "price tested a repeatedly defended ceiling from below",
                        {"level": round(level, 8), "prior_touches": len(touches),
                         "bars_since": len(window) - last})


def _breakout(bars: List[Bar], i: int, lookback: int = 20) -> Optional[PatternMatch]:
    """
    Close decisively beyond the prior range.

    One detector serves both `breakout_up` and `breakout_down`, naming the
    direction in the match. Earlier versions wrapped this in lambdas with
    separate up/down predicates, which re-derived a condition the function
    already checks and could drift out of step with it.
    """
    if i < lookback:
        return None
    window = bars[i - lookback:i]
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    if lo == hi:
        return None
    span = hi - lo
    close = bars[i].close
    if close > hi + span * 0.1:
        return PatternMatch("breakout_up", i, "bullish",
                            min((close - hi) / (span * 0.3), 1.0),
                            "closed above the prior range", {"level": hi})
    if close < lo - span * 0.1:
        return PatternMatch("breakout_down", i, "bearish",
                            min((lo - close) / (span * 0.3), 1.0),
                            "closed below the prior range", {"level": lo})
    return None


def _higher_low(bars: List[Bar], i: int, lookback: int = 10,
                min_step: float = 0.0015) -> Optional[PatternMatch]:
    """
    Uptrend structure: recent swing low clearly above the prior one.

    `min_step` is relative, because on a 5-digit pair an absolute threshold
    makes this fire constantly while on an index it never fires at all. Without
    it, two independently sampled minima differ by a trivial amount on most
    bars and the detector degenerates into "price went up at some point".
    """
    if i < lookback * 2:
        return None
    recent = min(b.low for b in bars[i - lookback:i])
    prior = min(b.low for b in bars[i - lookback * 2:i - lookback])
    if prior <= 0 or recent <= prior * (1 + min_step):
        return None
    step = (recent - prior) / prior
    return PatternMatch("higher_low", i, "bullish", min(step / (min_step * 5), 1.0),
                        "uptrend making higher lows",
                        {"recent_low": round(recent, 8),
                         "prior_low": round(prior, 8),
                         "step_pct": round(step * 100, 4)})


def _lower_high(bars: List[Bar], i: int, lookback: int = 10,
                min_step: float = 0.0015) -> Optional[PatternMatch]:
    """Downtrend structure: recent swing high clearly below the prior one."""
    if i < lookback * 2:
        return None
    recent = max(b.high for b in bars[i - lookback:i])
    prior = max(b.high for b in bars[i - lookback * 2:i - lookback])
    if prior <= 0 or recent >= prior * (1 - min_step):
        return None
    step = (prior - recent) / prior
    return PatternMatch("lower_high", i, "bearish", min(step / (min_step * 5), 1.0),
                        "downtrend making lower highs",
                        {"recent_high": round(recent, 8),
                         "prior_high": round(prior, 8),
                         "step_pct": round(step * 100, 4)})


# ─── Registry ─────────────────────────────────────────────────────────

def _pinbar(bars: List[Bar], i: int) -> Optional[PatternMatch]:
    """Rejection pinbar: long nose (>=60% of candle range) with small body near opposite extreme."""
    if i < 1:
        return None
    b = bars[i]
    rng = b.high - b.low
    if rng <= 0:
        return None
    body = abs(b.close - b.open)
    upper_wick = b.high - max(b.open, b.close)
    lower_wick = min(b.open, b.close) - b.low
    if lower_wick / rng >= 0.60 and body / rng <= 0.30:
        strength = min(1.0, lower_wick / rng)
        return PatternMatch("pinbar_bullish", i, "bullish", strength,
                            "strong rejection of lower prices (bullish pinbar)",
                            {"lower_wick_ratio": round(lower_wick / rng, 2), "body_ratio": round(body / rng, 2)})
    if upper_wick / rng >= 0.60 and body / rng <= 0.30:
        strength = min(1.0, upper_wick / rng)
        return PatternMatch("pinbar_bearish", i, "bearish", strength,
                            "strong rejection of higher prices (bearish pinbar)",
                            {"upper_wick_ratio": round(upper_wick / rng, 2), "body_ratio": round(body / rng, 2)})
    return None


def _fair_value_gap(bars: List[Bar], i: int) -> Optional[PatternMatch]:
    """3-bar imbalance (Fair Value Gap) with untraded price zone between bar i-2 and bar i."""
    if i < 2:
        return None
    b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]
    if b2.low > b0.high:
        gap = b2.low - b0.high
        avg_rng = (b0.range + b1.range + b2.range) / 3.0
        if avg_rng > 0 and gap >= 0.15 * avg_rng:
            strength = min(1.0, gap / avg_rng)
            return PatternMatch("fvg_bullish", i, "bullish", strength,
                                "bullish fair value gap / imbalance",
                                {"gap": round(gap, 6), "gap_bottom": b0.high, "gap_top": b2.low})
    if b2.high < b0.low:
        gap = b0.low - b2.high
        avg_rng = (b0.range + b1.range + b2.range) / 3.0
        if avg_rng > 0 and gap >= 0.15 * avg_rng:
            strength = min(1.0, gap / avg_rng)
            return PatternMatch("fvg_bearish", i, "bearish", strength,
                                "bearish fair value gap / imbalance",
                                {"gap": round(gap, 6), "gap_bottom": b2.high, "gap_top": b0.low})
    return None


CANDLESTICK: Dict[str, Callable[[List[Bar], int], Optional[PatternMatch]]] = {
    "doji": _doji,
    "hammer": _hammer,
    "shooting_star": _shooting_star,
    "bullish_engulfing": _bullish_engulfing,
    "bearish_engulfing": _bearish_engulfing,
    "morning_star": _morning_star,
    "evening_star": _evening_star,
    "marubozu": _marubozu,
    "pinbar_bullish": _pinbar,
    "pinbar_bearish": _pinbar,
    "fvg_bullish": _fair_value_gap,
    "fvg_bearish": _fair_value_gap,
}

PRICE_ACTION: Dict[str, Callable[[List[Bar], int], Optional[PatternMatch]]] = {
    "support_touch": _support_touch,
    "resistance_touch": _resistance_touch,
    "higher_low": _higher_low,
    "lower_high": _lower_high,
}

# `breakout_up` and `breakout_down` share one detector, which returns a match
# already named for its direction.
_BREAKOUT_ONLY = {"breakout_up", "breakout_down"}

REGISTRY: Dict[str, Callable[[List[Bar], int], Optional[PatternMatch]]] = {
    **CANDLESTICK, **PRICE_ACTION,
    "breakout_up": _breakout,
    "breakout_down": _breakout,
}


def scan(bars: List[Bar], patterns: Optional[Sequence[str]] = None,
         start: int = 0) -> List[PatternMatch]:
    """
    Run detectors over every bar and collect matches.

    `start` skips the warm-up region so detectors with lookbacks do not fire on
    insufficient history, which is where false positives concentrate.

    A detector may serve several registered names - `breakout_up` and
    `breakout_down` share one - so results are de-duplicated on
    (index, pattern). Without that, scanning both names would report the same
    breakout twice.
    """
    names = list(patterns) if patterns else list(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise KeyError(f"Unknown pattern(s): {unknown}. Known: {sorted(REGISTRY)}")

    # Detectors run once per bar, not once per name.
    detectors = {}
    for name in names:
        fn = REGISTRY[name]
        detectors.setdefault(fn, []).append(name)

    out: List[PatternMatch] = []
    seen = set()
    for i in range(max(start, 2), len(bars)):
        for fn, accepted in detectors.items():
            try:
                match = fn(bars, i)
            except (IndexError, ZeroDivisionError, KeyError):
                match = None
            if match is None or match.pattern not in accepted:
                continue
            key = (match.index, match.pattern)
            if key in seen:
                continue
            seen.add(key)
            out.append(match)
    out.sort(key=lambda m: (m.index, m.pattern))
    return out


def describe() -> Dict[str, str]:
    """Human-readable catalogue, used by the database and patternchecker."""
    return {
        "doji": "Tiny body relative to range. Indecision.",
        "hammer": "Long lower wick, small body. Reversal up.",
        "shooting_star": "Long upper wick, small body. Reversal down.",
        "bullish_engulfing": "Up bar swallows the prior down bar. Reversal up.",
        "bearish_engulfing": "Down bar swallows the prior up bar. Reversal down.",
        "morning_star": "Down, small, up. Three-bar bullish reversal.",
        "evening_star": "Up, small, down. Three-bar bearish reversal.",
        "marubozu": "Body fills nearly the whole range. Conviction.",
        "support_touch": "Price reached a level defended repeatedly before.",
        "resistance_touch": "Price reached a ceiling defended repeatedly before.",
        "breakout_up": "Closed above the prior 20-bar range.",
        "breakout_down": "Closed below the prior 20-bar range.",
        "higher_low": "Recent low above the prior low. Uptrend structure.",
        "lower_high": "Recent high below the prior high. Downtrend structure.",
        "pinbar_bullish": "Long lower rejection wick, small upper body. Bullish reversal.",
        "pinbar_bearish": "Long upper rejection wick, small lower body. Bearish reversal.",
        "fvg_bullish": "Untraded bullish liquidity gap between bar i-2 high and bar i low.",
        "fvg_bearish": "Untraded bearish liquidity gap between bar i-2 low and bar i high.",
    }
