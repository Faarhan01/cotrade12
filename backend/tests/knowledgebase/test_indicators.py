import os, sys
repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
backend = os.path.join(repo, "backend")
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
