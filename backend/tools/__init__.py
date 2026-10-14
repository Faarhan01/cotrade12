"""
tools — Backend tooling
========================
The bot: strategy testing and live trading, driven by the knowledgebase and
executed through the cony gateway.

    python -m tools.bot.runner sweep EURUSD --timeframe M15
    python -m tools.bot.runner scan  EURUSD --timeframe H1
    python -m tools.bot.runner list
    python -m tools.bot.runner report
"""

__all__ = ["bot"]
