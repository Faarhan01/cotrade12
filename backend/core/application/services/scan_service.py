from __future__ import annotations



class PatternScanService:
    def __init__(self, research):
        self._research = research

    def run(self, symbol, timeframe, **kw):
        return self._research.pattern_scan(symbol, timeframe, **kw)
