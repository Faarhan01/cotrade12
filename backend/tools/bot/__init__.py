"""
tools.bot — Trading Bot
========================
Backtesting and trading built from the knowledgebase, driven by the cony
gateway for data and order execution.

Modules:
  datafeed        fetch bars from the gateway, with a SQLite cache
  engine          backtest a Strategy and judge whether the result is signal
  patternchecker  find patterns and measure whether they actually predict
  runner          sweep strategies and record reports
  live            execute through the gateway

Deliberately not imported here. `patternchecker` and `runner` are runnable as
`python -m tools.bot.<name>`, and pre-importing them here makes runpy load
them twice, which produces a warning and can leave two module instances with
separate state.

Run:  python -m tools.bot.runner sweep --symbol EURUSD --timeframe M15
"""

__all__ = ["datafeed", "engine", "live"]

