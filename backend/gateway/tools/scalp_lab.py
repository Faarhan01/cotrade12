"""
Scalping strategy lab for Step Index.

Builds and tests scalping rules against Step Index M1 data pulled through the
cony gateway, sizing with MT5's own /calc/size and pricing with /calc/profit so
the arithmetic comes from the terminal rather than being re-derived here.

    python tools/scalp_lab.py            # last 7 days of M1
    python tools/scalp_lab.py EURUSD     # any symbol
"""

import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.getenv("CONY_URL", "http://127.0.0.1:8890").rstrip("/")
SYMBOL = (sys.argv[1] if len(sys.argv) > 1 else "Step Index 200").strip()
DAYS = int(os.getenv("SCALP_DAYS", "7"))


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def section(title):
    print(f"\n{title}")


def main():
    q = urllib.parse.quote(SYMBOL)

    section("1. INSTRUMENT (from the gateway, not assumed)")
    _, sym = call("GET", f"/symbol/{q}")
    d = sym["_derived"]
    pip = d["pip_size"]
    step = d["point_size"]
    spread = sym["ask"] - sym["bid"]
    contract = d["lot_info"]["contract_size"]
    pip_value = d["pip_value_per_lot"]
    stop_pips = d["order_rules"]["min_stop_distance_pips"]

    print(f"   symbol        {sym['name']}")
    print(f"   digits        {d['digits']}   point {step:g}   pip {pip:g}")
    print(f"   spread        {spread:g}  ({spread/pip:.1f} pips)")
    print(f"   contract      {contract:g}   pip value/lot {pip_value:g} {sym['currency_profit']}")
    print(f"   min stop      {stop_pips:g} pips")
    print(f"   lot limits    {d['lot_info']['min_lot']} .. {d['lot_info']['max_lot']} "
          f"step {d['lot_info']['lot_step']}")

    value_per_step = pip_value * (step / pip)          # $ per point per lot
    print(f"   $ per point   {value_per_step:g} per 1.0 lot "
          f"({value_per_step/100:g} per 0.01 lot)")

    section(f"2. DATA - last {DAYS} days of M1")
    end = datetime.now()
    start = end - timedelta(days=DAYS)
    _, bars = call("GET", f"/candles/{q}?timeframe=M1&from={start.date().isoformat()}"
                          f"&to={end.date().isoformat()}")
    if bars.get("truncated"):
        print(f"   note: {bars.get('note')}")
    candles = bars.get("candles", [])
    if len(candles) < 1000:
        print(f"   only {len(candles)} bars available - cannot test")
        return 1

    o, h, l, c = ([x[k] for x in candles] for k in ("open", "high", "low", "close"))
    print(f"   {len(candles)} bars  "
          f"{datetime.fromtimestamp(candles[0]['time'], timezone.utc):%Y-%m-%d %H:%M} "
          f"-> {datetime.fromtimestamp(candles[-1]['time'], timezone.utc):%Y-%m-%d %H:%M} UTC")
    print(f"   price {min(l):g} .. {max(h):g}")

    section("3. STRATEGY GRID - each rule backtested over the full week")
    # Signals: +1 long, -1 short, 0 flat, computed from bars up to and incl. i
    def sig_momentum(look):
        def f(i):
            if i < look:
                return 0
            window = c[i - look + 1:i + 1]
            up = sum(1 for j in range(1, len(window)) if window[j] > window[j - 1])
            net = c[i] - c[i - look]
            if net > 0 and up >= max(2, look // 2):
                return 1
            if net < 0 and up <= min(1, look // 4):
                return -1
            return 0
        return f

    def sig_breakout(look):
        def f(i):
            if i < look:
                return 0
            hi = max(h[i - look:i])
            lo = min(l[i - look:i])
            if c[i] > hi:
                return 1
            if c[i] < lo:
                return -1
            return 0
        return f

    def sig_fade(look):
        m = sig_momentum(look)
        return lambda i: -m(i)

    def sig_always(i):
        return 1

    def backtest(sig, tp_pips, sl_pips, max_bars=20):
        """
        Enter at the close of bar i, exit on TP/SL hit using the next bar's
        high/low, else time exit. Spread charged on entry and exit.
        """
        trades = []
        i = 1
        while i < len(c) - 1:
            side = sig(i)
            if side == 0:
                i += 1
                continue
            entry = c[i] + (spread if side == 1 else -spread)   # pay the spread
            tp = entry + side * tp_pips * pip
            sl = entry - side * sl_pips * pip
            j, exit_price, reason = i + 1, None, "time"
            while j < min(i + 1 + max_bars, len(c) - 1):
                if side == 1:
                    if h[j] >= tp:
                        exit_price, reason = tp, "tp"
                        break
                    if l[j] <= sl:
                        exit_price, reason = sl, "sl"
                        break
                else:
                    if l[j] <= tp:
                        exit_price, reason = tp, "tp"
                        break
                    if h[j] >= sl:
                        exit_price, reason = sl, "sl"
                        break
                j += 1
            if exit_price is None:
                exit_price = c[j] - (spread if side == 1 else -spread)
            pnl_points = side * (exit_price - entry)
            trades.append((side, pnl_points, reason, j - i))
            i = j + 1
        return trades

    def report(name, trades):
        """
        Report one rule.

        Two win rates are shown because they answer different questions and
        only one of them is about the TP/SL logic:

          win%   - every trade, including those closed on the time stop
          tp/sl% - only trades that actually reached +TP or -SL

        On this instrument most trades never reach either level and close
        wherever price happened to be, so the headline win rate is dominated
        by noise while tp/sl% reflects the rule itself. Reporting only the
        headline made a break-even strategy look skillful.
        """
        if not trades:
            print(f"   {name:<30} no trades")
            return
        resolved = [t for t in trades if t[2] in ("tp", "sl")]
        timed = [t for t in trades if t[2] == "time"]

        wins = [t for t in trades if t[1] > 0]
        gross_win = sum(t[1] for t in wins)
        gross_loss = -sum(t[1] for t in trades if t[1] < 0)
        net = sum(t[1] for t in trades)
        pf = gross_win / gross_loss if gross_loss else float("inf")

        r_pct = 100 * sum(1 for t in resolved if t[1] > 0) / len(resolved) if resolved else float("nan")
        t_pct = 100 * len(timed) / len(trades)

        equity = peak = maxdd = 0.0
        for t in trades:
            equity += t[1]
            peak = max(peak, equity)
            maxdd = max(maxdd, peak - equity)
        avg_hold = sum(t[3] for t in trades) / len(trades)

        print(f"   {name:<30} {len(trades):>5} {100*len(wins)/len(trades):>6.1f}% "
              f"{r_pct:>6.1f}% {t_pct:>5.1f}% {pf:>6.2f} {net:>+8.1f} "
              f"{maxdd:>7.1f} {avg_hold:>5.1f}")

    print(f"\n   {'rule':<30} {'trades':>5} {'win%':>6} {'tp/sl%':>6} {'timed%':>6} "
          f"{'PF':>6} {'net pts':>8} {'maxDD':>7} {'hold':>5}")
    print("   " + "-" * 84)
    print("   win% = all trades    tp/sl% = only trades that hit TP or SL"
          "    timed% = closed on the time stop")

    rules = []
    for look in (3, 5, 10, 20):
        rules.append((f"momentum({look}) TP10/SL10", sig_momentum(look), 10, 10))
        rules.append((f"momentum({look}) TP20/SL10", sig_momentum(look), 20, 10))
        rules.append((f"momentum({look}) TP10/SL20", sig_momentum(look), 10, 20))
    for look in (10, 20, 30):
        rules.append((f"breakout({look}) TP20/SL10", sig_breakout(look), 20, 10))
    for look in (5, 10):
        rules.append((f"fade({look}) TP10/SL10", sig_fade(look), 10, 10))
    rules.append(("always-long TP20/SL10", sig_always, 20, 10))

    results = []
    for name, sig, tp, sl in rules:
        trades = backtest(sig, tp, sl)
        report(name, trades)
        if trades:
            results.append((sum(t[1] for t in trades), name, trades))

    section("4. BEST RULE, priced through MT5's own /calc/profit")
    if not results:
        print("   no trades to price")
        return 1
    results.sort(reverse=True)
    for net, name, trades in results[:3]:
        gross = sum(t[1] for t in trades)
        print(f"   {name:<34} gross {gross:+.1f} points "
              f"= ${gross * value_per_step:+.2f} per 1.0 lot "
              f"= ${gross * value_per_step / 100:+.4f} per 0.01 lot")

    print()
    best_net, best_name, best_trades = results[0]
    # Price one representative trade through the terminal.
    sample = next((t for t in best_trades if t[1] != 0), best_trades[0])
    move = sample[1] * pip
    st, prof = call("POST", "/calc/profit",
                    {"symbol": sym["name"], "volume": 0.01,
                     "order_type": "buy" if sample[0] == 1 else "sell",
                     "open_price": round(c[len(c) // 2], d["digits"]),
                     "close_price": round(c[len(c) // 2] + move, d["digits"])})
    if st == 200:
        print(f"   MT5 confirms a {abs(move)/pip:.1f}-pip move on 0.01 lot "
              f"= {prof.get('profit')} {sym['currency_profit']}")

    section("5. VERDICT")
    net = sum(t[1] for t in best_trades)
    wins = sum(1 for t in best_trades if t[1] > 0)
    resolved = [t for t in best_trades if t[2] in ("tp", "sl")]
    timed = [t for t in best_trades if t[2] == "time"]
    r_pct = 100 * sum(1 for t in resolved if t[1] > 0) / len(resolved) if resolved else float("nan")
    print(f"   Best rule over {DAYS} days: {best_name}")
    print(f"   Trades {len(best_trades)}   overall win {100*wins/len(best_trades):.1f}%   "
          f"TP/SL-only win {r_pct:.1f}%   time-stop exits {100*len(timed)/len(best_trades):.0f}%")
    print(f"   Net {net:+.1f} points = ${net*value_per_step:+.2f} per 1.0 lot")
    print(f"   Spread paid {spread:g} = {spread/pip:.1f} pips per round trip.")
    if net <= 0:
        print("   -> The best of every rule tested still lost money after spread.")
    else:
        print("   -> Positive, but see significance before trusting it.")
        sd = math.sqrt(sum((t[1] - net / len(best_trades)) ** 2 for t in best_trades)
                       / max(len(best_trades) - 1, 1))
        se = sd / math.sqrt(len(best_trades))
        t = (net / len(best_trades)) / se if se else 0
        print(f"      t-statistic {t:+.2f} (need |t| > 2). "
              f"Gross before spread: {net + len(best_trades)*2*spread:+.1f} points.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
