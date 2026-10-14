"""
knowledgebase — Reference Library
==================================
Technical indicators, chart patterns and strategy definitions as pure logic.

Deliberately free of I/O so it can be imported by the backtest engine, a live
trader, a notebook or a test without pulling in the gateway or the database.

    from knowledgebase import indicators, patterns, strategies

    rsi = indicators.rsi(prices, 14)
    bars = patterns.to_bars(candle_dicts)
    hits = patterns.scan(bars)
    plan = strategies.Strategy.from_dict(stored_dict)
"""

from knowledgebase import indicators, patterns, strategies
from knowledgebase.patterns import Bar, PatternMatch, scan, to_bars
from knowledgebase.strategies import (
    Context,
    ExitRule,
    SizingRule,
    Strategy,
    ENTRY_RULES,
)

__version__ = "1.0.0"

__all__ = [
    "indicators",
    "patterns",
    "strategies",
    "Bar",
    "PatternMatch",
    "scan",
    "to_bars",
    "Context",
    "ExitRule",
    "SizingRule",
    "Strategy",
    "ENTRY_RULES",
    "__version__",
]
