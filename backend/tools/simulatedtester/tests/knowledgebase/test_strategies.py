from knowledgebase import strategies


def test_strategy_roundtrip():
    s = strategies.Strategy(name="test", entry_name="ma_cross")
    data = s.to_dict()
    restored = strategies.Strategy.from_dict(data)
    assert restored.name == s.name
    assert restored.entry_name == s.entry_name


def test_pattern_entry_any_skips_neutral():
    from knowledgebase.patterns import PatternMatch
    ctx = strategies.Context(bars=[])
    ctx.scanned = True
    ctx.matches[0] = [
        PatternMatch("doji", 0, "neutral", 1.0),
        PatternMatch("hammer", 0, "bullish", 1.0),
    ]
    assert strategies.pattern_entry(ctx, 0, direction="any") == 1


def test_context_indicators_use_ohlc_and_volume_inputs():
    from knowledgebase.patterns import Bar
    bars = [Bar(time=i, open=1.0 + i * 0.001, high=1.01 + i * 0.001,
                low=0.99 + i * 0.001, close=1.0 + i * 0.001,
                tick_volume=100 + i) for i in range(40)]
    ctx = strategies.Context(bars=bars)
    assert ctx.ind("cci", 20) is not None
    assert ctx.ind("obv") is not None
    assert ctx.ind("supertrend", 10, 3.0) is not None


def test_validate_strategy_rejects_unknown_entry_parameter():
    from knowledgebase.api import Research
    r = Research(fetch=lambda *a, **k: [])
    result = r.validate_strategy({
        "name": "bad",
        "entry_name": "ma_cross",
        "entry_params": {"fast": 20, "slow": 50, "confirmation_bars": 1},
    })
    assert result["valid"] is False
    assert any("entry_params" in problem for problem in result["problems"])
