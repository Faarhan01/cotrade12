"""
tools.bot — Live Execution
============================
Places real orders through the cony gateway using a knowledgebase Strategy.

Deliberately conservative:

  * `dry_run` is the default. Live orders require passing `live=True`
    explicitly, because the alternative is a strategy sweep that accidentally
    trades a demo account with real money.
  * Every order is checked with the gateway's `/order/check` first, so an
    insufficient-margin or bad-stop rejection is caught before it is sent.
  * Position size comes from `/calc/size`, which uses the symbol's real
    contract size and pip value rather than an assumed one.
  * Nothing here decides a strategy is good. That judgement belongs to
    `engine.classify`, and it belongs in a report a human read.

Before any of this is worth running, the strategy should have a stored report
whose verdict is better than `noise`.
"""

import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from knowledgebase.patterns import Bar                 # noqa: E402
from knowledgebase.strategies import Context, Strategy  # noqa: E402
from tools.bot import datafeed                         # noqa: E402


class LiveTrader:
    """Executes one strategy against the live gateway."""

    def __init__(self, symbol: str, timeframe: str = "M1",
                 strategy: Optional[Strategy] = None,
                 magic: int = 0, dry_run: bool = True):
        self.symbol = symbol
        self.timeframe = timeframe
        self.strategy = strategy
        self.magic = magic
        self.dry_run = dry_run
        self.inst = datafeed.instrument(symbol)
        self.pip = self.inst.get("pip") or 1.0
        self.log: List[Dict] = []

    # ── State ───────────────────────────────────────────────────────────

    def bars(self, count: int = 500) -> List[Bar]:
        return datafeed.bars(self.symbol, self.timeframe, count=count)

    def current_signal(self, bars: Optional[List[Bar]] = None) -> int:
        """Evaluate the strategy on the most recent closed bar."""
        if self.strategy is None:
            raise ValueError("no strategy attached")
        bars = bars or self.bars()
        ctx = Context(bars=bars)
        return self.strategy.signal(ctx, len(bars) - 2)   # -2: last bar may be forming

    def account(self) -> Dict:
        return datafeed._call("GET", "/account")

    def open_positions(self) -> Dict:
        return datafeed._call("GET", f"/positions?symbol={self.symbol}")

    # ── Sizing ──────────────────────────────────────────────────────────

    def size_for(self, risk_amount: float, stop_pips: float) -> Dict:
        """Ask the gateway to size a position from a risk budget."""
        return datafeed._call("POST", "/calc/size", {
            "symbol": self.symbol,
            "risk_amount": risk_amount,
            "stop_pips": stop_pips,
        })

    # ── Orders ──────────────────────────────────────────────────────────

    def check_order(self, side: int, lots: float,
                    sl_pips: Optional[float] = None,
                    tp_pips: Optional[float] = None) -> Dict:
        """
        Dry run through the terminal. Catches insufficient margin, stops in
        the freeze zone and unsupported filling modes before anything is sent.
        """
        tick = datafeed._call("GET", f"/tick/{self.symbol.replace(' ', '%20')}")
        price = tick["ask"] if side == 1 else tick["bid"]
        payload = {
            "symbol": self.symbol,
            "volume": lots,
            "order_type": "buy" if side == 1 else "sell",
            "magic": self.magic,
        }
        if sl_pips:
            payload["sl"] = round(price - side * sl_pips * self.pip, int(self.inst.get("digits") or 5))
        if tp_pips:
            payload["tp"] = round(price + side * tp_pips * self.pip, int(self.inst.get("digits") or 5))
        return datafeed._call("POST", "/order/check", payload)

    def send(self, side: int, lots: float,
             sl_pips: Optional[float] = None,
             tp_pips: Optional[float] = None,
             comment: str = "") -> Dict:
        """Place a market order. Refuses to send unless dry_run is off."""
        if self.dry_run:
            return {"success": False,
                    "blocked": "dry_run",
                    "detail": "Pass dry_run=False to place real orders."}

        check = self.check_order(side, lots, sl_pips, tp_pips)
        if not check.get("accepted"):
            return {"success": False, "blocked": "order_check",
                    "detail": check.get("retcode_description")}

        tick = datafeed._call("GET", f"/tick/{self.symbol.replace(' ', '%20')}")
        price = tick["ask"] if side == 1 else tick["bid"]
        digits = int(self.inst.get("digits") or 5)
        payload = {
            "symbol": self.symbol,
            "volume": lots,
            "order_type": "buy" if side == 1 else "sell",
            "magic": self.magic,
            "comment": comment or f"bot-{side:+d}",
        }
        if sl_pips:
            payload["sl"] = round(price - side * sl_pips * self.pip, digits)
        if tp_pips:
            payload["tp"] = round(price + side * tp_pips * self.pip, digits)

        result = datafeed._call("POST", "/buy" if side == 1 else "/sell", payload)
        self.log.append({"action": "send", "side": side, "lots": lots,
                         "ok": result.get("success"), "at": price})
        return result

    def close_all(self, magic: Optional[int] = None) -> Dict:
        """Flatten this symbol, optionally only one strategy's positions."""
        if self.dry_run:
            return {"success": False, "blocked": "dry_run"}
        payload = {"symbol": self.symbol}
        if magic is not None:
            payload["magic"] = magic
        return datafeed._call("POST", "/close-all", payload)

    # ── Cycle ───────────────────────────────────────────────────────────

    def evaluate(self) -> Dict:
        """
        One decision cycle: read data, evaluate the strategy, report what it
        would do. Does not trade.
        """
        bars = self.bars()
        signal = self.current_signal(bars)
        tick = datafeed._call("GET", f"/tick/{self.symbol.replace(' ', '%20')}")
        rule = self.strategy.exit_rule if self.strategy else None
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars": len(bars),
            "signal": {1: "long", -1: "short", 0: "flat"}[signal],
            "bid": tick.get("bid"),
            "ask": tick.get("ask"),
            "spread_pips": self.inst.get("spread_pips"),
            "would_trade": signal != 0,
            "dry_run": self.dry_run,
            "take_profit_pips": rule.take_profit if rule else None,
            "stop_loss_pips": rule.stop_loss if rule else None,
        }
