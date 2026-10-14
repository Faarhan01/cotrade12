# TODO

Findings from an audit of the whole codebase, plus the site review. Ordered by
how much damage the item does if left alone.

Every item marked **reproduced** was confirmed by executing it, not by reading
it. Items marked *reported* came from a code review and are plausible but not
yet demonstrated; treat them as leads to confirm, not as established bugs.

---

## Fixed in this pass

Each of these was reproduced before the fix and re-checked after.

| | Problem | Evidence |
|---|---|---|
| ✅ | **Strategy updates silently lost.** `store.py` UPDATE branch had no `commit()`, so it sat in SQLite's implicit transaction and was rolled back at shutdown. It only *appeared* to work when a later call happened to commit on its behalf. | `in_transaction` was `True` after an UPDATE-only call; the new value was absent after reopen. Now `False` and present. |
| ✅ | **Trailing stop loosened instead of ratcheting.** `engine.py` re-derived the stop from each bar's own high/low, so a lower high moved it *backwards*. The comment claimed a ratchet the code did not implement. | Exited at **100.10** where a correct ratchet holds **100.50**. Now exits at 100.50. |
| ✅ | **Validator accepted a negative take-profit.** `tp and sl and tp <= 0 or sl and sl <= 0` parses as `(tp and sl and tp <= 0) or (sl and sl <= 0)`, so the `tp` check was gated on `sl` being present. A negative TP places the target *below* entry on a long and books the loss as a resolved "take_profit", corrupting the resolved ratio every verdict depends on. | `{"take_profit": -10, "time_stop_bars": 5}` returned `valid=True`. Now rejected. |
| ✅ | **Look-ahead bias in `rsi_reversion(confirm=N)`.** It inspected bars `i+1 … i+confirm` — bars after the one the engine fills on. Reachable from the public API, since `confirm` is advertised in `/research/catalogue`. | Entering at bar 15 read bar **16**. Now looks backward. |
| ✅ | **Hardcoded gateway port broke the research layer on any other port.** `tools/bot/datafeed.py` and `server/research.py` each carried a literal `127.0.0.1:8890`. Running with `CONY_PORT=9101` gave a gateway that could not reach its own research layer — every data-touching research route returned 500. | Reproduced on 9101: `500 Cannot reach the gateway at http://127.0.0.1:8890`. Now follows `CONY_HOST`/`CONY_PORT`. |
| ✅ | **No regression test for any of the above.** `verify.py` registered the research routes but never called one, which is exactly why the port bug survived. Added 11 end-to-end research checks — and verified they *fail* when the port bug is reintroduced. | 163 → **174 checks**. |
| ✅ | **The site had no price chart.** Added a dependency-free canvas renderer (`frontend/assets/js/lib/chart.js`) with a timeframe picker on `/ui/symbols`. | Geometry asserted headlessly across 6 instruments: range covers data, prices map the right way up, wicks inside the plot, bodies drawn, HiDPI scaling correct. |
| ✅ | **Chart timestamps rendered in UTC** while the rest of the site uses broker time. | 11:00 UTC → 17:00 at a +6h offset. |
| ✅ | Stale absolute path in `gateway/README.md` (pointed at the old `Custom-apps\peron`), and `frontend/README.md` still titled "peron frontend". | Fixed. |

---

## CRITICAL — not yet fixed

### 1. Naive local time fed to MT5, which reads naive input as UTC
*reported, high confidence*

`mt5_engine.py:553`, `validation.py:148`, `research.py:85`, `datafeed.py:126`

Every default window is computed from naive `datetime.now()` and passed to
`copy_rates_from` / `copy_rates_range`. On a machine not running UTC, every
default-window request is silently wrong by the UTC offset. The codebase
already knows this — `clock_offset()` exists and the SSE payload publishes
`time_source` — but the fix was never applied to the request builders.

**Why it is critical:** every backtest and every research result depends on
which bars come back. This is the same class of bug as the clock offset the
rest of the project goes to such lengths to handle.

### 2. `/history/summary` `net` omits commission
*reported*

`handlers.py:723` — `"net": round(realized + swaps, 2)`. Commission is computed
at line 711 and returned separately, but excluded from `net`. On a
commission-charging account `net` overstates realised P&L by the full fee.

### 3. Accepted-retcode logic implemented twice, and the copies disagree
*reported*

- `handlers.py:467` — `retcode_name(retcode) in ("Done", "Done Partial")`
- `mt5_engine.py:665` — `retcode in self._accepted_retcodes()` (numeric)

They diverge whenever `retcode_name()` cannot resolve a code: `enums.py`
returns `"Unknown (N)"` while `accepted_retcodes()` falls back to `(10009,
10010)`. In that state `POST /order` succeeds while `POST /order/check`
reports failure for the identical request — the pre-flight check disagrees with
the thing it is checking.

---

## MAJOR

### 4. `MarketBook` mixes resolved and unresolved symbol names
*reported*

`subscribe()` stores the broker-cased name; `get()`, `unsubscribe()` use the
raw one and pass it straight to `market_book_get()`. So
`GET /marketbook/eurusd` subscribes as `EURUSD` then queries `eurusd`, which
the terminal rejects, and unsubscribe returns `released: false` while leaving
the subscription open — a leak on the terminal side.

### 5. `ensure_connected()` races; double `mt5.initialize()`
*reported*

`connection.py:158` — the `if not self._connected` check is outside the lock.
Two request threads, or a request plus the reconnect loop, can both enter
`connect()`, and the second runs `mt5.initialize()` with no
already-initialised guard.

### 6. `connect()` clears the reconnect stop event
*reported*

`connection.py:104` — one flag serving two incompatible purposes. A request
that triggers `ensure_connected()` → `connect()` resurrects a reconnect loop
the operator just stopped.

### 7. `enums.load()` caches an import failure permanently
*reported*

`enums.py:24` sets `_loaded = True` **before** attempting the import. All
module-level `_value()` calls run at import time, before
`ensure_on_path(package_path)` can help — so an explicit `package_path` is
never honoured by the enum layer, and one transient `ImportError` pins every
enum to hardcoded integers for the process lifetime.

### 8. Backtest cache returns a silently truncated bar set
*reported*

`datafeed.py:156` — `if len(local) >= min(count, 100): return local`. With
`count=5000` and 120 cached bars, that returns 120. Every t-statistic, verdict
and drawdown is then computed on 2% of the requested sample with nothing
telling the caller. The module docstring also promises a staleness check that
does not exist.

### 9. `breakeven_after_pips` is documented, persisted and advertised, but never implemented
*reported*

Declared on `ExitRule`, round-tripped through `to_dict`/`from_dict`, written
to the database, and offered to agents at `/research/catalogue` as *"move the
stop to entry after this much profit"*. `engine.run` never reads it. A strategy
configured with it backtests as if it did not exist, then behaves differently
live — which is the worst kind of gap, because the backtest is supposed to be
the thing that predicts the live result.

### 10. `Strategy.spread_pips` is always overwritten before use
*reported*

`api.py:355` and `runner.py:138` both clobber the field with the live spread,
so the persisted `spread_pips` column is write-only. A strategy with a
deliberately wider cost assumption is silently tested at the live spread.

### 11. `warmup_only` is a `bool` used as a slice count
*reported*

`api.py:185` — `values[-warmup_only:]` with `warmup_only=True` returns **one**
element, because `True == 1`. Latent: the route never passes the flag.

### 12. `date_range` compares tz-aware with tz-naive datetimes
*reported*

`validation.py:148` — a `"...Z"` query yields an aware datetime while the
default `end` is naive, so `GET /candles/EURUSD?from=2026-01-01T00:00:00Z`
raises `TypeError` → HTTP 500 instead of returning data.

### 13. `Save_strategy` TOCTOU; `sync_*` not atomic
*reported*

`store.py:85` selects, releases the lock, then re-acquires at line 99. Two
concurrent writers both see no row and both `INSERT`; the second fails on
`UNIQUE(name)`. Same select-then-write shape in `sync_indicators` and
`sync_patterns` commits per row, leaving a partial sync on failure.

### 14. `LiveTrader.open_positions()` sends an unquoted symbol
*reported*

`live.py:66` — three other methods in the same class do `.replace(' ', '%20')`.
For the project's own primary test instrument, `"Step Index 200"`, the raw
spaces break the query string.

---

## MINOR

### 15. Pip/point conversion implemented in five places
`mt5_engine.py:304` is canonical. But `dashboard/views.py:141` falls back to
`point * 10` — the assumption the engine docstring explicitly warns is wrong
for non-5/3-digit instruments — and `datafeed.py:81` falls back to
`pip_size = 1`, which is wrong by 10×. **The dashboard can display a different
pip size than the engine used to price an order on the same symbol.**

Also: `datafeed.py` uses `quote(symbol)` (default `safe="/"`) while
`research.py` uses `quote(symbol, safe="")`. Two escaping policies for one
operation.

### 16. `momentum_entry` window boundaries disagree
`strategies.py:246` — the window is `lookback` bars but the baseline is
`bars[i - lookback]`, one bar outside it. `net` measures a 4-bar move while
`ups` counts 3. Copied identically into `scalp_lab.py`.

### 17. `ma_cross` negative-index wraparound
`strategies.py:194` — `Context.value` guards `i < len(series)` but not
`i < 0`, so `confirm_bars > i` reads from the *end* of the sample. Negative
indexing does not raise, so the engine's `except IndexError` cannot catch it.

### 18. Trailing-stop / time-exit reads one bar past the window
`engine.py:309` — after the inner loop exits, `j == limit` and
`bars[min(j, ...)]` reads one bar beyond the holding window. Relatedly
`bars_held` for a time exit is `max_bars + 1`, not `time_stop_bars`.

### 19. Baseline mean uses a mismatched denominator
`patternchecker.py:133` — the numerator filters on `horizon in m`, the
denominator does not, so any zero-close bar biases the baseline that every
verdict is measured against.

### 20. Bonferroni threshold uses a normal quantile, not a t quantile
`patternchecker.py:204` — `NormalDist().inv_cdf` where the docstring promises a
t quantile. With 14 patterns it reports 2.91; the true t critical value is
higher, so the correction is slightly too lenient. `cost_marginal` is also
graded against `SIGNIFICANT_T` (2.0) rather than the corrected threshold, so a
pattern can be "significant" and never "cost-marginal".

### 21. Sorting by |t| surfaces the biggest loser first
`runner.py:185`, `api.py:450` — a strategy that reliably loses has |t| as large
as one that reliably wins. `api.sweep` returns that as `"best"` while its own
documentation says the verdict is the only field that decides.

### 22. Hardcoded `run_id` on every API backtest
`api.py:378` — `"api"`, so every report written through
`POST /research/backtest` shares one run id, defeating the grouping
`idx_reports_run` exists for.

### 23. `CONY_LOG_LEVEL` and `CONY_LOG_FILE` silently do nothing
`logger.py:47` — `get_logger` calls `setup_logging()` with no arguments, so
the defaults always win. An operator who sets `CONY_LOG_FILE` to capture a
session gets no file. **Both are documented in the root README.**

### 24. Dead code

| Location | Item |
|---|---|
| `engine.py:180` | `MIN_EDGE_VS_COST` — never referenced |
| `runner.py:97` | `_pips()` — never called; re-implemented inline at 244 |
| `datafeed.py:94` | `value_per_point()`, `money()` — never called |
| `patternchecker.py:368` | `check_and_store()` — never called; `main()` duplicates it |
| `store.py` | `best_reports()`, `pattern_frequency()`, `bar_range()`, `vacuum()` — never called |
| `schema.py:119` | `hit_context` table — never read or written |
| `connection.py:166` | `mark_dropped()` — never called, despite the contract |
| `patterns.py:109` | `"bullish" if b.bullish else "bullish"` — both branches identical |
| 7 modules | unused imports (`Dict`, `time`, `MT5Error`, `timezone`, `json`, …) |

### 25. `runner.cmd_*` leak the Store on exception
No `try/finally`; any `GatewayError` leaves the SQLite connection open.

---

## Site

### 26. Depth of market is unreachable from the UI
The dashboard never calls `/marketbook/*`. The routes exist and the client is
verified end-to-end, so this is frontend work. **Caveat:** the broker returned
`MarketBookUnavailable` when checked on this account, so confirm DOM is
actually served before building a panel.

### 27. No trading controls
The UI is read-only. `/order/check`, `/calc/size` and `/calc/profit` are all
wrapped and routed but unreachable from a page. That is defensible — live
buttons on a trading dashboard deserve their own decision — but it should be
a decision, not an omission.

### 28. Two more pages worth having
- **Positions/orders history** with filters — currently only the last 25 deals
  render
- **Account history / equity curve** — `/history/summary` is unrouted in the UI

### 29. Accessibility gaps
- The watchlist flash is the only motion and respects `prefers-reduced-motion`
  ✅, but the chart does not
- Tables have no `<caption>` or `aria-label`
- The timeframe buttons use `aria-pressed` ✅ but the group has no visible
  label
- No keyboard navigation on the symbol list (it is `<button>`s, so this works —
  worth keeping in mind)

---

## Documentation

### 30. `api-reference.md` covers 23 of 61 routes
The entire `/research` API (14), market book (5), web UI (3), and 16 single
endpoints are undocumented. Everything works; the document is just stale. The
live list is always at `GET /routes`.

### 31. Project name has drifted from the code
`backend/data/peron.db`, `PERON_PACKAGE_PATH`, the database filename, and the
docs all predate the rename to cotrade. Pick one convention and apply it.

---

## Infrastructure

### 32. No CI
`verify.py` is run by hand. It needs a live terminal, so it cannot run on a
stock runner, but the pure-logic parts (knowledgebase, engine, store) could —
and would catch most of this list before a human ever runs it.

### 33. No requirements file
Only `numpy`, which `MetaTrader5` pulls in. Nothing to pin *yet*.

### 34. Not load-tested
The gateway is threaded and SSE clients hold threads for their lifetime.
Bounded, but unproven under many concurrent clients.

### 35. The gateway has not been run against a live (non-demo) account
Everything here has been exercised against Deriv-Demo only.

---

## Suggested order

1. **#1 naive UTC** — it silently corrupts which bars every result is computed
   from. Highest blast radius.
2. **#3 retcode divergence** — the pre-flight check and the order disagree, so
   the safety net is unreliable.
3. **#9 `breakeven_after_pips`** — advertised to agents but does nothing.
4. **#15 pip conversion** — the dashboard and engine can disagree about the
   same instrument.
5. **#2, #4, #8** — each is a wrong number a user can act on.
6. **#30 documentation** — mechanical, and the gap actively misleads agents.
7. Everything else.

Items 1–4 each deserve a regression check before the fix, the way
`analyse_follow_through` got one when its own methodology turned out to be
wrong.