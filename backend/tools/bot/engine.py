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
close, take-profit and stop are checked against subsequent bars' high/low, a
bar that touches both exits at the stop (pessimistic), and trailing stops are
only tested from the following bar onward. Bars are treated as MT5 bid quotes,
so a long pays the ask on entry and the bid on exit, and a short pays the bid
on entry and the ask on exit.
"""

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from knowledgebase.patterns import Bar
from knowledgebase.strategies import Context, Strategy


class StrategyError(RuntimeError):
    """Raised when a strategy cannot be evaluated safely."""


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
    spread_cost: float = 0.0

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
    tie_policy: str = "pessimistic"

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
    def spread_cost(self) -> float:
        return sum(t.spread_cost for t in self.trades)

    @property
    def gross_points(self) -> float:
        return self.net_points + self.spread_cost

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
        """Per-trade Sharpe (mean / stdev), not annualised.

        Multiplying by sqrt(trade_count) here would reproduce t_statistic and
        present the same number under a second, more impressive name.
        """
        if len(self.trades) < 3:
            return None
        n = len(self.trades)
        pnls = [t.pnl_points / (self.pip or 1.0) for t in self.trades]
        mean_pnl = sum(pnls) / n
        var = sum((p - mean_pnl) ** 2 for p in pnls) / (n - 1)
        if var <= 0:
            return None
        return round(mean_pnl / math.sqrt(var), 4)

    @property
    def sortino_ratio(self) -> Optional[float]:
        """Per-trade Sortino (mean / downside deviation)."""
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
        return round(mean_pnl / math.sqrt(downside_var), 4)

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
            "gross_points": self.gross_points,
            "spread_cost": self.spread_cost,
            "expectancy": self.expectancy,
            "t_statistic": self.t_statistic,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_drawdown": self.max_drawdown,
            "verdict": self.verdict,
            "tie_policy": self.tie_policy,
            "avg_bars_held": (sum(t.bars_held for t in self.trades)
                              / len(self.trades)) if self.trades else None,
        })
        return d


# ─── Verdict thresholds ───────────────────────────────────────────────
# Chosen once, in one place, so every report is judged the same way.

SIGNIFICANT_T = 2.045       # conservative p<0.05 two-tailed at n=30
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

    net = result.net_points
    # "Fragile" means gross did not comfortably cover the round-trip cost.
    if net <= 0 or result.gross_points < result.spread_cost * MIN_EDGE_VS_COST:
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
                              symbol=inst.get("symbol", ""),
                              timeframe=strategy.timeframe,
                              bars=len(bars),
                              from_ts=bars[0].time if bars else None,
                              to_ts=bars[-1].time if bars else None)

    pip = pip if pip is not None else inst.get("pip")
    if not pip or pip <= 0:
        raise ValueError(
            "no pip size for this instrument; pass pip= explicitly or "
            "load symbol_info before running a backtest")

    if len(bars) > 1 and any(bars[k].time <= bars[k - 1].time
                             for k in range(1, len(bars))):
        raise ValueError("bars must be strictly time-ordered")

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
        except (IndexError, KeyError) as exc:
            raise StrategyError(
                f"{strategy.name} failed at bar {i}: {exc}") from exc
        if side == 0:
            i += 1
            continue

        bar = bars[i]
        # MT5 bars are bid quotes. A long buys at the ask and sells at the bid;
        # a short sells at the bid and buys back at the ask. This charges one
        # round-trip spread exactly once, rather than charging it on both legs.
        entry = bar.close + (spread_pts if side == 1 else 0.0)
        tp = entry + side * exit_rule.take_profit * pip if exit_rule.take_profit else None
        sl = entry - side * exit_rule.stop_loss * pip if exit_rule.stop_loss else None
        max_bars = exit_rule.time_stop_bars or 20

        def exit_price_at(level: float) -> float:
            return level + (spread_pts if side == -1 else 0.0)

        exit_price, reason, exit_index = None, "time", min(i + max_bars, len(bars) - 1)
        pending_trail = None
        j = i + 1
        while j <= exit_index:
            b = bars[j]

            # A level derived from an earlier bar is tested on this bar first.
            if pending_trail is not None:
                hit = (b.low <= pending_trail) if side == 1 else (b.high >= pending_trail)
                if hit:
                    exit_price, reason, exit_index = pending_trail, "trailing", j
                    break

            # Pessimistic tie policy: if a bar reaches both levels, assume the
            # stop was touched first. Without this, tight TP/SL rules book
            # take-profits on bars that also traded through the stop.
            if side == 1:
                if sl is not None and b.low <= sl:
                    exit_price, reason, exit_index = exit_price_at(sl), "stop_loss", j
                    break
                if tp is not None and b.high >= tp:
                    exit_price, reason, exit_index = exit_price_at(tp), "take_profit", j
                    break
            else:
                if sl is not None and b.high >= sl:
                    exit_price, reason, exit_index = exit_price_at(sl), "stop_loss", j
                    break
                if tp is not None and b.low <= tp:
                    exit_price, reason, exit_index = exit_price_at(tp), "take_profit", j
                    break

            if exit_rule.breakeven_after_pips:
                favorable = (b.high - entry) if side == 1 else (entry - b.low)
                if favorable >= exit_rule.breakeven_after_pips * pip:
                    sl = max(sl or entry, entry) if side == 1 else min(sl or entry, entry)

            if exit_rule.trailing_stop:
                moved = (b.high - entry) if side == 1 else (entry - b.low)
                candidate = moved - exit_rule.trailing_stop * pip
                if candidate > 0:
                    level = entry + side * candidate
                    if pending_trail is None or side * (level - entry) > side * (pending_trail - entry):
                        pending_trail = level
            j += 1

        if exit_price is None:
            if pending_trail is not None:
                exit_price, reason = exit_price_at(pending_trail), "trailing"
            else:
                last = bars[exit_index]
                exit_price = last.close + (spread_pts if side == -1 else 0.0)
                reason = "time"

        pnl = side * (exit_price - entry)
        result.trades.append(Trade(
            side=side, entry_index=i, exit_index=exit_index,
            entry_price=entry, exit_price=exit_price,
            pnl_points=pnl, reason=reason, bars_held=exit_index - i,
            spread_cost=spread_pts,
        ))
        i = exit_index + 1

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
