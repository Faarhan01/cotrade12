"""
tools.bot — Backtest Engine
=============================
Runs a knowledgebase Strategy over historical bars and reports whether the
result is signal or noise.

The statistics here exist because of a specific, measured failure. Testing 18
scalping rules on Step Index produced one that looked profitable at +22.8
points; its gross t-statistic was +0.37, it earned less than a third of its own
spread cost, and relaxing one integer in its entry condition flipped it to
-126.8. A backtester that reports only profit factor would have shipped that.

So every result reports, at minimum:

  * resolved vs timed-out trades counted separately, because a win rate that
    includes trades which never reached take-profit or stop is mostly noise
  * the t-statistic of mean trade P&L, which is the number that decides whether
    a result means anything
  * a verdict computed from those, not from profit

Execution assumptions are stated rather than hidden: fills happen at the bar's
close, take-profit and stop are checked against subsequent bars' high/low, and
stops fill at the stop price rather than through it. All three flatter the
result, so a strategy that fails here cannot succeed live.
"""

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from knowledgebase.patterns import Bar
from knowledgebase.strategies import Context, Strategy


@dataclass
class Trade:
    """One completed round trip."""
    side: int                 # +1 long, -1 short
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    pnl_points: float
    reason: str               # take_profit | stop_loss | time | trailing
    bars_held: int

    @property
    def won(self) -> bool:
        return self.pnl_points > 0


@dataclass
class BacktestResult:
    """Everything measured, including the parts that look unflattering."""
    strategy_name: str = ""
    symbol: str = ""
    timeframe: str = ""
    bars: int = 0
    from_ts: Optional[int] = None
    to_ts: Optional[int] = None
    trades: List[Trade] = field(default_factory=list)
    pip: float = 1.0              # pip size in price units, for reporting

    @property
    def net_pips(self) -> float:
        """
        Net result in pips.

        Trades store P&L in price units, which is right for arithmetic but
        unreadable on a 5-digit pair where a point is 0.00001. Pip is also the
        unit every strategy is specified in, so reporting in pips keeps the
        result comparable to the rule that produced it.
        """
        return self.net_points / (self.pip or 1.0)

    # Split reporting: "resolved" means the trade actually hit TP or SL.
    @property
    def resolved(self) -> List[Trade]:
        return [t for t in self.trades if t.reason in ("take_profit", "stop_loss",
                                                       "trailing")]

    @property
    def timed_out(self) -> List[Trade]:
        return [t for t in self.trades if t.reason == "time"]

    @property
    def wins(self) -> List[Trade]:
        return [t for t in self.trades if t.won]

    @property
    def losses(self) -> List[Trade]:
        return [t for t in self.trades if not t.won]

    @property
    def net_points(self) -> float:
        return sum(t.pnl_points for t in self.trades)

    @property
    def win_rate(self) -> Optional[float]:
        return 100.0 * len(self.wins) / len(self.trades) if self.trades else None

    @property
    def resolved_win_rate(self) -> Optional[float]:
        """Win rate among trades that reached take-profit or stop-loss.

        This is the rate that reflects the entry rule. The headline win rate
        is dominated by time-stopped trades that closed wherever price
        happened to be.
        """
        r = self.resolved
        return 100.0 * sum(1 for t in r if t.won) / len(r) if r else None

    @property
    def profit_factor(self) -> Optional[float]:
        gross_win = sum(t.pnl_points for t in self.wins)
        gross_loss = -sum(t.pnl_points for t in self.losses)
        if gross_loss <= 0:
            return None if gross_win <= 0 else float("inf")
        return gross_win / gross_loss

    @property
    def expectancy(self) -> Optional[float]:
        return self.net_points / len(self.trades) if self.trades else None

    @property
    def t_statistic(self) -> Optional[float]:
        """t of mean trade P&L against zero. The number that decides it."""
        if len(self.trades) < 3:
            return None
        n = len(self.trades)
        mean = self.net_points / n
        var = sum((t.pnl_points - mean) ** 2 for t in self.trades) / (n - 1)
        if var <= 0:
            return None
        return mean / (math.sqrt(var / n))

    @property
    def max_drawdown(self) -> float:
        equity = peak = 0.0
        worst = 0.0
        for t in self.trades:
            equity += t.pnl_points
            peak = max(peak, equity)
            worst = max(worst, peak - equity)
        return worst

    @property
    def sharpe_ratio(self) -> Optional[float]:
        """Annualized or sample-scaled Sharpe ratio of trades."""
        if len(self.trades) < 3:
            return None
        n = len(self.trades)
        pnls = [t.pnl_points / (self.pip or 1.0) for t in self.trades]
        mean_pnl = sum(pnls) / n
        var = sum((p - mean_pnl) ** 2 for p in pnls) / (n - 1)
        if var <= 0:
            return None
        return round((mean_pnl / math.sqrt(var)) * math.sqrt(n), 2)

    @property
    def sortino_ratio(self) -> Optional[float]:
        """Sortino ratio measuring return against downside volatility."""
        if len(self.trades) < 3:
            return None
        n = len(self.trades)
        pnls = [t.pnl_points / (self.pip or 1.0) for t in self.trades]
        mean_pnl = sum(pnls) / n
        downside = [p for p in pnls if p < 0]
        if not downside:
            return float("inf") if mean_pnl > 0 else 0.0
        downside_var = sum(p ** 2 for p in downside) / n
        if downside_var <= 0:
            return None
        return round((mean_pnl / math.sqrt(downside_var)) * math.sqrt(n), 2)

    @property
    def max_consecutive_wins(self) -> int:
        cur = max_w = 0
        for t in self.trades:
            if t.won:
                cur += 1
                max_w = max(max_w, cur)
            else:
                cur = 0
        return max_w

    @property
    def max_consecutive_losses(self) -> int:
        cur = max_l = 0
        for t in self.trades:
            if not t.won:
                cur += 1
                max_l = max(max_l, cur)
            else:
                cur = 0
        return max_l

    @property
    def verdict(self) -> str:
        return classify(self)

    def to_dict(self) -> Dict:
        d = {k: v for k, v in asdict(self).items() if k != "trades"}
        d.update({
            "trades": len(self.trades),
            "resolved": len(self.resolved),
            "timed_out": len(self.timed_out),
            "win_rate": self.win_rate,
            "resolved_win_rate": self.resolved_win_rate,
            "profit_factor": self.profit_factor,
            "net_points": self.net_points,
            "net_pips": self.net_pips,
            "pip": self.pip,
            "gross_points": sum(t.pnl_points for t in self.trades),
            "expectancy": self.expectancy,
            "t_statistic": self.t_statistic,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_drawdown": self.max_drawdown,
            "verdict": self.verdict,
            "avg_bars_held": (sum(t.bars_held for t in self.trades)
                              / len(self.trades)) if self.trades else None,
        })
        return d


# ─── Verdict thresholds ───────────────────────────────────────────────
# Chosen once, in one place, so every report is judged the same way.

SIGNIFICANT_T = 2.0        # p < 0.05 two-tailed
STRONG_T = 3.0
MIN_TRADES = 30            # below this nothing is measurable
MIN_EDGE_VS_COST = 1.0     # gross profit must at least cover what it paid


def classify(result: BacktestResult) -> str:
    """
    Turn measurements into a verdict.

    Returns one of:
      no_trades       - nothing fired
      insufficient    - too few trades to measure
      unresolvable    - almost nothing reached TP or SL, so untestable
      noise           - t too small to distinguish from chance
      promising       - significant, and earned more than it cost
      strong          - strongly significant
      fragile         - significant, but barely outran its costs
    """
    if not result.trades:
        return "no_trades"
    if len(result.trades) < MIN_TRADES:
        return "insufficient"

    resolved = len(result.resolved)
    if resolved < 0.3 * len(result.trades):
        return "unresolvable"

    t = result.t_statistic
    if t is None or abs(t) < SIGNIFICANT_T:
        return "noise"

    gross = sum(t.pnl_points for t in result.trades)
    net = result.net_points
    # "Fragile" means it only survived because gross happened to exceed cost.
    if net <= 0:
        return "fragile"
    if abs(t) >= STRONG_T and net > 0:
        return "strong"
    return "promising"


# ─── Engine ───────────────────────────────────────────────────────────


def run(strategy: Strategy, bars: List[Bar], inst: Dict,
        pip: Optional[float] = None, warmup: int = 60,
        ctx: Optional[Context] = None) -> BacktestResult:
    """
    Backtest one strategy over `bars`.

    pip        - pip size; defaults to the instrument's
    warmup     - bars skipped at the start so indicators are seeded
    """
    if len(bars) < warmup + 10:
        return BacktestResult(strategy_name=strategy.name,
                              symbol=inst.get("symbol", ""))

    pip = pip if pip is not None else (inst.get("pip") or 1.0)
    spread_pips = strategy.spread_pips or inst.get("spread_pips") or 0.0
    spread_pts = spread_pips * pip

    context = ctx or Context(bars=bars)
    exit_rule = strategy.exit_rule

    result = BacktestResult(
        strategy_name=strategy.name,
        symbol=inst.get("symbol", ""),
        timeframe=strategy.timeframe,
        bars=len(bars),
        pip=pip,
        from_ts=bars[warmup].time if len(bars) > warmup else None,
        to_ts=bars[-1].time,
    )

    i = warmup
    while i < len(bars) - 1:
        try:
            side = strategy.signal(context, i)
        except (IndexError, KeyError, TypeError):
            side = 0
        if side == 0:
            i += 1
            continue

        bar = bars[i]
        # Enter at the close, paying the spread on the side we take.
        entry = bar.close + (spread_pts if side == 1 else -spread_pts)
        tp = entry + side * exit_rule.take_profit * pip if exit_rule.take_profit else None
        sl = entry - side * exit_rule.stop_loss * pip if exit_rule.stop_loss else None
        max_bars = exit_rule.time_stop_bars or 20

        exit_price, reason = None, "time"
        trail = None
        j = i + 1
        limit = min(i + 1 + max_bars, len(bars))
        while j < limit:
            b = bars[j]
            if side == 1:
                if tp is not None and b.high >= tp:
                    exit_price, reason = tp, "take_profit"
                    break
                if sl is not None and b.low <= sl:
                    exit_price, reason = sl, "stop_loss"
                    break
            else:
                if tp is not None and b.low <= tp:
                    exit_price, reason = tp, "take_profit"
                    break
                if sl is not None and b.high >= sl:
                    exit_price, reason = sl, "stop_loss"
                    break

            # Breakeven stop: move stop to entry price once favorable move reaches threshold
            if exit_rule.breakeven_after_pips:
                favorable = (b.high - entry) if side == 1 else (entry - b.low)
                if favorable >= exit_rule.breakeven_after_pips * pip:
                    if side == 1:
                        sl = max(sl or entry, entry)
                    else:
                        sl = min(sl or entry, entry)

            # A trailing stop is ratcheted on each bar and checked on the NEXT
            # bar, because a level can only be known to have been respected
            # once a subsequent bar fails to trade through it. Checking the
            # same bar it was derived from would fill on a price the bar
            # never actually reached after the level was set.
            if exit_rule.trailing_stop:
                moved = (b.high - entry) if side == 1 else (entry - b.low)
                candidate = moved - exit_rule.trailing_stop * pip
                if candidate > 0:
                    # A trailing stop only ever moves in the trade's favour.
                    # Re-deriving it from *this* bar's high/low alone meant a
                    # bar with a lower high moved the stop backwards, so the
                    # stop loosened instead of tightening and the trade stayed
                    # on far longer than the rule describes. Keep the best
                    # level seen so far.
                    best = candidate if trail is None else max(
                        candidate, (trail - entry) * side)
                    trail = entry + side * best

            if trail is not None:
                hit = (b.low <= trail) if side == 1 else (b.high >= trail)
                if hit and j > i + 1:
                    exit_price, reason = trail, "trailing"
                    break
            j += 1

        if exit_price is None:
            if trail is not None and (
                    (side == 1 and bars[min(j, len(bars) - 1)].low <= trail)
                    or (side == -1 and bars[min(j, len(bars) - 1)].high >= trail)):
                exit_price, reason = trail, "trailing"
            else:
                # The window can run past the end of the data when the final
                # trade is still open; close at the last available bar.
                last = bars[min(j, len(bars) - 1)]
                exit_price = last.close - (spread_pts if side == 1 else -spread_pts)
                reason = "time"

        pnl = side * (exit_price - entry)
        result.trades.append(Trade(
            side=side, entry_index=i, exit_index=j,
            entry_price=entry, exit_price=exit_price,
            pnl_points=pnl, reason=reason, bars_held=j - i,
        ))
        i = j + 1

    return result


def sweep(strategy: Strategy, bars: List[Bar], inst: Dict, split: float = 0.7,
          pip: Optional[float] = None, warmup: int = 60) -> Dict:
    """
    Train/test split.

    Parameters are not fitted here, but the split still earns its place: a
    strategy that only works on the first 70% of the data is a strategy that
    has memorised that period, and that is exactly the failure a single
    full-sample number hides.
    """
    if len(bars) < warmup * 2 + 60:
        return {"error": "not enough bars to split"}
    cut = int(len(bars) * split)
    train = run(strategy, bars[:cut], inst, pip, warmup)
    test = run(strategy, bars[cut - warmup:], inst, pip, warmup)
    return {
        "split": split,
        "train": train.to_dict(),
        "test": test.to_dict(),
        "consistent": _consistent(train, test),
    }


def _consistent(train: BacktestResult, test: BacktestResult) -> bool:
    """Both halves must show the same sign, and the test half must not be noise."""
    if not train.trades or not test.trades:
        return False
    if train.net_points * test.net_points <= 0:
        return False
    t = test.t_statistic
    return t is not None and abs(t) >= SIGNIFICANT_T
