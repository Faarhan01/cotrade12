from __future__ import annotations



class SizingService:
    """Pass-through sizing helper kept for API boundary completeness."""
    def size(self, account, risk_pct, stop_pips, value_per_pip, max_lots):
        risk_amount = float(account.get("balance", 0.0)) * (risk_pct / 100.0)
        size_lots = risk_amount / (stop_pips * value_per_pip) if stop_pips else 0.0
        return {"lots": min(size_lots, max_lots), "risk_amount": risk_amount}
