"""
knowledgebase — Research API
=============================
Strategy work as a callable service, so an agent can create strategies, scan
for patterns, compute indicators and run backtests without knowing anything
about the file layout.

Takes its market data through an injected `fetch` callable rather than
importing the gateway directly. That keeps the knowledgebase free of transport
details while still letting the daemon expose the whole thing over HTTP.

    from knowledgebase.api import Research
    r = Research(fetch=lambda sym, tf, **kw: bars_from_somewhere(sym, tf))
    r.catalogue()
    r.pattern_scan("EURUSD", "M15")
    r.backtest(spec, "EURUSD", "M15")
"""

from typing import Callable, Dict, List, Optional

from knowledgebase import indicators as ind
from knowledgebase import patterns as kpatterns
from knowledgebase import strategies as kstrategies
from knowledgebase.patterns import Bar

Fetch = Callable[..., List[Bar]]


class Research:
    """
    Strategy research service.

    One instance per daemon process; holds the injected data fetcher and an
    optional store so results persist between calls.
    """

    def __init__(self, fetch: Fetch, store=None):
        self._fetch = fetch
        self._store = store

    # ─── Discovery ──────────────────────────────────────────────────────

    def catalogue(self) -> Dict:
        """
        Everything that can be built, in one call.

        An agent should read this before composing anything: it lists every
        indicator, pattern and entry rule with its parameters, so a strategy can
        be written from documented names rather than guessed.
        """
        return {
            "indicators": self._indicator_catalogue(),
            "patterns": self._pattern_catalogue(),
            "entry_rules": self._entry_rule_catalogue(),
            "exit_fields": {
                "take_profit": "pips to exit in profit",
                "stop_loss": "pips to exit at a loss",
                "trailing_stop": "pips to trail the high/low by",
                "time_stop_bars": "bars to hold before closing anyway",
                "breakeven_after_pips": "move the stop to entry after this much profit",
            },
            "sizing_fields": {
                "mode": "fixed | risk_pct",
                "lots": "lot size when mode is fixed",
                "risk_pct": "percent of balance to risk when mode is risk_pct",
                "max_lots": "hard ceiling",
            },
            "notes": [
                "Distances are in pips, not points.",
                "A backtest is only evidence if its verdict beats 'noise'.",
                "Patterns must be validated by follow-through, not assumed.",
            ],
        }

    def _indicator_catalogue(self) -> List[Dict]:
        meta = {
            "sma": ("trend", ["close"], "Simple moving average."),
            "ema": ("trend", ["close"], "Exponential moving average."),
            "wma": ("trend", ["close"], "Linearly weighted moving average."),
            "rsi": ("momentum", ["close"], "Relative Strength Index, Wilder."),
            "atr": ("volatility", ["high", "low", "close"], "Average True Range."),
            "bollinger": ("volatility", ["close"], "Bollinger Bands; returns 3 series."),
            "macd": ("momentum", ["close"], "MACD; returns 3 series."),
            "stochastic": ("momentum", ["high", "low", "close"], "Stochastic %K."),
            "adx": ("trend", ["high", "low", "close"], "Average Directional Index."),
            "donchian": ("volatility", ["high", "low"], "Donchian channels; returns 2."),
            "slope": ("trend", ["close"], "Least-squares slope, normalised."),
            "vwap": ("volume", ["high", "low", "close", "volume"], "Volume-weighted average price."),
            "cci": ("momentum", ["high", "low", "close"], "Commodity Channel Index."),
            "z_score": ("statistical", ["close"], "Standardized deviation / Z-score over window."),
        }
        out = []
        for name in sorted(ind.REGISTRY):
            category, inputs, description = meta.get(name, ("other", ["close"], ""))
            multi = name in ("bollinger", "macd", "donchian")
            out.append({
                "name": name,
                "category": category,
                "inputs": inputs,
                "series": {"bollinger": ["lower", "middle", "upper"],
                           "macd": ["macd", "signal", "histogram"],
                           "donchian": ["upper", "lower"]}.get(name, ["value"]),
                "description": description,
                "note": "Returns a list aligned to the input; None during warm-up."
                        if not multi else "Returns several aligned series.",
            })
        return out

    def _pattern_catalogue(self) -> List[Dict]:
        descriptions = kpatterns.describe()
        return [
            {
                "name": name,
                "family": ("candlestick" if name in kpatterns.CANDLESTICK
                           else "price_action"),
                "description": descriptions.get(name, ""),
            }
            for name in sorted(kpatterns.REGISTRY)
        ]

    def _entry_rule_catalogue(self) -> List[Dict]:
        signatures = {
            "rsi_reversion": {"period": 14, "oversold": 30.0, "overbought": 70.0,
                              "confirm": 0},
            "ma_cross": {"fast": 20, "slow": 50, "confirm_bars": 1},
            "breakout_entry": {"period": 20},
            "pattern_entry": {"patterns": ["bullish_engulfing"],
                              "direction": "bullish", "require_strength": 0.5},
            "momentum_entry": {"lookback": 10, "up_bars": 5, "mode": "follow"},
            "trend_strength_entry": {"period": 14, "min_adx": 25.0},
        }
        out = []
        for name in sorted(kstrategies.ENTRY_RULES):
            out.append({
                "name": name,
                "description": kstrategies.describe_entry_rules().get(name, ""),
                "default_params": signatures.get(name, {}),
                "returns": "+1 long, -1 short, 0 no trade",
            })
        return out

    # ─── Market data ────────────────────────────────────────────────────

    def bars(self, symbol: str, timeframe: str = "M1",
             count: int = 2000, days: Optional[int] = None) -> List[Bar]:
        return self._fetch(symbol, timeframe, count=count, days=days)

    # ─── Indicators ─────────────────────────────────────────────────────

    def indicator(self, symbol: str, name: str, timeframe: str = "M1",
                  count: int = 2000, params: Optional[List] = None,
                  warmup_only: bool = False) -> Dict:
        """
        Compute one indicator over recent bars.

        The last `warmup_only` bars are returned by default so a caller gets
        values that exist rather than a wall of nulls from the seeding period.
        """
        if name not in ind.REGISTRY:
            return {"error": f"unknown indicator '{name}'",
                    "known": sorted(ind.REGISTRY)}
        bars = self.bars(symbol, timeframe, count)
        if not bars:
            return {"error": "no bars returned for the symbol"}

        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        args = list(params or [])

        if name in ("atr", "stochastic", "adx", "true_range"):
            result = ind.compute(name, highs, lows, closes, *args)
        elif name == "donchian":
            result = ind.compute(name, highs, lows, *args)
        else:
            result = ind.compute(name, closes, *args)

        series = {"bollinger": ["lower", "middle", "upper"],
                  "macd": ["macd", "signal", "histogram"],
                  "donchian": ["upper", "lower"]}.get(name)

        if series:
            out = {}
            for label, values in zip(series, result):
                out[label] = [
                    {"time": b.time, "value": v}
                    for b, v in zip(bars, values) if v is not None
                ][-warmup_only:] if warmup_only else [
                    {"time": b.time, "value": v}
                    for b, v in zip(bars, values)
                ]
            return {"symbol": symbol, "timeframe": timeframe, "indicator": name,
                    "series": out, "bars": len(bars)}

        values = [{"time": b.time, "value": v}
                  for b, v in zip(bars, result) if v is not None]
        if warmup_only:
            values = values[-warmup_only:]
        return {"symbol": symbol, "timeframe": timeframe, "indicator": name,
                "bars": len(bars), "warmup_bars":
                    sum(1 for v in result if v is None),
                "series": values}

    # ─── Patterns ───────────────────────────────────────────────────────

    def pattern_scan(self, symbol: str, timeframe: str = "M1",
                     count: int = 2000, days: Optional[int] = None,
                     only: Optional[List[str]] = None,
                     horizon: int = 5) -> Dict:
        """
        Find patterns and measure whether price actually followed them.

        The follow-through column is the point. A catalogue of patterns is
        decoration; what matters is whether the move after the signal beat the
        spread, so hit rate, mean move, a Bonferroni-corrected t-statistic and
        a verdict are all returned.

        Both gross and net figures are present and the verdict is taken from
        the net one. Delegated to `CheckReport` so this endpoint and the CLI
        cannot drift into reporting different numbers for the same scan.
        """
        from tools.bot import datafeed
        from tools.bot.patternchecker import CheckReport

        bars = self.bars(symbol, timeframe, count, days)
        if not bars:
            return {"error": "no bars returned for the symbol"}
        matches = kpatterns.scan(bars, patterns=only)

        report = CheckReport(symbol, timeframe, bars, matches,
                             datafeed.instrument(symbol))
        result = report.to_dict()
        follow = result["follow_through"]

        # `horizon` is a caller choice; CheckReport fixes it at 5, so
        # recompute only the follow-through when a different one was asked for.
        if horizon != 5:
            from tools.bot.patternchecker import analyse_follow_through
            follow = analyse_follow_through(bars, matches, horizon=horizon,
                                            spread_pct=report.spread_pct())
            result["follow_through"] = follow
            result["horizon"] = horizon

        result["significant_after_correction"] = sorted(
            (k for k, v in follow.items() if v.get("verdict") == "significant"),
            key=lambda k: -abs(follow[k].get("t_statistic_edge") or 0))
        # Real signal, but the spread eats it. Distinct from "no effect".
        result["cost_marginal"] = sorted(
            k for k, v in follow.items() if v.get("cost_marginal"))
        # The only list worth building a strategy from.
        result["tradable_as_signalled"] = sorted(
            k for k, v in follow.items()
            if v.get("trade_direction") == "as_signalled")
        result["tradable_inverted"] = sorted(
            k for k, v in follow.items()
            if v.get("trade_direction") == "inverted")
        return result

    # ─── Strategies ─────────────────────────────────────────────────────

    def validate_strategy(self, spec: Dict) -> Dict:
        """
        Check a strategy definition and report what is wrong with it.

        Returns the normalised spec on success so a caller can store exactly
        what will be run.
        """
        problems = []
        if not spec.get("name"):
            problems.append("'name' is required")
        entry = spec.get("entry_name")
        if not entry:
            problems.append("'entry_name' is required")
        elif entry not in kstrategies.ENTRY_RULES:
            problems.append(f"unknown entry rule '{entry}'. "
                            f"Known: {sorted(kstrategies.ENTRY_RULES)}")

        params = spec.get("entry_params") or {}
        if not isinstance(params, dict):
            problems.append("'entry_params' must be an object")

        exit_rule = spec.get("exit_rule") or {}
        if exit_rule:
            if not any(exit_rule.get(k) for k in
                       ("take_profit", "stop_loss", "trailing_stop",
                        "time_stop_bars")):
                problems.append(
                    "exit_rule needs at least one of take_profit, stop_loss, "
                    "trailing_stop or time_stop_bars, or positions never close")
            tp, sl = exit_rule.get("take_profit"), exit_rule.get("stop_loss")
            # Parenthesised deliberately. Written as
            #   `tp and sl and tp <= 0 or sl and sl <= 0`
            # Python binds `and` tighter than `or`, so that parsed as
            # `(tp and sl and tp <= 0) or (sl and sl <= 0)` - the take-profit
            # check was gated on a stop-loss also being present, and a
            # definition with a negative take-profit and no stop-loss was
            # accepted. The engine then places that take-profit *below* entry
            # on a long and books the loss as a resolved "take_profit", which
            # corrupts the resolved ratio every verdict is built on.
            if (tp and tp <= 0) or (sl and sl <= 0):
                problems.append("take_profit and stop_loss must be positive")

        if problems:
            return {"valid": False, "problems": problems}
        plan = kstrategies.Strategy.from_dict(spec)
        try:
            plan.entry  # noqa: B018 - raises if the rule name is unknown
        except KeyError as exc:
            return {"valid": False, "problems": [str(exc)]}
        return {"valid": True, "strategy": plan.to_dict()}

    def save_strategy(self, spec: Dict) -> Dict:
        """Validate then persist. Returns the stored strategy on success."""
        result = self.validate_strategy(spec)
        if not result["valid"]:
            return result
        if self._store is None:
            return {"valid": True, "stored": False,
                    "detail": "no database attached; returning normalised spec",
                    "strategy": result["strategy"]}
        self._store.save_strategy(kstrategies.Strategy.from_dict(result["strategy"]))
        return {"valid": True, "stored": True, "strategy": result["strategy"]}

    def list_strategies(self) -> List[Dict]:
        if self._store is None:
            return []
        return self._store.list_strategies()

    def get_strategy(self, name: str) -> Optional[Dict]:
        if self._store is None:
            return None
        plan = self._store.load_strategy(name)
        return plan.to_dict() if plan else None

    def library(self) -> List[Dict]:
        return [p.to_dict() for p in kstrategies.library()]

    # ─── Backtesting ────────────────────────────────────────────────────

    def backtest(self, spec: Dict, symbol: str, timeframe: str = "M1",
                 count: int = 4000, warmup: int = 60,
                 spread_pips: Optional[float] = None) -> Dict:
        """
        Backtest one strategy and return the full statistical report.

        `spec` may name a stored strategy or carry a full definition, so an
        agent can test something it just wrote without saving it first.
        """
        from tools.bot import datafeed
        from tools.bot.engine import run, sweep

        validation = self.validate_strategy(spec)
        if not validation["valid"]:
            return validation
        plan = kstrategies.Strategy.from_dict(validation["strategy"])

        bars = self.bars(symbol, timeframe, count)
        if len(bars) < warmup + 50:
            return {"error": f"only {len(bars)} bars available, need "
                             f"{warmup + 50} to evaluate"}

        inst = datafeed.instrument(symbol)
        if spread_pips is not None:
            inst["spread_pips"] = spread_pips
        plan.symbol = symbol
        plan.timeframe = timeframe
        plan.spread_pips = inst.get("spread_pips", 0.0)

        result = run(plan, bars, inst, warmup=warmup)
        report = result.to_dict()
        report["symbol"] = symbol
        report["timeframe"] = timeframe
        report["spread_pips"] = plan.spread_pips
        report["pip_value_per_lot"] = inst.get("pip_value_per_lot")
        report["net_money_per_lot"] = round(
            report["net_pips"] * (inst.get("pip_value_per_lot") or 0.0), 2)
        report["min_lot"] = inst.get("min_lot")

        split = sweep(plan, bars, inst, warmup=warmup)
        if "train" in split:
            report["split_check"] = {
                "consistent": split["consistent"],
                "train_net_pips": round(split["train"].get("net_pips", 0.0), 1),
                "test_net_pips": round(split["test"].get("net_pips", 0.0), 1),
                "test_t": split["test"].get("t_statistic"),
            }

        if self._store is not None:
            self._store.save_report({
                "run_id": "api",
                "strategy_name": plan.name,
                "strategy_snapshot": plan.to_dict(),
                "symbol": symbol,
                "timeframe": timeframe,
                "pip": inst.get("pip") or 1.0,
                "bars": len(bars),
                "from_ts": report.get("from_ts"),
                "to_ts": report.get("to_ts"),
                "split": "full",
                "trades": report["trades"],
                "resolved": report["resolved"],
                "win_rate": report["win_rate"],
                "resolved_win_rate": report["resolved_win_rate"],
                "profit_factor": report["profit_factor"],
                "net_points": report["net_points"],
                "gross_points": report["gross_points"],
                "spread_cost": report["trades"] * 2 * plan.spread_pips
                               * (inst.get("pip") or 1.0),
                "max_drawdown": report["max_drawdown"],
                "expectancy": report["expectancy"],
                "t_statistic": report["t_statistic"],
                "verdict": report["verdict"],
            })

        report["interpretation"] = self._interpret(report)
        return report

    @staticmethod
    def _interpret(report: Dict) -> str:
        """
        Plain-language reading of a report.

        A verdict string alone is easy to misread; this says what it means and
        what the next step should be.
        """
        verdict = report.get("verdict")
        trades = report.get("trades", 0)
        if verdict == "no_trades":
            return "The rule never fired. Loosen the entry or use more bars."
        if verdict == "insufficient":
            return (f"Only {trades} trades - too few to measure. "
                    f"Use more history or a more frequent entry.")
        if verdict == "unresolvable":
            return ("Most trades closed on the time stop without reaching "
                    "take-profit or stop-loss, so the exit is untestable. "
                    "Move the levels closer or shorten the time stop.")
        if verdict == "noise":
            return ("No result here is distinguishable from chance. The t "
                    "statistic is too small; do not trade this on this data.")
        if verdict == "fragile":
            return ("Statistically significant but net negative, or it only "
                    "survived because gross happened to exceed costs. "
                    "Treat as unusable.")
        if verdict == "promising":
            return ("Significant and profitable after costs. Now check the "
                    "train/test split and replicate on other symbols before "
                    "trusting it.")
        if verdict == "strong":
            return ("Strongly significant and profitable after costs. "
                    "Still verify out-of-sample before risking capital.")
        return "No verdict."

    def sweep(self, specs: List[Dict], symbol: str, timeframe: str = "M1",
              count: int = 4000) -> Dict:
        """Backtest several strategies over the same data, ranked by |t|."""
        results = []
        for spec in specs:
            report = self.backtest(spec, symbol, timeframe, count)
            if "error" in report or report.get("valid") is False:
                continue
            results.append(report)
        results.sort(key=lambda r: abs(r.get("t_statistic") or 0), reverse=True)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "tested": len(results),
            "results": [
                {k: r.get(k) for k in
                 ("strategy_name", "trades", "resolved", "win_rate",
                  "resolved_win_rate", "profit_factor", "net_pips",
                  "net_money_per_lot", "t_statistic", "verdict")}
                for r in results
            ],
            "best": results[0].get("strategy_name") if results else None,
        }
