"""Minimal MT5-like simulator and fixtures for isolated behavior checks.

This tool is intentionally self-contained: nothing here may import Cotrade modules.
It can be run directly while developing or copied into another harness.
"""
import json
import random
import time


class FakeTerminal:
    def __init__(self, seed=42, spread_pips=1.0):
        self.random = random.Random(seed)
        self.spread_pips = spread_pips
        self.open_orders = []
        self.next_ticket = 1000

    def tick(self, symbol="EURUSD", value=None):
        if value is None:
            value = 1.0 + (self.random.random() - 0.5) * 0.02
        return {"symbol": symbol, "bid": value - self.spread_pips * 0.00005,
                "ask": value + self.spread_pips * 0.00005}

    def place_order(self, symbol, side, volume, sl=None, tp=None):
        ticket = self.next_ticket
        self.next_ticket += 1
        order = {"ticket": ticket, "symbol": symbol, "side": side,
                 "volume": volume, "sl": sl, "tp": tp, "open_time": time.time()}
        self.open_orders.append(order)
        return ticket

    def close_order(self, ticket):
        before = len(self.open_orders)
        self.open_orders = [o for o in self.open_orders if o["ticket"] != ticket]
        return len(self.open_orders) < before


def scenario(name, fn):
    print(f"SCENARIO {name}")
    return fn()


if __name__ == "__main__":
    ft = FakeTerminal()
    print(json.dumps(ft.tick(), indent=2))
    tid = ft.place_order("EURUSD", 1, 0.1, sl=1.0, tp=2.0)
    print("opened", tid)
    print("closed", ft.close_order(tid))
    print("remaining", len(ft.open_orders))
