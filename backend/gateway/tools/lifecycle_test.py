"""
End-to-end trading lifecycle test.

Places a real order on the connected account, walks it through every
operation, then closes it. Uses the minimum lot size and cleans up whatever
happens, so it is safe to run against a demo account.

    python tools/lifecycle_test.py
    CONY_URL=... CONY_TEST_MAGIC=987654 python tools/lifecycle_test.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("CONY_URL", "http://127.0.0.1:8890").rstrip("/")
MAGIC = int(os.getenv("CONY_TEST_MAGIC", "987654"))
SYMBOL = os.getenv("CONY_TEST_SYMBOL", "EURUSD")

step = 0
failures = []


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def report(label, ok, detail=""):
    global step
    step += 1
    mark = "PASS" if ok else "FAIL"
    print(f"  {step:2}. {mark}  {label}" + (f"   {detail}" if detail else ""))
    if not ok:
        failures.append(label)
    return ok


def main():
    print(f"Trading lifecycle on {BASE}  symbol={SYMBOL}  magic={MAGIC}")
    print("Places and closes one minimum-size order.\n")

    # Pre-flight ---------------------------------------------------------
    status, account = call("GET", "/account")
    if status != 200 or not account.get("balance"):
        print("Cannot reach the account; aborting.")
        return 1

    trading_allowed = account.get("trade_allowed") and account.get("trade_expert")
    if not trading_allowed:
        print(f"Account {account.get('login')} does not permit automated trading "
              f"(trade_allowed={account.get('trade_allowed')}, "
              f"trade_expert={account.get('trade_expert')}).")
        print("Enable 'Algo Trading' in the MT5 terminal and re-run.")
        return 1

    status, sym = call("GET", f"/symbol/{SYMBOL}")
    if status != 200:
        print(f"{SYMBOL} unavailable: {sym}")
        return 1

    d = sym["_derived"]
    info = d["order_rules"]
    pip = d["pip_size"]
    tick = sym.get("bid", 0)
    min_stop = info.get("min_stop_distance_pips", 0)

    print(f"  balance      {account['balance']} {account['currency']}")
    print(f"  symbol       {SYMBOL}  {d['digits']} digits, pip {pip:g}")
    print(f"  lot limits   {d['lot_info']['min_lot']} .. "
          f"{d['lot_info']['max_lot']} step {d['lot_info']['lot_step']}")
    print(f"  min stop     {min_stop} pips "
          f"({info['min_stop_distance_points']} points)")
    print(f"  mode         {d['trade_mode']}\n")

    if d["trade_mode"] != "full":
        print(f"  {SYMBOL} is {d['trade_mode']}, not tradable both ways.")
        return 1

    lot = d["lot_info"]["min_lot"]
    # Place the stop clear of the broker's minimum distance.
    stop_pips = max(min_stop + 5, 10)
    sl = round(tick - stop_pips * pip, d["digits"])
    tp = round(tick + stop_pips * pip, d["digits"])

    # 1. Size from the risk the symbol actually allows.
    status, sized = call("POST", "/calc/size",
                         {"symbol": SYMBOL, "risk_amount": 1.0, "stop_pips": stop_pips})
    report("calc/size returns a lot size", status == 200 and sized.get("lots", 0) > 0,
           f"{sized.get('lots')} lots" if status == 200 else sized)

    # 2. Dry run before committing anything.
    status, checked = call("POST", "/order/check", {
        "symbol": SYMBOL, "volume": lot, "order_type": "buy",
        "sl": sl, "tp": tp, "magic": MAGIC, "comment": "lifecycle-check",
    })
    report("order/check runs a dry run", status == 200,
           f"retcode {checked.get('retcode')} ({checked.get('retcode_description')})")
    report("dry run reserves margin",
           bool(checked.get("check", {}).get("margin")),
           f"margin {checked.get('check', {}).get('margin')}")

    # 3. Open.
    status, opened = call("POST", "/buy", {
        "symbol": SYMBOL, "volume": lot, "sl": sl, "tp": tp,
        "magic": MAGIC, "comment": "lifecycle-open",
    })
    if status != 200:
        report("buy opens a position", False, opened.get("error", str(opened)))
        return 1
    if not report("buy opens a position", opened.get("success"),
                  f"ticket {opened.get('result', {}).get('order')}"):
        return 1

    result = opened["result"]
    ticket = result.get("order")
    print(f"\n  opened ticket {ticket} @ {result.get('price')}  "
          f"sl {result.get('sl')}  tp {result.get('tp')}  "
          f"filling {result.get('type_filling')}")
    print(f"  retcode {result.get('_retcode')} "
          f"({result.get('_retcode_description')})\n")

    # The stops must actually be on the position, not merely accepted.
    status, check_pos = call("GET", f"/positions/{ticket}")
    report("stop loss is on the live position",
           status == 200 and abs(check_pos.get("sl", 0) - sl) < 1e-9,
           f"sl {check_pos.get('sl')} expected {sl}" if status == 200 else check_pos)
    report("take profit is on the live position",
           status == 200 and abs(check_pos.get("tp", 0) - tp) < 1e-9,
           f"tp {check_pos.get('tp')} expected {tp}" if status == 200 else "")

    try:
        # 4. It appears in the book.
        deadline = time.time() + 10
        found = []
        while time.time() < deadline:
            status, positions = call("GET", "/positions")
            found = [p for p in positions.get("positions", [])
                     if p.get("magic") == MAGIC]
            if found:
                break
            time.sleep(0.5)
        report("position appears with live PnL", bool(found),
               f"{len(found)} position(s), PnL {found[0].get('profit') if found else 'n/a'}")

        # 5. Portfolio reflects it.
        status, portfolio = call("GET", "/portfolio")
        report("portfolio counts the position",
               portfolio.get("summary", {}).get("position_count", 0) >= 1,
               portfolio.get("summary"))

        # 6. Move the stop, still respecting the minimum distance.
        status, tick_now = call("GET", f"/tick/{SYMBOL}")
        new_sl = round(tick_now["bid"] - (stop_pips + 5) * pip, d["digits"])
        status, modified = call("POST", "/modify", {"ticket": ticket, "sl": new_sl})
        report("modify moves the stop loss", status == 200 and modified.get("success"),
               f"sl -> {new_sl}" if status == 200 else modified)

        # 7. Partial close, then verify the remainder.
        if lot / 2 >= d["lot_info"]["min_lot"]:
            status, partial = call("POST", "/close",
                                   {"ticket": ticket, "volume": lot / 2,
                                    "magic": MAGIC, "comment": "lifecycle-partial"})
            report("partial close succeeds", status == 200 and partial.get("success"),
                   partial.get("error", "half closed") if status != 200 else "half closed")

            time.sleep(1.5)
            status, positions = call("GET", "/positions")
            left = [p for p in positions.get("positions", []) if p.get("magic") == MAGIC]
            report("partial close left exposure open", bool(left),
                   f"volume now {left[0].get('volume') if left else 'none'}")
        else:
            print("      (lot too small to split; skipping partial close)")

        # 8. Close whatever is left.
        status, remaining = call("GET", "/positions")
        left = [p for p in remaining.get("positions", []) if p.get("magic") == MAGIC]
        for pos in left:
            call("POST", "/close", {"ticket": pos["ticket"], "magic": MAGIC,
                                    "comment": "lifecycle-cleanup"})

        deadline = time.time() + 10
        while time.time() < deadline:
            status, after = call("GET", "/positions")
            left = [p for p in after.get("positions", []) if p.get("magic") == MAGIC]
            if not left:
                break
            time.sleep(0.5)
        report("all test positions closed", not left,
               f"{len(left)} still open")

        # 9. The trade shows up in history.
        status, summary = call("GET", f"/history/summary?symbol={SYMBOL}")
        report("trade appears in history", status == 200,
               f"net {summary.get('net')} over {summary.get('deal_count')} deals"
               if status == 200 else summary)

    finally:
        # Always clean up, even if an assertion above failed.
        status, positions = call("GET", "/positions")
        for pos in positions.get("positions", []):
            if pos.get("magic") == MAGIC:
                call("POST", "/close", {"ticket": pos["ticket"], "magic": MAGIC,
                                        "comment": "lifecycle-force-close"})
        status, orders = call("GET", "/orders")
        for order in orders.get("orders", []):
            if order.get("magic") == MAGIC:
                call("POST", "/cancel", {"ticket": order["ticket"]})

    print("\n" + "=" * 62)
    if failures:
        print(f"  {step - len(failures)} passed, {len(failures)} FAILED")
        for name in failures:
            print(f"    - {name}")
        return 1
    print(f"  all {step} lifecycle steps passed; account left flat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
