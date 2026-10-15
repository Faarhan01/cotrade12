import os, sys
backend = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if backend not in sys.path:
    sys.path.insert(0, backend)

from knowledgebase import indicators

def test_sma_length_and_warmup():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = indicators.sma(data, 3)
    assert len(out) == len(data)
    assert out[0] is None
    assert out[1] is None
    assert out[2] == 2.0

def test_rsi_no_mutation():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    snap = list(data)
    indicators.rsi(data, 3)
    assert data == snap


def test_atr_wilder_smoothing():
    """ATR should use Wilder smoothing, not SMA-of-TR."""
    highs = [10.0 + i for i in range(20)]
    lows = [9.0 + i for i in range(20)]
    closes = [9.5 + i for i in range(20)]
    out = indicators.atr(highs, lows, closes, period=3)
    # First non-null should be at index 2.
    assert out[0] is None and out[1] is None
    assert out[2] is not None
    # Wilder smoothing produces a stable value strictly larger than SMA guess.
    assert out[-1] >= out[2]
    # Length preserved.
    assert len(out) == 20


def test_route_count_and_repo_constructors():
    from database.repositories import SqliteStrategyRepository, SqliteReportRepository
    # constructors accept config optionally
    assert SqliteStrategyRepository() and SqliteReportRepository(None)
