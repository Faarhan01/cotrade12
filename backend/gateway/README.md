# cony gateway

Direct MetaTrader 5 gateway: a Python daemon that attaches straight to the MT5
terminal through the official `MetaTrader5` package and exposes it over HTTP so
an AI agent can drive it — market data, account state, every order operation,
and live streaming.

```
AI agent / app  →  deamon (:8890)  →  server (routing)  →  cony (engine)  →  MetaTrader5  →  MT5 terminal
```

No Node.js. One process. One port.

## Layers

Three sibling packages. Dependencies run one way only: `deamon → server → cony`.

| Package   | Responsibility | Knows about |
|-----------|----------------|-------------|
| `cony/`   | MT5 engine — connection, symbols, data, trading, DOM | the MetaTrader5 package only |
| `server/` | HTTP routing, validation, JSON shaping, SSE streams | cony, HTTP |
| `deamon/` | Process lifecycle — config, logging, sockets, startup | server, cony |

Neither `cony` nor `server` imports `deamon`, so any layer can be replaced
without touching the others:

- Swap `deamon/` for an MCP server, a WebSocket front end or a CLI — cony and server stay as they are.
- Swap `server/` for FastAPI — cony and deamon stay as they are.
- Import `cony` from a script or notebook with no server running at all.

## Coverage

All 35 public functions of the MetaTrader5 package are wrapped, verified by
`tools/audit_coverage.py`:

| Area | Functions |
|------|-----------|
| Connection | `initialize` `shutdown` `login` `last_error` `version` |
| Account | `account_info` `terminal_info` |
| Counters | `symbols_total` `positions_total` `orders_total` `history_deals_total` `history_orders_total` |
| Symbols | `symbols_get` `symbol_info` `symbol_info_tick` `symbol_select` |
| Ticks | `copy_ticks_from` `copy_ticks_range` |
| Candles | `copy_rates_from` `copy_rates_from_pos` `copy_rates_range` |
| Trading | `order_send` `order_check` `order_calc_margin` `order_calc_profit` |
| Book/positions | `orders_get` `positions_get` `market_book_add` `market_book_get` `market_book_release` |
| History | `history_deals_get` `history_orders_get` |
| Helpers | `Buy` `Sell` `Close` |

223 package constants are exposed as named maps through `GET /enums`, including
the full 40-entry trade return code glossary — all read from the installed
package at runtime rather than hardcoded.

## Layout

```
gateway/
├── cony/                    engine — no HTTP, no server
│   ├── __init__.py
│   ├── connection.py        terminal lifecycle, locking, auto-reconnect
│   ├── mt5_engine.py        every MT5 operation
│   ├── marketbook.py        level-2 depth of market
│   ├── enums.py             constant maps, derived from the package
│   ├── paths.py             package discovery
│   └── serializers.py       namedtuple / numpy → JSON-safe dicts
├── server/                  HTTP layer
│   ├── __init__.py
│   ├── routes.py            URL router
│   ├── handlers.py          endpoints
│   ├── validation.py        input parsing
│   ├── streaming.py         SSE producers
│   ├── research.py          optional /research routes (needs knowledgebase)
│   ├── responses.py         RawResponse, for non-JSON replies
│   └── errors.py            HTTP status mapping
├── deamon/                  service entry point
│   ├── __init__.py
│   ├── __main__.py          gateway assembly, sockets, SSE transport
│   ├── config.py            environment configuration
│   └── logger.py            logging setup
├── tools/
│   ├── verify.py            144 endpoint and error-path checks
│   ├── lifecycle_test.py    real order: open, modify, close, clean up
│   ├── audit_coverage.py    package function coverage
│   ├── audit_hardcode.py    hardcoded path / port / constant scan
│   └── introspect_package.py  dump the package surface
├── docs/
│   └── api-reference.md     full endpoint reference
└── README.md
```

## Running

```powershell
cd <repo>\backend\gateway
python -m deamon
```

Serves on `http://127.0.0.1:8890` and attaches to the terminal on startup.

Point it at the package if it is not already importable:

```powershell
$env:CONY_MT5_PACKAGE = "<path to a directory containing MetaTrader5\"
```

`PERON_PACKAGE_PATH` is still accepted as a legacy alias for the same variable.

Default port is **8890**, not 8888. Cotrade's `peron_bridge.py` already uses
8888, and Windows lets two sockets bind one port and then split traffic between
them without error. The daemon also refuses to start on a busy port rather than
sharing it.

## Research API

`/research/*` adds strategy work on top of the market data: a catalogue of
every indicator, pattern and entry rule; strategy validation and storage;
pattern scanning; and backtesting with a train/test split.

It is an **optional extension**. `server/research.py` registers its routes
only when `knowledgebase` and `tools.bot` are importable from `backend/`, so a
standalone gateway is still a pure MetaTrader 5 gateway. If it is missing, the
startup log says so with the underlying import error, and every market-data
endpoint is unaffected.

```powershell
curl http://127.0.0.1:8890/research           # what it offers, and the workflow
curl http://127.0.0.1:8890/research/catalogue # indicators, patterns, entry rules
```

An agent should read `/research/catalogue` before composing a strategy, so it
builds from documented names rather than guessing.

### Reading a backtest verdict

`verdict` is the only field that decides whether anything is worth doing:

| verdict | meaning |
|---|---|
| `no_trades` | the entry rule never fired |
| `insufficient` | too few trades to measure |
| `unresolvable` | most trades hit the time stop, so the exit was never tested |
| `noise` | indistinguishable from chance — **do not trade this** |
| `fragile` | significant but net negative, or only significant because gross beat costs |
| `promising` | significant and profitable after costs; replicate before trusting |
| `strong` | as above, with a larger margin |

`win_rate` counts every trade including those closed on the time stop;
`resolved_win_rate` counts only trades that actually reached take-profit or
stop-loss. Both are reported because they disagree whenever the exit rule is
loose, and the disagreement is itself the finding.

Always check `split_check.consistent` before believing a `promising` verdict.
A rule that made its money entirely in the first half of the sample is not a
rule.

### Reading a pattern scan

Follow-through is reported in three layers, because they answer different
questions and collapsing them is how drift gets mistaken for skill:

- `mean_move_pct` — the raw forward move. On a sample that simply trended,
  every bullish pattern comes out negative and every bearish one positive,
  whether or not they mean anything.
- `mean_edge_pct` — the move minus `baseline_pct`, what the market did over
  the same horizon from any bar. This isolates the pattern's own
  contribution, and **the verdict is based on it**.
- `mean_edge_pct_net` — the edge minus the round-trip spread. An edge too
  small to trade is a real effect and no profit, so it is labelled
  `cost_marginal` rather than being hidden.

A significant *negative* edge is not a dead pattern; it is one that reliably
moves the other way. `trade_direction` reports `as_signalled` or `inverted`
accordingly. Patterns that fail to replicate across symbols and timeframes
should be assumed to be noise regardless of their t-statistic.

## Dashboard

`GET /` serves a control panel: account summary, open positions, working
orders, recent deals, and a live Market Watch watchlist.

It is an **optional extension**, registered the same way as the research API
and living in `backend/dashboard/` rather than in `gateway/`. The gateway is a
MetaTrader 5 bridge and does not know what a web page is; if the dashboard
cannot be imported the log says so and every JSON endpoint is unaffected.

```
backend/dashboard/
├── __init__.py     route registration
├── views.py        server-side rendering and data collection
└── static/
    ├── app.css
    └── app.js
```

Three properties worth preserving if it is edited:

- **No build step, no CDN, no web fonts.** The page works with no internet
  access, which is the normal condition for a trading desk.
- **Rendered on the server, enhanced by JS.** With scripting off it still
  shows account, positions, orders, deals and the watchlist — it just stops
  updating.
- **Prices arrive over SSE, not polling.** `/symbols` is 1.5 MB for this
  broker's 731 instruments, so it is never sent wholesale; the server projects
  it to the 24 Market Watch instruments and their handful of display fields,
  and `/stream/ticks` pushes only symbols that actually moved.

Handlers return `server.responses.RawResponse` to send bytes verbatim. Without
it every handler result is JSON-encoded, which is right for an agent but would
force the browser through `JSON.parse`.

### Unit discipline

Spreads are converted with the pip size the gateway derives per instrument
(`_derived.pip_size`), never inferred from the digit count:

```
pips = spread_points × point_size / pip_size
```

Two earlier versions of that line were wrong — one inferred the pip size from
`digits`, which misreports every instrument except plain FX pairs, and one
multiplied points by the pip size without dividing by it, which reports
fractions of a pip. Both produced plausible-looking numbers rather than
errors, so check the arithmetic against a known symbol when changing it.

Deal timestamps render in **broker** time (UTC plus the published clock
offset), not this machine's local time, so they agree with the header clock.

## Start here

An agent should call these, in order:

```powershell
curl http://127.0.0.1:8890/health          # am I connected?
curl http://127.0.0.1:8890/routes          # what can I call?
curl http://127.0.0.1:8890/enums           # what values are legal?
curl http://127.0.0.1:8890/symbol/EURUSD   # how does this instrument work?
curl http://127.0.0.1:8890/research        # what can I build with this?
```

Open `http://127.0.0.1:8890/` in a browser for the same information rendered
as a dashboard.

`/symbol/{symbol}` is the important one. It returns the broker's spec plus a
`_derived` block carrying the pip size, lot rules, minimum stop distance,
supported filling modes, swaps, and the account-currency value of one pip — the
facts needed to size a position and place valid stops without knowing MT5
internals:

```jsonc
"_derived": {
  "pip_size": 0.0001,
  "point_size": 1e-05,
  "points_per_pip": 10,
  "pip_decimals": 4,
  "lot_info": { "min_lot": 0.01, "max_lot": 20.0, "lot_step": 0.01, "contract_size": 100000.0 },
  "order_rules": { "min_stop_distance_points": 20, "min_stop_distance_pips": 2.0 },
  "filling": { "supported": ["fok"], "flag": 1 },
  "trade_mode": "full",
  "pip_value_per_lot": 10.0,
  "sizing_formula": "lots = risk_amount / (stop_distance_in_pips * pip_value_per_lot)"
}
```

Values are lowercase so they round-trip: whatever `/enums` advertises can be sent
straight back in a query or body.

## Trading

```powershell
# Size a position from a risk budget
curl -X POST http://127.0.0.1:8890/calc/size -H "Content-Type: application/json" `
  -d '{"symbol":"EURUSD","risk_amount":50,"stop_pips":20}'
# -> {"lots": 0.24, "actual_risk": 48.0, ...}

# Dry run first - places nothing, reports margin and any problem
curl -X POST http://127.0.0.1:8890/order/check -H "Content-Type: application/json" `
  -d '{"symbol":"EURUSD","volume":0.24,"order_type":"buy","sl":1.1150,"tp":1.1300}'

# Then place it
curl -X POST http://127.0.0.1:8890/buy -H "Content-Type: application/json" `
  -d '{"symbol":"EURUSD","volume":0.24,"sl":1.1150,"tp":1.1300,"magic":1001,"comment":"ai"}'

# Read, adjust, exit
curl http://127.0.0.1:8890/positions
curl -X POST http://127.0.0.1:8890/modify -H "Content-Type: application/json" -d '{"ticket":123,"sl":1.1180}'
curl -X POST http://127.0.0.1:8890/close  -H "Content-Type: application/json" -d '{"ticket":123}'
```

`order_type` accepts names (`buy`, `sell`, `buy_limit`, `buy_stop`, …) as well
as MT5 integers. `type_filling` can be omitted: the gateway reads the symbol's
declared filling modes and picks one the broker accepts, which avoids retcode
10030 on brokers that reject `return`.

Every order response echoes the request the terminal actually processed under
`_resolved_request`, so a caller can confirm its stops and fills were honoured
rather than assuming.

## Live data

Server-Sent Events — no dependency, no extra protocol. Send
`Accept: text/event-stream`.

| Stream | Emits |
|--------|-------|
| `/stream/ticks?symbols=EURUSD,GBPUSD&interval=1` | Ticks, only when a price moved |
| `/stream/marketbook?symbols=EURUSD&interval=1` | Depth of market |
| `/stream/portfolio?interval=2` | Account and open positions together, for live PnL |

`symbols` defaults to whatever is open. `interval` is clamped to 0.2–60s. The
server is threaded, so an open stream never blocks other requests — verified by
`tools/verify.py`.

```powershell
curl -N -H "Accept: text/event-stream" `
  "http://127.0.0.1:8890/stream/ticks?symbols=EURUSD&interval=1"
```

### Symbol names

Symbol names are used **exactly as MetaTrader 5 spells them** — they are
case-sensitive and not uniformly upper case, so the gateway never rewrites
them. `Step Index 200` is a real symbol; `STEP INDEX 200` is not.

A name given in the wrong case still resolves: the gateway keeps a cached
map from the broker's own list and returns the canonical spelling.

```powershell
curl http://127.0.0.1:8890/symbol/Step%20Index%20200   # exact broker name
curl http://127.0.0.1:8890/symbol/step%20index%20200   # wrong case, still works
```

That map costs ~236 ms to build (it reads every symbol with full specs) and is
cached for `CONY_SYMBOL_CACHE_TTL` seconds. `/health` reports its state:

```json
"symbol_cache": { "entries": 731, "ttl_seconds": 300, "age_seconds": 4.2, "valid": true }
```

If a symbol is added at the broker and you need it immediately rather than
waiting out the TTL:

```powershell
curl -X POST http://127.0.0.1:8890/symbol-cache/clear
```

The cache is also dropped automatically on reconnect, since a reconnect can
land on a different account with a different symbol list.

## Errors

| Status | Meaning |
|--------|---------|
| `400` | Missing, malformed or out-of-range parameter |
| `404` | Unknown route, symbol, or ticket |
| `409` | Terminal or broker refused it; body carries `retcode` |
| `503` | Terminal not connected |
| `500` | Unexpected engine failure |

```json
{ "error": "'volume' must be >= 1e-05, got 0", "type": "BadRequest", "status": 400 }
```

Order rejections name the cause and carry the MT5 code, so a requote (10004)
is distinguishable from insufficient margin (10019) or a stop in the freeze
zone (10029). `GET /enums` decodes any code.

## Configuration

All environment variables.

| Variable | Default | Meaning |
|----------|---------|---------|
| `CONY_HOST` | `127.0.0.1` | Bind address |
| `CONY_PORT` | `8890` | Bind port |
| `PERON_PACKAGE_PATH` / `CONY_MT5_PACKAGE` | auto-detected | Directory holding `MetaTrader5/` |
| `MT5_LOGIN` `MT5_PASSWORD` `MT5_SERVER` | — | Only needed if the terminal is not logged in |
| `MT5_PATH` | — | Path to `terminal64.exe` |
| `MT5_TIMEOUT` | `60000` | Connect timeout, ms |
| `CONY_AUTO_CONNECT` | `true` | Attach on startup |
| `CONY_AUTO_RECONNECT` | `true` | Reattach in the background if the link drops |
| `CONY_RECONNECT_INTERVAL` | `20` | Seconds between attempts |
| `CONY_SYMBOL_CACHE_TTL` | `300` | Seconds a cached symbol-name map stays valid |
| `CONY_LOG_LEVEL` | `INFO` | Log level |
| `CONY_LOG_FILE` | — | Also write logs to a file |

## Testing

With the daemon running:

```powershell
python tools\verify.py           # 129 read-only and error-path checks
python tools\audit_coverage.py   # 35/35 package functions wrapped
python tools\audit_hardcode.py   # no hardcoded paths, ports or constants
python tools\lifecycle_test.py   # places and closes one real order
```

`lifecycle_test.py` trades on the connected account. It uses the minimum lot,
tags everything with a magic number, and closes what it opens in a `finally`
block, so it leaves the account flat. Run it against a demo account.

## Requirements

Python 3.11 on Windows. The MetaTrader5 package ships a `cp311-win_amd64`
binary extension, so the interpreter version and platform must match. The MT5
terminal must be installed, logged in and running, with Algo Trading enabled.

`cony` never invents data. With the terminal down, reads reconnect or fail
rather than returning placeholders.
