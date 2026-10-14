# cotrade

A MetaTrader 5 gateway and web control panel. Python drives the terminal
through the official `MetaTrader5` package and exposes it three ways: a JSON
API for agents, a research API for strategy work, and a browser dashboard for
people.

Everything is local. The gateway binds `127.0.0.1` only.

---

## Requirements

| | |
|---|---|
| **Python** | **3.11, specifically.** The `MetaTrader5` package ships `_core.cp311-win_amd64.pyd` — a compiled extension bound to CPython 3.11's ABI. It will not import on 3.10 or 3.12. |
| **MetaTrader 5** | Installed, and **logged in**. The gateway attaches to the running terminal; it does not launch it. |
| **Dependencies** | `numpy` only, which the `MetaTrader5` package pulls in itself. |

There is no `requirements.txt` yet because there is nothing else to pin. If
that changes, add one here.

### Install

```powershell
pip install MetaTrader5 numpy
```

If the package is **not** importable — a private copy, or a virtualenv that
cannot see it — point the gateway at the directory that contains a
`MetaTrader5\` folder:

```powershell
$env:CONY_MT5_PACKAGE = "C:\path\to\metatrader5_package"
```

`PERON_PACKAGE_PATH` is still honoured as a legacy alias.

The gateway searches, in order: that variable, then `../metatrader5_package`
and two levels up from the gateway, then whatever is already importable. So
dropping the package beside `backend/` just works.

---

## Setup

There is nothing to build and nothing to compile. Clone, install, run.

```powershell
pip install MetaTrader5 numpy

# start MetaTrader 5 and log in first

# Run directly from repository root:
python run.py
```

You should see:

```
listening      http://0.0.0.0:3000
package path   ...
Connected to MT5 terminal (build 6235, account 29974125)
```

Then open **http://localhost:3000/**.

Or specify a custom port:
```powershell
python run.py server --port 8890
```

---

## The site

| URL | What it is |
|---|---|
| <http://127.0.0.1:8890/> | Account overview — balance, equity, positions, orders, deals, live Market Watch |
| <http://127.0.0.1:8890/ui/symbols> | Instrument browser with full derived spec |
| <http://127.0.0.1:8890/ui/research> | Pattern scans, strategy validation, backtests |

Plain HTML, CSS and JavaScript. No npm, no build step, no CDN, no web fonts —
it renders with no internet access, which is the normal condition for a trading
desk.

Prices update over SSE (`/stream/portfolio`, `/stream/ticks`), not polling, so
a quiet account costs nothing.

`frontend/` is entirely static. Edit a page, partial, stylesheet or script and
reload the browser — no restart. Only `backend/dashboard/*.py` needs the daemon
restarted.

---

## Layout

```
cotrade/
├── backend/
│   ├── gateway/          the MT5 bridge and HTTP server
│   │   ├── cony/         engine — no HTTP, no server
│   │   ├── server/       HTTP layer
│   │   └── deamon/       entry point, sockets, SSE transport
│   ├── dashboard/        serves the web UI; the only Python the frontend needs
│   ├── knowledgebase/    indicators, patterns, strategies — pure logic, no I/O
│   ├── database/         SQLite store
│   ├── tools/bot/        backtesting, pattern checking, CLI
│   ├── data/             peron.db
│   └── docs/             strategy findings
└── frontend/
    ├── pages/            one .html per screen
    ├── partials/         shared header, footer, head
    └── assets/           css/ and js/, split into shared lib and per-page
```

The gateway is three layers with dependencies pointing one way only:
`deamon → server → cony`. The engine never knows HTTP exists.

`backend/dashboard/` and `backend/knowledgebase/` are **optional extensions**.
They register their routes on startup and log a warning if they cannot load;
a stripped-down gateway still serves the full JSON API.

---

## Verifying an install

```powershell
cd backend\gateway
python tools\verify.py          # 163 endpoint and error-path checks
python tools\audit_coverage.py  # MetaTrader5 package coverage
python tools\audit_hardcode.py  # no baked-in paths, ports or constants
```

`verify.py` needs the daemon running and MetaTrader 5 connected. It checks
error paths, not just happy ones: unknown symbols return 404 rather than 500,
window sizes are bounded, position sizing does not lose a step to float error,
and static-asset traversal attempts are refused.

---

## Configuration

All optional. Every one has a working default.

| Variable | Default | Purpose |
|---|---|---|
| `CONY_HOST` | `127.0.0.1` | Bind address. Change with care — the API places real orders. |
| `CONY_PORT` | `8890` | Port. |
| `CONY_MT5_PACKAGE` | auto-detected | Directory containing `MetaTrader5\`. |
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | — | Login details, if not already stored in the terminal. |
| `MT5_PATH` | — | Path to `terminal64.exe`, if not in the default location. |
| `MT5_TIMEOUT` | `60000` | Milliseconds to wait for the terminal. |
| `CONY_LOG_LEVEL` | `INFO` | Set `DEBUG` for verbose logging. |
| `CONY_LOG_FILE` | — | Also write logs to a file. |
| `CONY_AUTO_CONNECT` | `true` | Attach to the terminal on startup. |
| `CONY_AUTO_RECONNECT` | `true` | Re-attach if the connection drops. |
| `CONY_RECONNECT_INTERVAL` | `20` | Seconds between retries. |
| `CONY_SYMBOL_CACHE_TTL` | `300` | Seconds to cache symbol specs. |
| `CONY_FRONTEND_DIR` | `<repo>/frontend` | Where the web UI lives. Resolved relative to `backend/dashboard/`, so the default is the `frontend/` folder beside `backend/`. |

---

## Using the API

Start here:

```powershell
curl http://127.0.0.1:8890/health     # connected?
curl http://127.0.0.1:8890/routes     # what can I call?
curl http://127.0.0.1:8890/enums      # what values are legal?
curl http://127.0.0.1:8890/symbol/EURUSD   # how does this instrument work?
curl http://127.0.0.1:8890/research   # what can I build with this?
```

`/symbol/{symbol}` returns the broker's spec plus a `_derived` block carrying
pip size, lot rules, minimum stop distance, supported filling modes and the
account-currency value of one pip — everything needed to size a position and
place valid stops without knowing MetaTrader 5 internals.

**Symbols must use MT5's exact spelling.** Case is not normalised. `EURUSD`
works; `eurusd` does not. Look the spelling up rather than guessing it.

Full reference: [`backend/gateway/docs/api-reference.md`](backend/gateway/docs/api-reference.md).
Gateway internals: [`backend/gateway/README.md`](backend/gateway/README.md).
Frontend conventions: [`frontend/README.md`](frontend/README.md).

---

## Research and strategies

`/research/*` adds strategy work on top of the market data: a catalogue of
every indicator, pattern and entry rule, strategy validation and storage,
pattern scanning, and backtesting with a train/test split.

An agent should read `/research/catalogue` before composing a strategy so it
builds from documented names rather than guessing.

### Reading a verdict

`verdict` is the only field that decides whether anything is worth doing:

| verdict | meaning |
|---|---|
| `noise` | indistinguishable from chance — **do not trade this** |
| `fragile` | significant but net negative, or significant only because gross beat costs |
| `promising` / `strong` | significant and profitable after costs — still replicate before trusting |

Always check `split_check.consistent`. A rule that made its money in the first
half of the sample is not a rule.

### A warning about pattern scans

Follow-through is reported in three layers, and the one that decides the
verdict is the least impressive:

- `mean_move_pct` — the raw forward move. In any period that simply trended,
  every bullish pattern comes out negative and every bearish one positive,
  whether or not they mean anything.
- `mean_edge_pct` — minus what the market did over the same horizon from any
  bar. This isolates the pattern's own contribution, and **the verdict is
  based on it**.
- `mean_edge_pct_net` — minus the round-trip spread. A real effect too small
  to trade is labelled `cost_marginal` rather than hidden.

An effect that does not replicate across symbols and timeframes is noise,
whatever its t-statistic says. One genuine-looking lead found this way —
`breakout_up` on EURUSD M15, surviving Bonferroni — did not replicate: it
appeared in 1 of 14 symbol × timeframe cells.

Findings on a specific instrument are written up in
[`backend/docs/strategies/stepindex.md`](backend/docs/strategies/stepindex.md),
which concludes **UNVALIDATED**. That is the expected result of most of this
work, and it is worth stating plainly rather than burying.

---

## Live trading

The gateway can place real orders. Nothing will send one unless you ask
explicitly.

```powershell
# always check first
curl -X POST http://127.0.0.1:8890/order/check -d '{"symbol":"EURUSD","volume":0.1,"order_type":"buy"}'

# then place it
curl -X POST http://127.0.0.1:8890/buy -d '{"symbol":"EURUSD","volume":0.1,"magic":1234}'
```

`tools/bot/live.py` defaults to `dry_run=True` and refuses to send without
`dry_run=False`.

What does **not** exist yet: a continuous trading loop. There is no EA-style
event loop, no position state machine, and no trailing-stop management on live
positions — `engine.py` implements those for backtests only. Live trading today
means one explicitly requested order at a time. That is a deliberate gap, not an
oversight, and it is the right shape until something has actually earned the
right to run unattended.

---

## Limits worth knowing

The gateway bounds anything that could return an unbounded response, and says
so in the payload when it truncates — but a truncated history is easy to
misread as complete data:

- **History is capped at 365 days and 20,000 rows.** A wider request is
  silently narrowed and the response says `capped`.
- **Candle and tick windows are bounded** for the same reason. A request for
  ten years of M1 candles returns what fits and flags `truncated`.
- **MetaTrader 5's own retention applies on top of this.** Ticks are roughly
  24 hours, M1 candles 90–180 days, H1 around 26 months. This is why
  long-horizon analysis uses candles rather than ticks — the gateway cannot
  return data the broker has already discarded.
- **The gateway binds one terminal.** `MetaTrader5` attaches to a single
  running terminal, so only one daemon process can hold it at a time.

---

## Known gaps

Worth knowing before relying on any of this:

- **`api-reference.md` covers 23 of 61 routes.** The research API, market book,
  SSE streams, position sizing and the whole web UI are undocumented there. The
  live list is always at `GET /routes`.
- **The database is still named `peron.db`** and `PERON_PACKAGE_PATH` is still
  accepted as an alias. Both predate the rename to cotrade.
- **No CI.** `verify.py` is run by hand.
- **The gateway has not been load-tested.** It is threaded, and SSE clients hold
  threads for their lifetime; that is bounded but not proven under many
  concurrent clients.