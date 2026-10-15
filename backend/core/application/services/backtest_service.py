from __future__ import annotations



class BacktestService:
    """Thin wrapper around a Research instance backtest."""

    def __init__(self, research):
        self._research = research

    def run(self, spec, symbol, timeframe, bars=None, **kw):
        return self._research.backtest(spec, symbol, timeframe, bars=bars, **kw)
