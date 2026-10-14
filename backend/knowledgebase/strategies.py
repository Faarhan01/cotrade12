"""
knowledgebase — Strategies
============================
Declarative strategy definitions: entry logic, exit rules, sizing.

Everything is a dataclass with `to_dict` / `from_dict` so a strategy can be
stored in SQLite as data and reconstructed later without importing the module
that defined it. That matters because the alternative - keeping live callables
around - makes strategies unpersistable.

`Strategy.entry` is a function `(ctx, i) -> int` returning +1 long, -1 short,
0 no trade. It is deliberately a callable rather than a serialised rule tree
because the rule trees tried for this turn into a miniature language nobody
wants to debug; the *parameters* live in the dataclass, the logic stays in
Python, and `to_dict` records both name and parameters.
"""

from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional

from knowledgebase import indicators as ind
from knowledgebase.patterns import Bar, PatternMatch


@dataclass
class Context:
    """
    Bars plus indicator values, addressed by index.

    Strategies ask for what they need; indicators are computed once and cached
    because ATR over 10k bars is not free and a grid search would call it
    thousands of times.
    """
    bars: List[Bar]
    indicators: Dict[str, list] = field(default_factory=dict)
    matches: Dict[int, List[PatternMatch]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.bars)

    def close(self) -> List[float]:
        return [b.close for b in self.bars]

    def high(self) -> List[float]:
        return [b.high for b in self.bars]

    def low(self) -> List[float]:
        return [b.low for b in self.bars]

    # Indicators that take (high, low, close, ...) rather than (close, ...).
    _OHLC = {"atr", "stochastic", "adx", "true_range"}

    def ind(self, name: str, *args, **kwargs) -> list:
        """
        Fetch (and cache) an indicator series.

        The OHLC variants get high/low/close supplied automatically so callers
        write `ctx.ind("atr", 14)` rather than threading three series through
        every strategy. Cached because ATR over 10k bars is not free and a
        parameter sweep calls it thousands of times.
        """
        key = f"{name}:{args}:{sorted(kwargs.items())}"
        if key in self.indicators:
            return self.indicators[key]
        if name in self._OHLC:
            series = ind.compute(name, self.high(), self.low(), self.close(),
                                 *args, **kwargs)
        elif name == "donchian":
            series = ind.compute(name, self.high(), self.low(), *args, **kwargs)
        else:
            series = ind.compute(name, self.close(), *args, **kwargs)
        self.indicators[key] = series
        return series

    def value(self, name: str, i: int, *args, **kwargs):
        """
        One indicator value at bar i, or None during warm-up.

        Multi-output indicators (bollinger, macd, donchian) return a tuple of
        series; pass `component` to pick one, otherwise a single series is
        assumed and a tuple is an error worth surfacing rather than silently
        indexing the wrong level.
        """
        series = self.ind(name, *args, **kwargs)
        if isinstance(series, tuple):
            raise ValueError(
                f"'{name}' returns {len(series)} series; use ctx.series(name, i) "
                f"to index one, or ctx.ind() for the raw tuple.")
        return series[i] if i < len(series) else None

    def series(self, name: str, i: int, component: int = 0, *args, **kwargs):
        """One component of a multi-output indicator at bar i."""
        result = self.ind(name, *args, **kwargs)
        if not isinstance(result, tuple):
            result = (result,)
        if i >= len(result[component]):
            return None
        return result[component][i]

    def patterns_at(self, i: int, name: Optional[str] = None) -> List[PatternMatch]:
        """
        Pattern matches at bar i, populating the scan on first use.

        Done lazily so a strategy that trades patterns cannot silently return
        zero signals because nobody remembered to attach them.
        """
        if not self.matches:
            from knowledgebase import patterns as _pat
            for match in _pat.scan(self.bars):
                self.matches.setdefault(match.index, []).append(match)
        found = self.matches.get(i, [])
        return [m for m in found if name is None or m.pattern == name]


@dataclass
class ExitRule:
    """How a position is closed. All distances are in pips."""
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    trailing_stop: Optional[float] = None      # trails by this many pips
    time_stop_bars: Optional[int] = None
    breakeven_after_pips: Optional[float] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "ExitRule":
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__annotations__})


@dataclass
class SizingRule:
    """How position size is chosen."""
    mode: str = "fixed"          # fixed | risk_pct
    lots: float = 0.1
    risk_pct: float = 1.0        # percent of balance when mode is risk_pct
    max_lots: Optional[float] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "SizingRule":
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__annotations__})


# ─── Entry rules ──────────────────────────────────────────────────────
# Signature: (ctx, i) -> +1 / -1 / 0


def _clamp(value: Optional[float], low: float, high: float) -> bool:
    return value is not None and low <= value <= high


def rsi_reversion(ctx: Context, i: int, period: int = 14,
                  oversold: float = 30.0, overbought: float = 70.0,
                  confirm: int = 0) -> int:
    """
    Buy oversold, sell overbought.

    `confirm` requires price to have already been moving our way over the
    last `confirm` bars, which filters out the common case of buying straight
    through a falling knife.

    It deliberately looks BACKWARD. An earlier version inspected the next
    `confirm` bars instead, which is look-ahead: the engine fills at
    `bars[i].close`, so a rule that has already read bars i+1..i+confirm is
    deciding with data it could not have had. It also produced backtests that
    looked better than the live behaviour, because the confirmation it
    measured had not happened yet at the moment of entry.
    """
    r = ctx.value("rsi", i, period)
    if r is None:
        return 0
    if confirm:
        side = 1 if r < oversold else (-1 if r > overbought else 0)
        if side == 0:
            return 0
        for k in range(1, confirm + 1):
            j = i - k
            if j < 0:
                return 0
            moved = ctx.bars[i].close - ctx.bars[j].close
            if moved * side <= 0:
                return 0
        return side
    if r < oversold:
        return 1
    if r > overbought:
        return -1
    return 0


def ma_cross(ctx: Context, i: int, fast: int = 20, slow: int = 50,
             confirm_bars: int = 1) -> int:
    """Trend entry on a moving-average cross, requiring the cross to be recent."""
    f_now, s_now = ctx.value("sma", i, fast), ctx.value("sma", i, slow)
    if f_now is None or s_now is None:
        return 0
    f_prev = ctx.value("sma", i - confirm_bars, fast)
    s_prev = ctx.value("sma", i - confirm_bars, slow)
    if f_prev is None or s_prev is None:
        return 0
    if f_prev <= s_prev and f_now > s_now:
        return 1
    if f_prev >= s_prev and f_now < s_now:
        return -1
    return 0


def breakout_entry(ctx: Context, i: int, period: int = 20,
                   confirm: bool = False) -> int:
    """Donchian breakout: close beyond the prior `period` bars' range."""
    upper = ctx.series("donchian", i, 0, period)
    lower = ctx.series("donchian", i, 1, period)
    if upper is None or lower is None:
        return 0
    bar = ctx.bars[i]
    if bar.close > upper:
        return 1
    if bar.close < lower:
        return -1
    return 0


def pattern_entry(ctx: Context, i: int, patterns: Optional[List[str]] = None,
                  direction: str = "bullish", require_strength: float = 0.0) -> int:
    """Trade a candlestick or price-action pattern."""
    for match in ctx.patterns_at(i):
        if patterns and match.pattern not in patterns:
            continue
        if match.strength < require_strength:
            continue
        if direction == "any":
            return 1 if match.direction == "bullish" else (
                -1 if match.direction == "bearish" else 0)
        if match.direction != direction:
            continue
        return 1 if direction == "bullish" else -1
    return 0


def momentum_entry(ctx: Context, i: int, lookback: int = 10,
                   up_bars: int = 5, mode: str = "follow") -> int:
    """
    Enter on a run of same-direction bars - the family tested on Step Index.

    mode="follow" trades with the move, mode="fade" trades against it.
    """
    if i < lookback:
        return 0
    window = ctx.bars[i - lookback + 1:i + 1]
    ups = sum(1 for j in range(1, len(window)) if window[j].close > window[j - 1].close)
    net = ctx.bars[i].close - ctx.bars[i - lookback].close
    if net > 0 and ups >= up_bars:
        return 1 if mode == "follow" else -1
    if net < 0 and ups <= (lookback - up_bars):
        return -1 if mode == "follow" else 1
    return 0


def trend_strength_entry(ctx: Context, i: int, period: int = 14,
                         min_adx: float = 25.0) -> int:
    """Trade with ADX-confirmed direction and normalised slope."""
    a = ctx.value("adx", i, period)
    s = ctx.value("slope", i, 5)
    if a is None or s is None or a < min_adx:
        return 0
    return 1 if s > 0 else -1


ENTRY_RULES: Dict[str, Callable] = {
    "rsi_reversion": rsi_reversion,
    "ma_cross": ma_cross,
    "breakout_entry": breakout_entry,
    "pattern_entry": pattern_entry,
    "momentum_entry": momentum_entry,
    "trend_strength_entry": trend_strength_entry,
}


@dataclass
class Strategy:
    """A complete, persistable strategy definition."""
    name: str
    description: str = ""
    symbol: str = ""
    timeframe: str = "M1"
    entry_name: str = "ma_cross"
    entry_params: Dict = field(default_factory=dict)
    exit_rule: ExitRule = field(default_factory=ExitRule)
    sizing: SizingRule = field(default_factory=SizingRule)
    spread_pips: float = 0.0
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    created: str = ""

    @property
    def entry(self) -> Callable:
        if self.entry_name not in ENTRY_RULES:
            raise KeyError(
                f"Unknown entry rule '{self.entry_name}'. Known: {sorted(ENTRY_RULES)}")
        return ENTRY_RULES[self.entry_name]

    def signal(self, ctx: Context, i: int) -> int:
        return self.entry(ctx, i, **self.entry_params)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["exit_rule"] = self.exit_rule.to_dict()
        d["sizing"] = self.sizing.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "Strategy":
        d = dict(d or {})
        d["exit_rule"] = ExitRule.from_dict(d.get("exit_rule") or {})
        d["sizing"] = SizingRule.from_dict(d.get("sizing") or {})
        allowed = set(cls.__annotations__)
        return cls(**{k: v for k, v in d.items() if k in allowed})


# ─── Ready-made strategies ────────────────────────────────────────────


def library() -> List[Strategy]:
    """Starter set. Each is a hypothesis to be tested, not a recommendation."""
    return [
        Strategy(
            name="ma_cross_20_50",
            description="Trend following on a 20/50 SMA cross.",
            entry_name="ma_cross",
            entry_params={"fast": 20, "slow": 50, "confirm_bars": 1},
            exit_rule=ExitRule(take_profit=20, stop_loss=20, time_stop_bars=60),
        ),
        Strategy(
            name="rsi_reversion_14",
            description="Mean reversion at RSI extremes.",
            entry_name="rsi_reversion",
            entry_params={"period": 14, "oversold": 30, "overbought": 70},
            exit_rule=ExitRule(take_profit=15, stop_loss=15, time_stop_bars=40),
        ),
        Strategy(
            name="breakout_20",
            description="Donchian 20-bar breakout.",
            entry_name="breakout_entry",
            entry_params={"period": 20},
            exit_rule=ExitRule(take_profit=30, stop_loss=15, time_stop_bars=60),
        ),
        Strategy(
            name="momentum_follow_10",
            description="Ride a 10-bar directional run.",
            entry_name="momentum_entry",
            entry_params={"lookback": 10, "up_bars": 5, "mode": "follow"},
            exit_rule=ExitRule(take_profit=10, stop_loss=10, time_stop_bars=20),
        ),
        Strategy(
            name="momentum_fade_10",
            description="Fade a 10-bar directional run.",
            entry_name="momentum_entry",
            entry_params={"lookback": 10, "up_bars": 5, "mode": "fade"},
            exit_rule=ExitRule(take_profit=10, stop_loss=10, time_stop_bars=20),
        ),
        Strategy(
            name="trend_strength_adx14",
            description="Trade ADX-confirmed direction.",
            entry_name="trend_strength_entry",
            entry_params={"period": 14, "min_adx": 25},
            exit_rule=ExitRule(take_profit=25, stop_loss=15, trailing_stop=10,
                               time_stop_bars=80),
        ),
        Strategy(
            name="engulfing_entry",
            description="Trade engulfing candles in either direction.",
            entry_name="pattern_entry",
            entry_params={"patterns": ["bullish_engulfing", "bearish_engulfing"],
                          "direction": "any", "require_strength": 0.5},
            exit_rule=ExitRule(take_profit=12, stop_loss=12, time_stop_bars=30),
        ),
    ]


def describe_entry_rules() -> Dict[str, str]:
    return {
        "rsi_reversion": "Buy below oversold, sell above overbought.",
        "ma_cross": "Trend entry when a fast SMA crosses a slow SMA.",
        "breakout_entry": "Close beyond the prior Donchian range.",
        "pattern_entry": "Trade a named candlestick or price-action pattern.",
        "momentum_entry": "Follow or fade a run of same-direction bars.",
        "trend_strength_entry": "Direction confirmed by ADX and normalised slope.",
    }
