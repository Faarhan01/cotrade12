"""
cony — Market Book
====================
Level-2 depth of market via the MetaTrader5 market book interface.

The terminal only maintains a book for symbols that have been explicitly
subscribed to with market_book_add, so this tracks subscriptions itself and
keeps them balanced: every add has a matching release, including on
disconnect, otherwise the terminal leaks a subscription per symbol.
"""

import threading
from typing import Dict, List, Optional

from cony import enums
from cony.serializers import serialize_namedtuple


class MarketBookError(Exception):
    """Market book operation failed."""


class MarketBook:
    """Subscription-aware access to terminal depth-of-market data."""

    def __init__(self, engine):
        self._engine = engine
        self._lock = threading.RLock()
        self._subscribed: set = set()

    @property
    def subscribed(self) -> List[str]:
        """Symbols currently subscribed."""
        with self._lock:
            return sorted(self._subscribed)

    def subscribe(self, symbol: str) -> bool:
        """Start receiving book updates for a symbol."""
        mt5 = self._engine.mt5
        if mt5 is None:
            raise MarketBookError("Not connected to the terminal")

        with self._lock:
            if symbol in self._subscribed:
                return False
            # Resolve the broker's spelling first, then ensure it is watched -
            # the terminal only maintains a book for symbols in MarketWatch.
            name = self._engine._ready_symbol(symbol)
            if not mt5.market_book_add(name):
                code = mt5.last_error()
                raise MarketBookError(
                    f"market_book_add('{name}') failed: {code}. "
                    f"Book data is unavailable for this symbol - brokers often "
                    f"restrict it to exchange-traded instruments."
                )
            self._subscribed.add(name)
            return True

    def unsubscribe(self, symbol: str) -> bool:
        """Stop receiving book updates for a symbol."""
        mt5 = self._engine.mt5
        if mt5 is None:
            return False

        with self._lock:
            if symbol not in self._subscribed:
                return False
            released = mt5.market_book_release(symbol)
            self._subscribed.discard(symbol)
            return bool(released)

    def unsubscribe_all(self) -> List[str]:
        """Drop every subscription, e.g. before disconnecting."""
        released = []
        for symbol in self.subscribed:
            try:
                if self.unsubscribe(symbol):
                    released.append(symbol)
            except MarketBookError:
                continue
        return released

    def get(self, symbol: str) -> dict:
        """
        Current book for one symbol.

        Returns the top levels on each side alongside a ladder summary, which
        is the form that is actually useful for judging imbalance.
        """
        mt5 = self._engine.mt5
        if mt5 is None:
            raise MarketBookError("Not connected to the terminal")

        if symbol not in self._subscribed:
            self.subscribe(symbol)

        entries = mt5.market_book_get(symbol)
        if entries is None:
            code = mt5.last_error()
            raise MarketBookError(f"market_book_get('{symbol}') failed: {code}")
        if not entries:
            return {
                "symbol": symbol,
                "bids": [],
                "asks": [],
                "best_bid": None,
                "best_ask": None,
                "spread": None,
                "bid_volume": 0,
                "ask_volume": 0,
                "imbalance": None,
                "empty": True,
            }

        bids, asks = [], []
        for raw in entries:
            entry = serialize_namedtuple(raw)
            side = enums.BOOK_SIDE_NAMES.get(entry.get("type"), "unknown")
            if "buy" in side:
                bids.append(entry)
            else:
                asks.append(entry)

        # Best bid is the highest, best ask the lowest.
        bids.sort(key=lambda e: e.get("price", 0), reverse=True)
        asks.sort(key=lambda e: e.get("price", 0))

        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None
        bid_volume = sum(e.get("volume", 0) for e in bids)
        ask_volume = sum(e.get("volume", 0) for e in asks)
        total = bid_volume + ask_volume

        return {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": (best_ask - best_bid) if (best_bid and best_ask) else None,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "imbalance": round((bid_volume - ask_volume) / total, 4) if total else None,
            "levels": len(entries),
            "empty": False,
        }

    def get_many(self, symbols: List[str]) -> Dict[str, Optional[dict]]:
        """Books for several symbols, with failures isolated per symbol."""
        result: Dict[str, Optional[dict]] = {}
        for name in symbols:
            try:
                result[name] = self.get(name)
            except MarketBookError:
                result[name] = None
        return result

    def release_all_on_disconnect(self):
        """
        Clear local tracking after a disconnect.

        The terminal discards its books when the connection drops, so the
        local set must be emptied too or the next connect would believe it is
        still subscribed to symbols it is not.
        """
        with self._lock:
            self._subscribed.clear()
