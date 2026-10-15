"""Deterministic regression tests for MT5-style fills."""
from knowledgebase.patterns import Bar
from knowledgebase.strategies import Context, ExitRule, pattern_entry
from tools.bot.engine import run


class FixedStrategy:
    def __init__(self, side=1, exit_rule=None, spread_pips=0.0):
        self.name = "fixture"
        self.timeframe = "M1"
        self.spread_pips = spread_pips
        self.exit_rule = exit_rule or ExitRule()
        self.side = side

    def signal(self, ctx, i):
        return self.side


def bar(time, o, h, l, c):
    return Bar(time=time, open=o, high=h, low=l, close=c, tick_volume=100)


INST = {"symbol": "EURUSD", "pip": 0.0001, "point": 0.00001, "spread_pips": 0.0}


def test_same_bar_stop_wins_over_take_profit():
    bars = [bar(i, 1.1000, 1.1006, 1.0994, 1.1000) for i in range(20)]
    result = run(FixedStrategy(exit_rule=ExitRule(take_profit=5, stop_loss=5)), bars, INST, warmup=1)
    assert result.trades
    assert all(t.reason == "stop_loss" and t.pnl_points < 0 for t in result.trades)


def test_round_trip_spread_is_charged_once():
    bars = [bar(i, 1.1000, 1.1000, 1.1000, 1.1000) for i in range(20)]
    inst = dict(INST, spread_pips=1.0)
    long = run(FixedStrategy(1, ExitRule(time_stop_bars=3), 1.0), bars, inst, warmup=1)
    short = run(FixedStrategy(-1, ExitRule(time_stop_bars=3), 1.0), bars, inst, warmup=1)
    assert long.trades and all(abs(t.pnl_points + 0.0001) < 1e-12 for t in long.trades)
    assert short.trades and all(abs(t.pnl_points + 0.0001) < 1e-12 for t in short.trades)


def test_trailing_stop_is_tested_on_next_bar():
    bars = [
        bar(0, 1.1000, 1.1000, 1.1000, 1.1000),
        bar(1, 1.1000, 1.1010, 1.1000, 1.1005),
        bar(2, 1.1005, 1.1006, 1.0994, 1.0995),
    ] + [bar(i + 3, 1.0995, 1.0996, 1.0994, 1.0995) for i in range(10)]
    result = run(FixedStrategy(1, ExitRule(trailing_stop=5, time_stop_bars=4)), bars, INST, warmup=0)
    assert result.trades
    assert result.trades[0].reason == "trailing"
    assert result.trades[0].exit_index == 2


def test_missing_pip_raises_instead_of_guessing():
    bars = [bar(i, 1.1, 1.1, 1.1, 1.1) for i in range(20)]
    try:
        run(FixedStrategy(), bars, {"symbol": "X"}, warmup=1)
    except ValueError as exc:
        assert "pip size" in str(exc)
    else:
        raise AssertionError("expected a missing pip size to fail loudly")


def test_pattern_entry_any_skips_neutral_matches():
    from knowledgebase.patterns import PatternMatch
    ctx = Context(bars=[])
    ctx.scanned = True
    ctx.matches[0] = [
        PatternMatch("doji", 0, "neutral", 1.0),
        PatternMatch("hammer", 0, "bullish", 1.0),
    ]
    assert pattern_entry(ctx, 0, direction="any") == 1
