# Bot tools

Local trading/backtesting tools that run against the Cotrade gateway.

- `datafeed.py` fetches and caches MT5 candles.
- `engine.py` runs deterministic backtests with MT5 bid/ask semantics.
- `patternchecker.py` scans patterns and measures follow-through.
- `runner.py` sweeps strategies and records reports.
- `live.py` places dry-run/live orders through the gateway.

None of these modules should import from `tools.simulatedtester`.
