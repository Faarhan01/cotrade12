# Step Index — Scalping Strategy

**Status: UNVALIDATED. No edge demonstrated. Do not trade live.**

The rule documented here was the best-performing of 18 tested, but the result is
statistically indistinguishable from random. This file records the strategy and
the evidence honestly so it can be re-tested rather than re-invented.

- Instrument: `Step Index 200` (Deriv synthetic index)
- Data source: cony gateway, M1 candles, 7 days
- Test harness: `gateway/tools/scalp_lab.py`
- Verdict: break-even after costs, as random-walk maths predicts

---

## 1. The rule

**Fade the last 10 minutes, take 10 points, stop 10 points.**

On each M1 bar close:

| Condition | Action |
|---|---|
| Net move over last 10 bars is **up** AND ≥5 of those bars were up | **SELL** (fade the rise) |
| Net move over last 10 bars is **down** AND ≤1 of those bars were up | **BUY** (fade the fall) |
| Anything else | No trade |

**Exit**, whichever comes first:

| Parameter | Value |
|---|---|
| Take profit | 10 points (10.0 pips) |
| Stop loss | 10 points (10.0 pips) |
| Time stop | 20 bars (20 minutes) |

Spread of 0.2 is charged on entry and exit, so each round trip costs 0.4 points.

---

## 2. Instrument facts

Read from the gateway, not assumed:

```
GET /symbol/Step%20Index%20200
```

| Property | Value |
|---|---|
| Digits | 1 |
| Point | 0.1 |
| Pip | 1.0 |
| Spread | 0.2 (exactly one price step) |
| Contract size | 10 |
| Pip value / lot | 10 USD |
| Value per point | $1.00 per 1.00 lot, $0.01 per 0.01 lot |
| Min stop distance | 1.1 pips |
| Lot limits | 0.1 – 20.0, step 0.01 |
| Trade mode | full |

`min_lot` is **0.1**, not 0.01. The 0.01-lot figures elsewhere in this document
are per-unit normalisations; a real order must use ≥ 0.1 lots, which is $0.10 per
point.

---

## 3. Result over 7 days (10,000 bars)

```
rule                             trades    win%   tp/sl%  timed%     PF   net pts  maxDD
fade(10) TP10/SL10                  400   52.0%    50.8%   68.0%   1.03     +36.0   117.2
momentum(5) TP10/SL10               494   49.8%    51.4%   71.7%   1.01      +9.2   170.8
momentum(20) TP10/SL20              257   48.2%    92.5%   84.4%   0.92     -62.0   139.6
breakout(20) TP20/SL10              347   48.1%     0.0%   84.1%   0.77    -252.0   279.6
fade(5) TP10/SL10                   497   47.9%    43.1%   71.0%   0.78    -356.4   401.2
```

### Reading the win-rate columns

Two rates are reported because they answer different questions:

| Column | Meaning |
|---|---|
| `win%` | Every trade, including those closed on the time stop |
| `tp/sl%` | Only trades that actually reached +TP or −SL |
| `timed%` | Share that closed on the time stop without reaching either |

`tp/sl%` is the column that reflects the rule itself. `win%` is dominated by
noise whenever most trades never resolve. Reporting only `win%` makes a
break-even strategy look skillful.

**For fade(10): overall 52.0%, but 50.8% among trades that resolved.** The rule
is a coin flip precisely where it matters.

### Take-profit reachability

`TP20/SL10` rules show `tp/sl% = 0.0%` — a 20-point take profit is **never**
reached within the 20-bar time stop. Only ~16% of those trades ever resolve, so
those configurations are untestable as written.

`TP10/SL20` rules resolve 92–95% of the time, and every one of them loses money.

### Where the profit came from (fade(10), earlier run on same window)

| Exit | Trades | Points | Avg/trade |
|---|---:|---:|---:|
| Hit take profit | 64 | +640.0 | +10.000 |
| Hit stop loss | 63 | −630.0 | −10.000 |
| **Time stop (hit neither)** | **273** | **+12.8** | **+0.047** |
| **Net after spread** | **400** | **+22.8** | |

- Take-profits and stop-losses cancel almost exactly: **+640 vs −630**.
- **68% of trades never reached ±10 points.** They closed on the time stop at an
  arbitrary price and contributed +12.8 points total.
- The 50.0% win rate comes from those wandering trades finishing up or down by
  chance, not from the TP/SL logic working.
- Average win +5.92, average loss −5.81 — effectively identical.

### Cost analysis

| | Points |
|---|---:|
| Gross before spread | ≈ +183 |
| Spread cost (400 trades × 0.4) | −160 |
| **Net** | **+22.8** |

The strategy earns roughly one seventh of what it pays in spread.

---

## 4. Why this is not an edge

### 4.1 Statistical significance

Gross t-statistic: **+0.37**. A real edge needs |t| > 2. At 400 trades averaging
±10 point swings, the standard error is far larger than the observed edge.

### 4.2 The sign flips on a one-integer change

Relaxing the entry condition from `up ≤ 1` to `up ≤ 2` turns **+22.8 points into
−126.8 points**. Real strategies do not invert from a trivial parameter tweak;
noise does.

### 4.3 The underlying process is a random walk

Measured over 19,309 H1 bars (804 days):

| Property | Value |
|---|---|
| Direction | P(up) = 0.5003 |
| z-statistic | +0.09 |
| Run-length distribution | matches geometric (χ² = 7.5, critical 12.6) |
| Volatility clustering | none (all autocorrelations \|z\| < 1.25) |
| Mean reversion after big moves | none (t-stats < 1.7) |
| Variance ratio | ≈ 1 at short horizons |

There are bursts — a 13-move run was observed — but they occur at exactly the
rate randomness predicts. Any strategy requires >50% win rate to overcome a
1-step spread, and this process delivers exactly 50%.

### 4.4 Sibling instruments behave the same

Tested over 774 days each:

| Symbol | P(up) | z | Verdict |
|---|---|---|---|
| Step Index 200 | 0.5003 | +0.09 | no bias |
| Skew Step Index 4 Up | 0.5041 | +1.13 | no bias |
| Skew Step Index 5 Up | 0.5080 | +2.19 | does not survive Bonferroni correction |

The documented 80/20 and 90/20 skews are absent from this account's data.

### 4.5 The variants are independent of each other

Correlating price **changes** across all five Step Index variants over 8,000
common M1 bars:

| | Index | 200 | 300 | 400 | 500 |
|---|---|---|---|---|---|
| **Index** | 1.0000 | +0.0133 | −0.0174 | −0.0094 | +0.0169 |
| **200** | | 1.0000 | −0.0021 | +0.0041 | +0.0140 |
| **300** | | | 1.0000 | +0.0109 | +0.0011 |
| **400** | | | | 1.0000 | +0.0255 |

All within ±0.03. No shared driver, and no lead-lag relationship at 1–30
minutes (all |z| < 1.5). Trading one variant tells you nothing about another.

> **Caution — a trap worth recording.** Correlating raw price *levels* gives
> −0.8620 between Index and Index 200, which looks like a major discovery. It is
> entirely spurious: both series are non-stationary random walks, and levels of
> unrelated walks drift into spurious alignment. Always correlate differences.

### 4.6 No time-of-day effect

Tested all 24 UTC hours over 7 days:

- **Zero hours** reached |z| > 2 for directional drift (Bonferroni threshold
  would be 3.08).
- Volatility *does* vary: quietest 03:00 UTC (mean |move| 1.489), busiest
  19:00 UTC (2.011) — a **1.35× ratio**.

Higher volatility means more bars reach their take-profit, but with no
directional edge it does not create profit. Filtering to busy or quiet hours
produced no significant result (best: quiet hours TP8/SL8 at +61.2 points,
t = +0.87).

---

## 5. What the other 17 rules did

Every other rule lost money. Representative rows:

| Rule | Trades | Win % | PF | Net pts |
|---|---:|---:|---:|---:|
| momentum(3) TP10/SL10 | 478 | 46.4% | 0.90 | −148.4 |
| momentum(5) TP10/SL10 | 493 | 49.1% | 0.98 | −28.4 |
| momentum(10) TP10/SL10 | 397 | 44.8% | 0.83 | −216.8 |
| breakout(20) TP20/SL10 | 348 | 44.5% | 0.75 | −268.0 |
| fade(5) TP10/SL10 | 497 | 46.9% | 0.76 | −385.6 |
| always-long TP20/SL10 | 487 | 45.6% | 0.86 | −205.6 |

17 of 18 lost. The one that didn't is not meaningfully different from the rest.

---

## 6. Reproducing this

```powershell
cd C:\Users\faarh\Workspaces\Custom-apps\peron\backend\gateway
python -m deamon            # must be running on :8890

python tools\scalp_lab.py "Step Index 200"
```

Adjustable via environment:

| Variable | Default | Meaning |
|---|---|---|
| `CONY_URL` | `http://127.0.0.1:8890` | Gateway base URL |
| `SCALP_DAYS` | `7` | Window in days |

To re-test on fresh data, change `SCALP_DAYS` and run again on a different
`from`/`to` window. If the strategy is real, it should hold on unseen data. If it
is noise, the sign and magnitude will move around.

---

## 7. Caveats on the backtest itself

The harness is optimistic. Treat these numbers as an upper bound:

- **Stops fill at the stop price, not through it.** On a 1-second synthetic with
  0.2 spread, real slippage past a stop is likely.
- **No latency modelled.** Entries are taken at the close of the signal bar with
  no execution delay.
- **Same-bar TP/SL ambiguity.** If a bar's high and low span both levels, the
  result depends on check order; this harness assumes the favourable side.
- **Overlapping signals skipped.** After a trade closes, the next bar is
  re-evaluated, so some signals are never taken.

Any of these would make live results worse, not better.

---

## 8. Recommendation

**Do not trade this live.** The instrument has no exploitable structure at the
precision tested, and the spread equals one full price step.

Where Step Index *is* useful, because the correct answer is knowable in advance:

- **Latency and execution testing** — you know the true price path, so any fill
  discrepancy is yours or the broker's, not market noise
- **Fill-behaviour validation** — it is what exposed that this broker rejects
  `RETURN` filling with retcode 10030 and accepts only FOK
- **Cost-model verification** — spread is pinned at exactly one step, so
  assumptions can be checked precisely
- **Gateway self-tests** — symbol resolution, serialization and market-watch
  selection all verify cleanly here

If the goal is a live strategy, real market data on this same account (forex
majors, available via `GET /symbols`) has genuine structure that would show
measurable autocorrelation where Step Index shows none.

---

## 9. Change log

| Date | Change |
|---|---|
| 2026-10-14 | Initial document. Rule found via 18-strategy grid over 7 days. Flagged unvalidated. |
| 2026-10-14 | Added dual win-rate reporting (`win%` vs `tp/sl%`) after the single headline rate proved misleading. |
| 2026-10-14 | Added time-of-day analysis (§4.6), cross-variant independence (§4.5), and volatility-hour scalping. All negative. |
| 2026-10-14 | Recorded the spurious price-level correlation trap in §4.5. |
