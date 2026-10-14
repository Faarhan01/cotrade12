"""
tools.bot — Pattern Checker
==============================
Scans market data for the patterns defined in the knowledgebase and reports
where they occur, how strong they are, and whether anything followed them.

Three questions this answers, in order of usefulness:

  1. Does the pattern exist at all in this data?  Some shapes are rare enough
     that a strategy built on them will never fire.
  2. When it does fire, does price actually go the way the pattern claims?
     A bullish engulfing on a random walk is bullish 50% of the time, and
     measuring that directly is the fastest way to find out.
  3. Is the forward move large enough to clear the spread?

The forward analysis in section 2 is the point of the whole exercise. A
pattern catalogue on its own is decoration; what matters is whether the move
after the signal beats the cost of taking it.

    from tools.bot.patternchecker import check
    report = check("EURUSD", "M15", count=3000)
    print(report.summary())
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from knowledgebase import patterns as kpatterns  # noqa: E402
from tools.bot import datafeed  # noqa: E402
from tools.bot.engine import SIGNIFICANT_T  # noqa: E402


def forward_returns(bars, index: int, horizons=(1, 3, 5, 10, 20)) -> Dict[int, float]:
    """Percentage move after `index`, over several horizons."""
    out = {}
    base = bars[index].close
    if not base:
        return out
    for h in horizons:
        j = index + h
        if j < len(bars):
            out[h] = (bars[j].close - base) / base * 100.0
    return out


def _t_statistic(values) -> Optional[float]:
    """Two-sided t on the mean of `values`, or None if undefined."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    if var <= 0:
        return None
    return mean / (var ** 0.5 / n ** 0.5)


def _trade_direction(gross_verdict, net_verdict, mean_net):
    """How - if at all - this pattern could be traded, on the evidence given.

    "as_signalled"  the pattern's own prediction pays after costs.
    "inverted"      the opposite side pays after costs. A statistically
                    significant negative follow-through means price reliably
                    moves against the pattern, which is a tradeable fact even
                    though it is not the one the pattern claims.
    None            no cost-adjusted edge either way.
    """
    if gross_verdict != "significant" or net_verdict != "significant":
        return None
    return "as_signalled" if mean_net > 0 else "inverted"


def _grade(t, threshold):
    """Label a t-statistic against both the plain and corrected thresholds."""
    if t is None:
        return "noise"
    if abs(t) >= threshold:
        return "significant"
    if abs(t) >= SIGNIFICANT_T:
        return "uncorrected"
    return "noise"


def analyse_follow_through(bars, matches, horizon: int = 5,
                           family_alpha: float = 0.05,
                           spread_pct: float = 0.0) -> Dict:
    """
    Does price actually move in the pattern's predicted direction, and is that
    move worth more than it costs to capture?

    Three things are separated, because they are three different questions and
    answering them with one number is how drift gets mistaken for skill:

    1. GROSS  - the raw forward move. On its own this is close to worthless:
       in any period that simply trended, every bullish pattern comes out
       negative and every bearish one positive, whether or not they mean
       anything. Measured, not trusted.
    2. EDGE   - the move minus what the market did anyway over the same
       horizon. This is the only figure that isolates the pattern's own
       contribution, and it is what the verdict is based on. The baseline is
       returned alongside so it can be checked rather than trusted.
    3. NET    - the edge minus the round-trip spread. An edge too small to
       trade is a real effect and no profit, so it is labelled separately.

    `spread_pct` is the round-trip cost as a percentage of price, the unit the
    forward returns are already in.

    A Bonferroni threshold is applied because many patterns are tested at once
    and the most extreme t-statistic is guaranteed to look impressive by
    chance alone - with 14 patterns, the best will clear t=2 about half the
    time even on pure noise. Patterns are only called significant if they
    survive that correction, otherwise every sweep produces a false positive.
    """
    stats = defaultdict(list)
    for m in matches:
        moves = forward_returns(bars, m.index, horizons=(horizon,))
        if horizon not in moves:
            continue
        signed = moves[horizon] if m.direction == "bullish" else (
            -moves[horizon] if m.direction == "bearish" else None)
        if signed is not None:
            stats[m.pattern].append(signed)

    # The control: what a bar did on average over this horizon, entered at any
    # bar at all. Any pattern that cannot beat this has found nothing.
    baseline_moves = [forward_returns(bars, i, horizons=(horizon,))
                      for i in range(len(bars) - horizon)]
    baseline = (sum(m[horizon] for m in baseline_moves if horizon in m)
                / len(baseline_moves)) if baseline_moves else 0.0

    tested = len(stats)
    threshold = bonferroni_threshold(family_alpha, tested) if tested > 1 else SIGNIFICANT_T

    out = {}
    for name, values in stats.items():
        n = len(values)
        if n < 5:
            out[name] = {"n": n, "verdict": "too few", "threshold": round(threshold, 2)}
            continue
        mean = sum(values) / n
        # The pattern's own contribution, with the market's drift removed.
        edge = [v - baseline for v in values]
        mean_edge = sum(edge) / n
        # Then charged the round trip: the spread is paid entering and again
        # leaving, so the full `spread_pct` comes off the edge.
        net = [v - spread_pct for v in edge]
        mean_net = sum(net) / n
        t, t_edge, t_net = (_t_statistic(values), _t_statistic(edge),
                            _t_statistic(net))
        hit = 100.0 * sum(1 for v in values if v > 0) / n
        hit_edge = 100.0 * sum(1 for v in edge if v > 0) / n

        gross_verdict = _grade(t_edge, threshold)
        net_verdict = _grade(t_net, threshold)
        out[name] = {
            "n": n,
            "hit_rate": round(hit, 1),
            "hit_rate_edge": round(hit_edge, 1),
            "mean_move_pct": round(mean, 5),
            "baseline_pct": round(baseline, 5),
            "mean_edge_pct": round(mean_edge, 5),
            "mean_edge_pct_net": round(mean_net, 5),
            "t_statistic": round(t, 2) if t is not None else None,
            "t_statistic_edge": round(t_edge, 2) if t_edge is not None else None,
            "t_statistic_net": round(t_net, 2) if t_net is not None else None,
            "threshold": round(threshold, 2),
            # Judged on the EDGE, not the raw move. In a trending sample the
            # raw move is dominated by drift and will make every bullish
            # pattern look bearish and every bearish one look bullish.
            "verdict": gross_verdict,
            "net_verdict": net_verdict,
            # Which way to actually trade it. A significant NEGATIVE effect is
            # not a dead pattern - it is one that reliably moves the other
            # way, which is tradable by taking the opposite side. Reporting
            # only the predicted direction throws that away.
            "trade_direction": _trade_direction(gross_verdict, net_verdict,
                                                mean_net),
        }
        # A real effect that the spread eats. Named explicitly because "no
        # effect at all" and "an effect too small to trade" lead to opposite
        # conclusions.
        if (t_edge is not None and t_net is not None
                and abs(t_edge) >= SIGNIFICANT_T and abs(t_net) < SIGNIFICANT_T):
            out[name]["cost_marginal"] = True
            out[name]["note"] = ("significant before costs, not after - the "
                                 "spread is larger than the effect")
    return out


def bonferroni_threshold(alpha: float, tests: int) -> float:
    """Two-tailed critical |t| for `tests` comparisons at family-wise alpha."""
    if tests <= 1:
        return SIGNIFICANT_T
    per_test = alpha / tests
    try:
        from statistics import NormalDist
        return NormalDist().inv_cdf(1 - per_test / 2)
    except Exception:
        return 3.0


class CheckReport:
    """Result of one pattern scan."""

    def __init__(self, symbol, timeframe, bars, matches, inst):
        self.symbol = symbol
        self.timeframe = timeframe
        self.bars = bars
        self.matches = matches
        self.inst = inst
        self.by_pattern = defaultdict(list)
        for m in matches:
            self.by_pattern[m.pattern].append(m)

    @property
    def counts(self) -> Counter:
        return Counter(m.pattern for m in self.matches)

    @property
    def density(self) -> float:
        """Matches per 100 bars, summed across every pattern scanned."""
        return 100.0 * len(self.matches) / max(len(self.bars), 1)

    def busiest_pattern_rate(self) -> float:
        """Highest firing rate of any single pattern, as % of bars.

        The aggregate `density` sums all patterns, so it scales with however
        many detectors are registered and reads alarmingly high on a healthy
        scan. This is the number that would actually indicate a broken
        detector - a single pattern firing on a third of all bars.
        """
        if not self.bars:
            return 0.0
        return 100.0 * max(self.counts.values(), default=0) / len(self.bars)

    def spread_pct(self) -> float:
        """Round-trip spread cost as a percentage of price.

        The unit the forward returns are already expressed in, so costs and
        moves can be compared directly. Uses the mean close as the reference
        rather than the last bar, which would make the ratio depend on where
        in the sample it was computed.
        """
        if not self.bars:
            return 0.0
        pips = self.inst.get("spread_pips") or 0.0
        pip = self.inst.get("pip") or 1.0
        price = sum(b.close for b in self.bars) / len(self.bars)
        if not price:
            return 0.0
        return 100.0 * (pips * pip) / price

    def frequent_enough(self, minimum: int = 5) -> List[str]:
        return [p for p, n in self.counts.items() if n >= minimum]

    def summary(self) -> str:
        lines = [
            f"{self.symbol} {self.timeframe} - {len(self.bars)} bars, "
            f"{len(self.matches)} matches ({self.density:.1f} per 100 bars)",
        ]
        if not self.matches:
            lines.append("  no patterns found")
            return "\n".join(lines)

        lines.append("")
        lines.append(f"  {'pattern':<22} {'count':>6} {'bull':>5} {'bear':>5} "
                     f"{'neut':>5} {'avg str':>8}")
        for name, group in sorted(self.by_pattern.items(),
                                  key=lambda kv: -len(kv[1])):
            dirs = Counter(m.direction for m in group)
            strength = sum(m.strength for m in group) / len(group)
            lines.append(f"  {name:<22} {len(group):>6} {dirs.get('bullish', 0):>5} "
                         f"{dirs.get('bearish', 0):>5} {dirs.get('neutral', 0):>5} "
                         f"{strength:>8.2f}")

        spread_pct = self.spread_pct()
        follow = analyse_follow_through(self.bars, self.matches, horizon=5,
                                        spread_pct=spread_pct)
        if follow:
            tested = [s for s in follow.values() if s.get("t_statistic") is not None]
            if tested:
                threshold = tested[0]["threshold"]
                lines.append("")
                lines.append("  follow-through over 5 bars, signed by predicted direction")
                lines.append(f"  Bonferroni threshold for {len(tested)} patterns "
                             f"tested: |t| >= {threshold:.2f}")
                lines.append("")
                lines.append(f"  {'pattern':<22} {'n':>5} {'hit%':>7} "
                             f"{'raw%':>9} {'edge%':>9} {'edge_net%':>10} "
                             f"{'t_edge':>7} {'t_net':>7}  verdict")
                for name, stats in sorted(follow.items(),
                                          key=lambda kv: -abs(kv[1].get("t_statistic_edge") or 0)):
                    if stats.get("verdict") == "too few":
                        lines.append(f"  {name:<22} {stats['n']:>5}"
                                     f"{'  too few samples':>36}")
                        continue
                    lines.append(f"  {name:<22} {stats['n']:>5} "
                                 f"{stats['hit_rate']:>6.1f}% "
                                 f"{stats['mean_move_pct']:>8.4f}% "
                                 f"{stats['mean_edge_pct']:>8.4f}% "
                                 f"{stats['mean_edge_pct_net']:>9.4f}% "
                                 f"{stats['t_statistic_edge']:>6.2f} "
                                 f"{stats['t_statistic_net']:>6.2f}  "
                                 + (f"[{stats['trade_direction'].upper()}] "
                                    if stats.get("trade_direction") else "")
                                 + stats['verdict']
                                 + ("  [cost-marginal]" if stats.get("cost_marginal") else ""))
                lines.append("")
                lines.append(f"  the market moved {follow and list(follow.values())[0]['baseline_pct']:+.4f}% "
                             f"on average over this horizon from any bar")
                lines.append("  raw% is that pattern's raw move; edge% removes the "
                             "market drift, edge_net% then charges the spread")
                lines.append("  'uncorrected' clears t=2 but not the family-wise threshold")
                lines.append("  a negative edge means price moved AGAINST the pattern")
                lines.append("  'verdict' judges the edge (does the pattern beat the market?), "
                             "'net_verdict' judges it after costs (is it worth "
                             "trading?)")
                lines.append("  [AS_SIGNALLED] trades the pattern's own way; [INVERTED] trades "
                             "the opposite way")

        spread_pips = self.inst.get("spread_pips") or 0.0
        if spread_pips:
            lines.append("")
            lines.append(f"  spread is {spread_pips:.2f} pips "
                         f"({spread_pct:.4f}% of price); any follow-through "
                         f"smaller than that costs money to trade")

        usable = self.frequent_enough()
        lines.append("")
        lines.append(f"  patterns with >=5 occurrences: "
                     f"{', '.join(usable) if usable else 'none'}")
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars": len(self.bars),
            "matches": len(self.matches),
            "density_per_100_bars": round(self.density, 2),
            "busiest_pattern_per_100_bars": round(self.busiest_pattern_rate(), 2),
            "patterns_scanned": len(kpatterns.REGISTRY),
            "spread_pct": round(self.spread_pct(), 5),
            "counts": dict(self.counts),
            "follow_through": analyse_follow_through(self.bars, self.matches,
                                                  spread_pct=self.spread_pct()),
            "recent": [m.to_dict() for m in self.matches[-25:]],
        }


def check(symbol: str, timeframe: str = "M1", count: int = 3000,
          days: Optional[int] = None, only: Optional[List[str]] = None,
          store=None) -> CheckReport:
    """Scan an instrument and build a report."""
    bars = datafeed.fetch(symbol, timeframe, count=count, days=days, store=store)
    inst = datafeed.instrument(symbol)
    matches = kpatterns.scan(bars, patterns=only)
    return CheckReport(symbol, timeframe, bars, matches, inst)


def check_and_store(symbol: str, timeframe: str = "M1", count: int = 3000,
                    store=None, run_id: Optional[str] = None) -> Dict:
    """Scan and persist the hits, so patterns can be queried later."""
    from database.store import new_run_id
    report = check(symbol, timeframe, count=count, store=store)
    if store is None:
        from database import Store
        store = Store()
        store.migrate()
    rid = run_id or new_run_id("scan")
    payload = []
    for m in report.matches:
        bar = report.bars[m.index]
        payload.append({
            "pattern": m.pattern, "index": m.index, "time": bar.time,
            "direction": m.direction, "strength": m.strength,
            "price": bar.close, "meta": m.meta,
        })
    store.save_hits(rid, symbol, timeframe, payload)
    return {"run_id": rid, **report.to_dict()}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan for chart patterns")
    parser.add_argument("symbol")
    parser.add_argument("--timeframe", "-t", default="M1")
    parser.add_argument("--count", "-c", type=int, default=3000)
    parser.add_argument("--days", "-d", type=int, default=None)
    parser.add_argument("--pattern", "-p", action="append",
                        help="restrict to these patterns (repeatable)")
    parser.add_argument("--save", action="store_true",
                        help="persist hits to the database")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    store = None
    if args.save:
        from database import Store
        store = Store()
        store.migrate()

    report = check(args.symbol, args.timeframe, args.count, args.days,
                   args.pattern, store)
    print(json.dumps(report.to_dict(), indent=2, default=str) if args.json
          else report.summary())

    if args.save:
        from database.store import new_run_id
        payload = [{"pattern": m.pattern, "index": m.index,
                    "time": report.bars[m.index].time, "direction": m.direction,
                    "strength": m.strength, "price": report.bars[m.index].close,
                    "meta": m.meta} for m in report.matches]
        rid = new_run_id("scan")
        saved = store.save_hits(rid, args.symbol, args.timeframe, payload)
        print(f"\nsaved {saved} hits as run {rid}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
