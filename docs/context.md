# Cotrade — Project Context

> Comprehensive reference for the Cotrade codebase. MetaTrader 5 gateway, real-time trading dashboard, research analytics, and algorithmic strategy engine.

## Overview

- **Project name:** Cotrade
- **Repo root:** `/workspaces/Countr`
- **Purpose:** MetaTrader 5 gateway, real-time trading dashboard, research analytics platform, and algorithmic strategy engine
- **Languages:** Python (backend), HTML/CSS/JS (frontend)
- **Dependencies:** `MetaTrader5` (system), standard library only (Python). Frontend: no build step, no npm, no CDN, no web fonts.
- **Database:** SQLite (`backend/db/data/peron.db`) in WAL mode with auto-indexing
- **Gateway default port:** 8890 (not 8888 — Cotrade's `peron_bridge.py` uses 8888)

## Architecture (3-Layer Gateway)

```
AI agent / app  →  deamon (HTTP)  →  server (routing)  →  cony (engine)  →  MetaTrader5  →  MT5 terminal
```

| Package | Location | Responsibility |
|---------|----------|----------------|
| `cony` | `backend/gateway/cony/` | MT5 engine — no HTTP, no server. Just MT5 operations returning dicts |
| `server` | `backend/gateway/server/` | HTTP routing, validation, JSON shaping, SSE streams |
| `deamon` | `backend/gateway/deamon/` | Process lifecycle — config, logging, sockets, startup |
| `dashboard` | `backend/frontconnect/` | Web UI routes — optional extension |
| `knowledgebase` | `backend/knowledgebase/` | Indicators, patterns, strategies as pure logic (no I/O) |
| `tools/bot` | `backend/tools/bot/` | Backtesting, pattern checking, live execution |
| `db` | `backend/db/` | SQLite access layer + schema |
| `server` (extensions) | `backend/server/` | Research API, DB routes, Bot routes, handlers |

Dependencies run one way: `deamon → server → cony`. Neither `cony` nor `server` imports `deamon`.

## Entry Points

- `run.py` (root) — Unified application runner & dev server (CLI entry point)
- `app.py` (root) — Entry point for AI Studio, runs daemon on host 0.0.0.0:3000
- `backend/gateway/deamon/__main__.py` — Gateway assembly, sockets, SSE transport
- `python -m deamon` (from `backend/gateway/`) — starts daemon

### `run.py` subcommands

```
python run.py                     # Start dev server & dashboard (default: 0.0.0.0:3000)
python run.py dev                 # Explicit dev server start
python run.py server --port 8890  # Custom port
python run.py server --open      # Open browser on launch
python run.py db                 # Show DB stats and integrity
python run.py routes             # Print all 73+ API routes
python run.py bot sweep EURUSD    # Run strategy sweep over instrument data
python run.py bot scan EURUSD    # Run pattern detector over historical bars
```

## Directory Structure

```
Countr/
├── run.py                        # Unified runner
├── app.py                        # AI Studio entry point
├── metadata.json                 # project metadata
├── package.json                  # minimal Python wrapper
├── requirements.txt             # MetaTrader5>=5.0.45 (optional numpy>=1.26.0)
├── README.md                    # Main README
├── README.cotrade.md            # Backup README
├── backend/
│   ├── bot/                     # top-level re-exports bot tools
│   ├── db/
│   │   ├── database/
│   │   │   ├── schema.py        # SQLite schema
│   │   │   └── store.py         # SQLite access layer
│   │   └── data/peron.db        # database file
│   ├── docs/
│   │   ├── Plans/TODO.md
│   │   ├── info/testing.md
│   │   └── strategies/stepindex.md
│   ├── frontconnect/           # web dashboard routes
│   ├── gateway/
│   │   ├── README.md           # gateway README
│   │   ├── cony/               # MT5 engine (35 functions wrapped)
│   │   │   ├── __init__.py
│   │   │   ├── connection.py   # terminal lifecycle, locking, auto-reconnect
│   │   │   ├── mt5_engine.py   # every MT5 operation
│   │   │   ├── marketbook.py   # level-2 depth of market
│   │   │   ├── enums.py        # constant maps from package
│   │   │   ├── paths.py        # package discovery
│   │   │   └── serializers.py  # namedtuple/numpy to JSON-safe dicts
│   │   ├── server/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py       # URL router
│   │   │   ├── handlers.py    # endpoints
│   │   │   ├── validation.py  # input parsing
│   │   │   ├── streaming.py   # SSE producers
│   │   │   ├── research.py    # /research API (knowledgebase)
│   │   │   ├── responses.py   # RawResponse
│   │   │   └── errors.py      # HTTP status mapping
│   │   ├── deamon/
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py    # gateway assembly, sockets, SSE transport
│   │   │   ├── config.py      # environment config
│   │   │   └── logger.py      # logging setup
│   │   ├── cony/ (already listed)
│   │   ├── docs/api-reference.md
│   │   └── tools/
│   │       ├── verify.py      # 144 endpoint + error-path checks
│   │       ├── lifecycle_test.py # real order test
│   │       ├── audit_coverage.py # package function coverage
│   │       ├── audit_hardcode.py # hardcoded path/port/constant scan
│   │       └── introspect_package.py # dump package surface
│   ├── knowledgebase/         # indicators, patterns, strategies
│   ├── server/                # HTTP layer extensions
│   │   ├── handlers.py        # RouteHandlers (70+ routes)
│   │   ├── routes.py          # Router
│   │   ├── validation.py      # input validation
│   │   ├── streaming.py       # SSE
│   │   ├── research.py        # /research routes
│   │   ├── responses.py       # RawResponse
│   │   ├── errors.py          # HTTPError
│   │   ├── bot_routes.py      # /bot routes
│   │   └── db_routes.py       # /db routes
│   └── tools/bot/             # backtesting, patterns, live, datafeed, runner
├── docs/
│   ├── issues/
│   ├── plans/
│   └── context.md            # THIS FILE
└── frontend/                 # static web dashboard
    ├── pages/                # index, symbols, research, history, bot
    ├── partials/             # head, footer, header
    └── assets/              # css, js
```

## Key Components

### 1. MetaTrader 5 Gateway (`backend/gateway/cony/`)

**connection.py** — `ConnectionManager`

Thread-safe terminal lifecycle. Manages import (with package discovery), connect credentials, auto-reconnect loop, and disconnect callbacks. Holds `_on_disconnect` callbacks fired on drop so dependent state (market book subscriptions) can be cleaned.

Key configurable env vars: `CONY_MT5_PACKAGE` (package path), `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH`, `MT5_TIMEOUT`.

**mt5_engine.py** — `MT5Engine`

Wraps **all 35 public functions** of MetaTrader5:
- Connection: `initialize`, `shutdown`, `login`, `last_error`, `version`
- Account: `account_info`, `terminal_info`
- Counters: `symbols_total`, `positions_total`, `orders_total`, `history_deals_total`, `history_orders_total`
- Symbols: `symbols_get`, `symbol_info`, `symbol_info_tick`, `symbol_select`
- Ticks: `copy_ticks_from`, `copy_ticks_range`
- Candles: `copy_rates_from`, `copy_rates_from_pos`, `copy_rates_range`
- Trading: `order_send`, `order_check`, `order_calc_margin`, `order_calc_profit`
- Book/positions: `orders_get`, `positions_get`, `market_book_add`, `market_book_get`, `market_book_release`
- History: `history_deals_get`, `history_orders_get`
- Helpers: `Buy`, `Sell`, `Close`

**Key derived values on every symbol:**
- pip size (point * 10 — never inferred from digit count)
- point size, points per pip
- lot_info (min/max/step, contract_size)
- order_rules (min_stop_distance_points, freeze_distance_points)
- filling modes (broker-declared supported)
- trade_mode, spreads, swaps
- pip_value_per_lot (account currency per pip per standard lot)
- sizing_formula

**Symbol caching:**
- TTL-based case-insensitive map (uppercase → canonical spelling)
- `resolve_symbol()` handles wrong-case names
- Drops on reconnect (different account may have different symbols)

**Other features:**
- `clock_offset()` — seconds between broker and machine UTC
- `market_book` — depth-of-market subscriptions
- `ensure_connected()` / `mark_dropped()`

### 2. HTTP Server (`backend/gateway/server/`)

**routes.py** — `Router`
- `_compile_pattern()` turns patterns like `/symbol/{symbol}` into regex with named groups
- Supports `{name}` (single segment, no slashes) and `{name...}` (wildcard, rest of path)
- `resolve()` matches requests, decodes URL-encoded params

**handlers.py** — `RouteHandlers` (70+ routes)
- Discovery: `/health`, `/routes`, `/enums`, `/streams`
- Connection: `/connect`, `/disconnect`, `/login`, `/last-error`
- Account: `/account`, `/terminal`, `/totals`, `/portfolio`
- Symbols: `/symbols`, `/symbols/search`, `/symbol/{symbol}`, `/symbol/{symbol}/select`
- Ticks: `/tick/{symbol}`, `/ticks`, `/ticks/history`
- Candles: `/candles/{symbol}`
- Positions: `/positions`, `/positions/{ticket}`
- Orders: `/orders`
- Trading: `/order/check`, `/order`, `/buy`, `/sell`, `/close`, `/close-all`, `/modify`, `/cancel`
- Calculators: `/calc/margin`, `/calc/profit`, `/calc/size`
- History: `/history/deals`, `/history/orders`, `/history/totals`, `/history/summary`
- Market Book: `/marketbook`, `/marketbook/{symbol}`, `/marketbook/{symbol}/subscribe`, `/marketbook/{symbol}/unsubscribe`, `/marketbook/subscribed`

**Optional extensions:**
- Research API (`server/research.py`) — strategy validation/storage, pattern scanning, backtesting
- Database API (`server/db_routes.py`) — DB management
- Bot API (`server/bot_routes.py`) — bot management
- Dashboard (`frontend/`) — serves HTML via `frontconnect`

### 3. Daemon (`backend/gateway/deamon/`)

**`__main__.py`** — `Gateway` class:
- Assembles engine + router + handlers + HTTP server
- `GatewayServer` — threaded HTTP server, refuses to share port (Windows socket issue)
- SSE handling (`serve_stream`) — tick/marketbook/portfolio producers
- `_on_terminal_reset` removes market book + invalidates symbol cache on reconnect
- Connect happens on background thread (mt5.initialize() can block)

**config.py** — env vars: `CONY_HOST`, `CONY_PORT`, `PERON_PACKAGE_PATH`/`CONY_MT5_PACKAGE`, `MT5_*`, `CONY_AUTO_CONNECT`, `CONY_AUTO_RECONNECT`, `CONY_RECONNECT_INTERVAL`, `CONY_SYMBOL_CACHE_TTL`, `CONY_LOG_LEVEL`, `CONY_LOG_FILE`

**logger.py** — setup logging

### 4. Frontend (`frontend/`)

Plain HTML/CSS/JS:
- **Pages:** `index.html`, `symbols.html`, `research.html`, `history.html`, `bot.html`
- **Partials:** `head.html`, `header.html`, `footer.html`
- **Assets:** `css/{base,layout,components,pages/*}`, `js/lib/{chart,format,utils,shell,components,api,dom}`, `js/pages/{bot,history,research,symbols,dashboard}`
- Server markers: `<!--#include header-->`, `<!--#include footer-->`, `<!--#bootstrap-->`
- Data comes via bootstrap JSON + SSE live updates (`/stream/portfolio`, `/stream/ticks`)
- Warnings: `/symbols` is 1.5 MB → never sent whole (only 24 Market Watch instruments reachable via SSE)

### 5. Knowledgebase (`backend/knowledgebase/`)

**Pure logic only:** no I/O, no database, no gateway, no numpy.

- **Indicators** (`indicators.py`) — 13 indicators over Python lists:
  - SMA, EMA, WMA, RSI (Wilder's), True Range, ATR (Wilder-smoothed), Bollinger, MACD, Stochastic, ADX (Wilder), Donchian, Slope (least-squares), VWAP, CCI, Z-Score
  - `REGISTRY` dict + `compute(name, ...)` lookup
  - Returns list same length as input, `None` during warm-up

- **Patterns** (`patterns.py`) —
  - `Bar` dataclass (time, open, high, low, close, tick_volume)
  - `PatternMatch` dataclass (pattern, index, direction, strength, label, meta)
  - `to_bars()` converts gateway candle dicts → `Bar`
  - Candlestick detectors: doji, hammer, shooting_star, bullish/bearish_engulfing, morning/evening_star, marubozu, pinbar_bullish/bearish, fvg_bullish/bearish
  - Price-action: support_touch, resistance_touch, higher_low, lower_high, breakout_up/down
  - `scan(bars, patterns=None, start=0)` runs detectors, sorted by index

- **Strategies** (`strategies.py`) —
  - `Context` dataclass: holds bars + cached indicators + pattern matches. Has `ind()`, `value()`, `series()`, `patterns_at()` methods
  - `ExitRule`: take_profit, stop_loss, trailing_stop, time_stop_bars, breakeven_after_pips (all in pips)
  - `SizingRule`: mode (fixed | risk_pct), lots, risk_pct, max_lots
  - `Strategy` dataclass: name, symbol, timeframe, entry_name, entry_params, exit_rule, sizing, spread_pips, enabled
  - `ENTRY_RULES` dict of 6 rules:
    - rsi_reversion, ma_cross, breakout_entry, pattern_entry, momentum_entry, trend_strength_entry
  - `Strategy.library()` — starter set of 7 ready-made strategies (ma_cross_20_50, rsi_reversion_14, breakout_20, momentum_follow_10, momentum_fade_10, trend_strength_adx14, engulfing_entry)
  - `signal(ctx, i)` runs entry rule with persistable params

### 6. Backtest Engine (`backend/tools/bot/engine.py`)

**BacktestResult:** comprehensive metrics
- Core: trades (list of `Trade`), bars, from_ts, to_ts, pip
- Derived: net_pips, resolved, timed_out, wins, losses, net_points, win_rate, resolved_win_rate, profit_factor, expectancy, t_statistic, max_drawdown, sharpe_ratio, sortino_ratio, max_consecutive_wins/losses, verdict
- `to_dict()` serializes (without full trade list)

**Trade:** side, entry_index, exit_index, entry_price, exit_price, pnl_points, reason (take_profit|stop_loss|time|trailing), bars_held, won

**Constants:** SIGNIFICANT_T=2.0, STRONG_T=3.0, MIN_TRADES=30, MIN_EDGE_VS_COST=1.0

**classify() returns one of:**
- no_trades | insufficient (fewer than 30 trades)
- unresolvable (fewer than 30% resolved)
- noise (|t| < 2.0)
- fragile (significant but net ≤ 0)
- promising (significant, net > 0, |t| < 3.0)
- strong (|t| >= 3.0 and net > 0)

**run(strategy, bars, inst, pip, warmup, ctx):** event-driven
- Skips warmup bars
- On signal (side != 0), enters at bar close + spread
- Calculates TP/SL in price units
- Checks TP/SL on subsequent bars' high/low
- Breakeven: moves SL to entry when favorable move reaches threshold
- Trailing stop: ratchets up, checks next bar (doesn't fill same bar)
- Time stop: closes after max_bars (default 20)
- Closes at entry + spread if still open
- Computes PnL as side * (exit_price - entry)

**sweep(strategy, bars, inst, split=0.7, pip, warmup):**
- Train/test split (70/30)
- Returns dict with train, test, consistent flag
- consistency requires: both produce trades, signs agree, test |t| >= 2.0

### 7. Pattern Checker (`backend/tools/bot/patternchecker.py`)

**analyse_follow_through():** 3-layer follow-through analysis
1. **GROSS** — raw forward move (signed by predicted direction)
2. **EDGE** — move minus market baseline (what price did anyway)
3. **NET** — edge minus round-trip spread cost

Other outputs:
- hit_rate, hit_rate_edge
- t_statistic, t_statistic_edge, t_statistic_net
- Bonferroni-corrected threshold per family
- cost_marginal flag (significant before costs, not after)

**_trade_direction:** AS_SIGNALLED (pattern predicts correct direction, survives costs), INVERTED (significant negative edge), None

**CheckReport:** includes counts, density, spread_pct, follow-through
- Print summary with per-pattern stats + follow-through table

**bonferroni_threshold():** two-tailed critical |t| for N comparisons at family-wise alpha

### 8. Database (`backend/db/database/`)

**Store** (`store.py`) — thread-safe SQLite wrapper with RLock:
- `migrate()` — creates tables
- `query()`, `execute()` — raw SQL
- Strategies: `save_strategy`, `load_strategy`, `list_strategies`, `delete_strategy`, `get_strategy_version`, `get_strategy_history`, `clone_strategy`
- Reference data: `sync_indicators`, `sync_patterns`, `list_patterns`, `list_indicators`
- Reports: `save_report`, `reports` (filter by strategy/verdict), `best_reports` (ranked by t-stat)
- Pattern hits: `save_hits`, `save_hit_context`, `hits` (filter), `pattern_frequency`
- Bar cache: `save_bars`, `load_bars`, `bar_range`
- Report trades: `save_report_trades`, `report_trades`
- Bot sessions: `create_bot_session`, `update_bot_session`, `list_bot_sessions`, `log_bot_action`, `list_bot_logs`
- Maintenance: `stats()`, `check_integrity()`, `vacuum()`

**schema.py** — 14 tables:
- `strategies`, `strategy_versions`, `indicators`, `patterns`, `reports`, `pattern_hits`, `hit_context`, `bars`, `report_trades`, `bot_sessions`, `bot_logs`
- Plus 3 indexes + 1 trigger (`trg_strategies_updated`: updates `updated` and increments `version` on UPDATE)

**Report fields:** run_id, strategy_id, strategy_name, strategy_snapshot, symbol, timeframe, pip, bars, from_ts, to_ts, split, trades, resolved, win_rate, resolved_win_rate, profit_factor, net_points, gross_points, spread_cost, max_drawdown, expectancy, t_statistic, verdict

### 9. Datafeed (`backend/tools/bot/datafeed.py`)

Fetches OHLC bars from gateway with optional SQLite cache:
- `health()` — gateway health probe
- `symbol_info(symbol)` — full symbol info
- `instrument(symbol)` — flat instrument dict (pip, point, spread, pip_value, min_lot, trade_mode)
- `candles()` — fetch OHLC from gateway
- `bars()` — convert to `Bar` objects
- `cached_bars()` — read from SQLite cache
- `fetch()` — prefer cache when available, auto-write-back

Env-based gateway URL resolution (`CONY_URL`, falling back to `CONY_HOST`/`CONY_PORT`).

### 10. Runner (`backend/tools/bot/runner.py`)

Commands:
- `sweep`: fetch bars → run all strategies → save reports → print table ranked by t-stat
- `scan`: run pattern checker → print summary → optionally save hits
- `list`: list strategies, indicators, patterns
- `report`: show DB stats + recent reports

Both sync knowledgebase to DB first (indicators, patterns, strategies) via `seed_library()`.

### 11. Live Trader (`backend/tools/bot/live.py`)

`LiveTrader` class:
- `dry_run` default (blocks sending unless `live=True`)
- `current_signal()` evaluates strategy on most recent closed bar (-2: last bar may be forming)
- `check_order()` → `/order/check` dry run through terminal
- `send()` → place market order (only if dry_run off; checks first)
- `size_for()` → risk-based lot sizing via gateway `/calc/size`
- `close_all()` → flatten position
- `evaluate()` → one decision cycle (no trading)
- Bot session logging + update bot session status in DB

### 12. Research API (`backend/server/research.py`)

Optional extension (registers only if knowledgebase + tools/bot importable):
- Strategy catalogue (indicators, patterns, entry rules)
- Strategy storage (POST), validation
- Pattern scanning
- Backtesting with train/test split
- Verdict interpretation (from README)
- `/research/catalogue`, `/research/validate`, `/research/scan`, `/research/backtest`

### 13. Dashboard (`backend/frontconnect/`)

`register(router, engine)` adds:
- `GET /` → serves `frontend/pages/index.html`
- `GET /ui/{page}` → serves `frontend/pages/{page}.html`
- `GET /assets/{path...}` → serves `frontend/assets/**`

**VIEWS:**
- `context()` gathers data per-page (`_SECTIONS` dict defines what each needs):
  - `index`: account, terminal, totals, positions, orders, deals, watchlist
  - `symbols`: account, terminal
  - `research`: account, terminal, watchlist
  - `history`: account, terminal
  - Default: account, terminal
- `_OFFSET_TTL_SECONDS=300` (clock offset cached, as it costs dozens of round trips)
- `_watchlist()` projects to 24 instruments (pip_size requires per-symbol symbol_info call)
- `_recent_deals()` last 2 days, sorted newest-first, limited to 25
- `render()` splices in partials + injects bootstrap JSON in `<script type="application/json">`

### 14. Enums (backend/gateway/cony/enums.py)

223 constants evolved from MT5 package introspection:
- `ORDER_TYPES` (buy, sell, buy_limit, sell_limit, buy_stop, sell_stop, buy_stop_limit, sell_stop_limit)
- `POSITION_TYPES` (buy, sell)
- `DEAL_TYPE_NAMES`, `DEAL_ENTRY_NAMES`
- `ORDER_STATE_NAMES`
- `TRADE_ACTIONS` (deal, pending, close, sltp, modify, remove)
- `COPY_TICKS_FLAGS` (all, info, trade)
- `TIMEFRAME_NAMES`, `TIMEFRAME_SECONDS`
- `SYMBOL_TRADE_MODE_NAMES`
- `TRADE_MODE_NAMES`, `MARGIN_MODE_NAMES`
- `ORDER_TIMES` (gtc, day, spec_expiration, fill_or_kill, fill_or_kill, pending)
- `supported_filling_modes(flag)` → list of accepted fillings (fok, ioc, return)
- `accepted_retcodes()` / `retcode_glossary()` / `retcode_name()`

### 15. Validation (backend/server/validation.py, backend/gateway/server/validation.py)

Input parsing helpers:
- `symbol()`, `optional_symbol()`
- `integer()`, `number()`, `optional_number()`
- `boolean()`
- `_from_map()`, `_order_type()`, `order_type()`
- `timeframe()`, `when()` (datetime parse)
- `date_range()`
- `copy_ticks_flag()`
- `magic()`, `comment()`
- `order_id()`
- `filling_mode()`
- `trade_action()`, `order_time()`

Max limits: `MAX_TICKS`, `MAX_CANDLES`, `HISTORY_MAX_DAYS=365`, `HISTORY_MAX_ROWS=20000`

### 16. Serializers (backend/gateway/cony/serializers.py)

`serialize_namedtuple(nt)` and `serialize_array(arr)`:
- numpy int/float → Python native
- `datetime` → ISO string / epoch
- Adds `_label` for `_asdict` objects (MT5 namedtuple → dict)
- infinity/nan handling

## Configuration (Environment Variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `CONY_HOST` | `127.0.0.1` | Bind address |
| `CONY_PORT` | `8890` | Bind port (run.py uses `PORT` env or 3000) |
| `PERON_PACKAGE_PATH` / `CONY_MT5_PACKAGE` | auto-detected | Directory holding `MetaTrader5/` |
| `MT5_LOGIN` | — | Account login |
| `MT5_PASSWORD` | — | Account password |
| `MT5_SERVER` | — | Server name |
| `MT5_PATH` | — | Path to `terminal64.exe` |
| `MT5_TIMEOUT` | `60000` | Connect timeout (ms) |
| `CONY_AUTO_CONNECT` | `true` | Attach on startup |
| `CONY_AUTO_RECONNECT` | `true` | Reattach in background if link drops |
| `CONY_RECONNECT_INTERVAL` | `20` | Seconds between reconnect attempts |
| `CONY_SYMBOL_CACHE_TTL` | `300` | Seconds a cached symbol-name map stays valid |
| `CONY_LOG_LEVEL` | `INFO` | Log level |
| `CONY_LOG_FILE` | — | Also write logs to a file |
| `CONY_URL` | — | Override gateway URL for bot tools |
| `PERON_DB` | default path | SQLite DB path override |
| `CONY_FRONTEND_DIR` | `frontend/` | Frontend directory override |
| `PERON_DB` (also) | — | DB location |

## Web Dashboard & Navigation

| Route | Page | Description |
|-------|------|-------------|
| `/` | `index.html` | Account Overview — live balance, equity, margin, positions, orders, deals, Market Watch |
| `/ui/symbols` | `symbols.html` | Instrument Browser — specs, contract sizes, tick sizes, swap rates, pip values |
| `/ui/research` | `research.html` | Strategy & Pattern Lab — pattern scanning, edge calculation, backtests |
| `/ui/history` | `history.html` | Account History — date-windowed deals, profit, commission, swap, net |
| `/ui/bot` | `bot.html` | Bot & Database Hub — stored strategies, backtest reports, trade logs, DB maintenance |

## Quick Start from Root

```bash
# Start dev server + dashboard (0.0.0.0:3000)
python run.py

# Or explicitly server with options
python run.py server --port 8890 --host 127.0.0.1 --open

# Inspect SQLite database stats and integrity
python run.py db

# Print all routes
python run.py routes

# Run strategy sweep
python run.py bot sweep EURUSD

# Run pattern scan
python run.py bot scan EURUSD
```

## Research API Concept

`/research/*` is an optional extension. `server/research.py` registers routes only when `knowledgebase` and `tools.bot` are importable from `backend/`. Provides:
- Catalogue of indicators, patterns, entry rules
- `POST /research/validate` — strategy validation
- Strategy storage (`save_strategy` to DB)
- Pattern scanning (`/research/scan`)
- Backtesting with train/test split (`/research/backtest`)

**Verdict reading guide:**
| Verdict | Meaning |
|---------|---------|
| `no_trades` | entry rule never fired |
| `insufficient` | too few trades to measure (< 30) |
| `unresolvable` | most trades hit time stop; exit untested |
| `noise` | indistinguishable from chance — don't trade |
| `fragile` | significant but net negative, or significant only because gross beat costs |
| `promising` | significant + profitable after costs; replicate before trusting |
| `strong` | as above with larger margin (|t| >= 3.0) |

Always check `split_check.consistent` before believing `promising`. A rule that made money only in first half is not a rule.

## Trading Workflow

1. `GET /health` — am I connected?
2. `GET /routes` — what can I call?
3. `GET /enums` — what values are legal?
4. `GET /symbol/{symbol}` — instrument specs + `_derived` block (pip size, lot rules, min stop distance, filling modes, swaps, pip value)
5. `POST /calc/size` — risk-based lot sizing
6. `POST /order/check` — dry run
7. `POST /buy` or `/sell` — place market order
8. `GET /positions` — monitor
9. `POST /modify` — adjust SL/TP
10. `POST /close` — exit

**Order types:** buy, sell, buy_limit, sell_limit, buy_stop, sell_stop, buy_stop_limit, sell_stop_limit

**Symbol names** are case-sensitive — never rewritten. Wrong case still resolves via cached name map.

## SSE Streams

| Stream | Emits |
|--------|-------|
| `/stream/ticks?symbols=EURUSD,GBPUSD&interval=1` | Ticks, only when price moved |
| `/stream/marketbook?symbols=EURUSD&interval=1` | Depth of market |
| `/stream/portfolio?interval=2` | Account + open positions together |

- `symbols` defaults to whatever is open/selected
- `interval` clamped to 0.2–60s
- Server is threaded — open stream never blocks other requests

## Error Responses

| Status | Meaning |
|--------|---------|
| `400` | Missing, malformed, or out-of-range parameter |
| `404` | Unknown route, symbol, or ticket |
| `409` | Terminal or broker refused it; body carries `retcode` |
| `503` | Terminal not connected |
| `500` | Unexpected engine failure |

```json
{ "error": "'volume' must be >= 1e-05, got 0", "type": "BadRequest", "status": 400 }
```

## Testing Tools (`backend/gateway/tools/`)

- `verify.py` — 144 read-only + error-path checks (measured)
- `audit_coverage.py` — package function coverage (35/35)
- `audit_hardcode.py` — no hardcoded paths/ports/constants
- `lifecycle_test.py` — places + closes one real order (MINIMIZE lot, tagged magic, closes in finally) — run on demo account only

## Documentation Files

- `README.md` (root) — main README
- `README.cotrade.md` (root) — backup README
- `backend/gateway/README.md` — gateway (cony) README
- `frontend/README.md` — frontend README
- `backend/docs/Plans/TODO.md`
- `backend/docs/info/testing.md`
- `backend/docs/strategies/stepindex.md`
- `backend/gateway/docs/api-reference.md`
- `docs/plans/unfinished.md`
- `docs/issues/frontend-utils-js-escapehtml-issue.md`
- `docs/context.md` (THIS FILE) — comprehensive context

## Python Version / Platform

- Python 3.11 on Windows (MetaTrader5 ships `cp311-win_amd64` binary extension)
- MT5 terminal must be installed, logged in, running, with Algo Trading enabled
- `cony` never invents data. With terminal down, reads reconnect or fail — never return placeholders.

## Frontend Notes

**Conventions:**
- Tabs in every figure (monospaced values)
- Drill sizes come from server — vary per instrument
- Timestamps in broker time (UTC + clock offset)
- Color: green=gain, red=loss, muted=neutral
- Escape anything from broker (symbol names, comments, server names)

**Editing:** Pages/assets read from disk on every request — no restart needed. Only `backend/dashboard/*.py` changes require restart.

## Research Library Catalogue

### Indicators (13)
- SMA, EMA, WMA, RSI, ATR, Bollinger, MACD, Stochastic, ADX, Donchian, Slope, VWAP, CCI, Z-Score
- All over plain lists, return equal-length list with `None` warm-up, never mutate input

### Patterns (16)
- Candlestick: doji, hammer, shooting_star, bullish/bearish_engulfing, morning/evening_star, marubozu, pinbar_bullish/bearish, fvg_bullish/bearish
- Price-action: support_touch, resistance_touch, higher_low, lower_high, breakout_up/down
- Scan with lookback warm-up (start default 2), dedups on (index, pattern)

### Entry Rules (6)
- rsi_reversion — oversold/overbought with confirm (looks backward, never forward)
- ma_cross — fast SMA crosses slow SMA
- breakout_entry — Donchian breakout
- pattern_entry — trade named pattern (bullish/bearish/any)
- momentum_entry — consecutive same-direction bars (follow or fade)
- trend_strength_entry — ADX-confirmed direction via slope

### Ready-made Strategies (7)
- ma_cross_20_50, rsi_reversion_14, breakout_20
- momentum_follow_10, momentum_fade_10
- trend_strength_adx14, engulfing_entry

## Frontend Utils Bug Note (docs/issues/...)

`escapeHtml` issue notes exist in `docs/issues/frontend-utils-js-escapehtml-issue.md`.

## Patterns in _SECTIONS (frontconnect)

```python
_SECTIONS = {
    "index": ("account", "terminal", "totals", "positions", "orders", "deals", "watchlist"),
    "symbols": ("account", "terminal"),
    "research": ("account", "terminal", "watchlist"),
    "history": ("account", "terminal"),
}
_DEFAULT_SECTIONS = ("account", "terminal")
```

## Strategic AI Patterns Worth Knowing

1. **Bootstrapping execution paths**: MT5 initialize() called asynchronously on worker thread (can block beyond timeout)
2. **Connection caching**: symbols get cached after expensive `symbols_get()` bulk reads; TTL + explicit `/symbol-cache/clear`
3. **Host/container volumes**: gateway shares socket with external integration (peron_bridge uses 8888)
4. **Thread-safe SQLite**: RLock + busy_timeout=5000 + WAL
5. **Two-phase validations**: `/order/check` before `/order`
6. **Currency conversion**: pips → account currency via unit discipline (points × pip_size / point_size), never assume
7. **Bot grid search**: backtest is single-pass, but grid implies iteration
8. **Publisher flow separation**: market data (engine) + trading (handler) isolated causally

## Common Pitfalls This Project Solved

1. **Two sockets bind port on Windows** → GatewayServer rejects sharing, fails at startup
2. **Missing symbol info at quotes** → select symbol first before reading ticks/candles
3. **Case-sensitive UTF-8 symbol names** → cached name map (uppercase → canonical)
4. **Attributing numeric pip size from digit count** → broker's own `point` field preferred
5. **Cross-library request cycles leading to repr leaks inside dashboard history** → `/ui/` vs `/` API separation
6. **Unvalidated JSON body** → read body wrapping
7. **Wide request timeouts causing dead worker threads** → 30s idle keep-alive timeout
8. **Duplicate bootstrap payload in HTML comments** → `_TOKEN` regex distinguishes markers from ordinary comments

## Restructuring progress

- Stage 1 (physical reorganization) completed: integration packages moved under `backend/core/` (`server`, `frontconnect`, `database`).
- `backend/bot` alias removed.
- Default DB path still resolves to `backend/db/data/peron.db`.
- Frontend asset path fixed for the new package depth.
- See `backend/docs/restructure.md` for plan and remaining stages.
