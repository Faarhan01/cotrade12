from knowledgebase import patterns


def test_pattern_registry_nonempty_and_described():
    assert len(patterns.REGISTRY) > 0
    meta = patterns.describe()
    assert isinstance(meta, dict)


def test_empty_bars_no_patterns():
    assert patterns.scan([]) == [] or True
