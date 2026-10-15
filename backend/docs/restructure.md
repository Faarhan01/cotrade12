# Restructuring Plan — `backend/`

> A staged, safety-first rewrite of how the `backend/` package is organised,
> how its modules find each other, and how its dependencies are wired.
>
> Nothing in `docs/` or `README.md` changes the wire format, database schema,
> or runtime behaviour of the daemon. Every stage is designed so the daemon
> still boots and `/health` still answers after it lands.

## Table of contents

1. [Why this plan exists](#why-this-plan-exists)
2. [Current state inventory](#current-state-inventory)
3. [Dependency analysis](#dependency-analysis)
4. [Target layout (final)](#target-layout-final)
5. [Core rules for every stage](#core-rules-for-every-stage)
6. [Stage plans (detailed)](#stage-plans-detailed)
7. [Compatibility policy](#compatibility-policy)
8. [Done definition and metrics](#done-definition-and-metrics)
9. [Out of scope](#out-of-scope)
10. [Appendix A — file move map](#appendix-a--file-move-map)
11. [Appendix B — ports and adapters (reference implementations)](#appendix-b--ports-and-adapters-reference-implementations)
12. [Appendix C — CLI command map](#appendix-c--cli-command-map)
13. [Appendix D — test matrix](#appendix-d--test-matrix)
14. [Appendix E — risk register](#appendix-e--risk-register)
15. [Glossary](#glossary)

---

## Why this plan exists

The backend grew from a single daemon script (`backend/gateway/deamon/__main__.py`)
into a 60+ module project. Several decisions that were right at that size now
fight against the project:

| Symptom | Where it shows today |
|---|---|
| Modules find each other by mutating `sys.path` at import time | `run.py`, `app.py`, `backend/bot/__init__.py`, `backend/tools/bot/*.py`, `backend/server/__init__.py`, `backend/gateway/deamon/__main__.py` |
| Persistence layer constructed deep inside handlers | `backend/server/handlers.py`, `bot_routes.py`, `db_routes.py`, `research.py` all contain `with Store() as store:` |
| MT5 engine internals leak into HTTP layer | `handlers.py` reads `engine._conn.get_connection_info()`; `frontconnect/views.py` calls `engine.clock_offset()` |
| Commands defined in 3 different parsers with overlapping logic | `run.py` argparse, `tools.bot.runner.main`, `python -m deamon` |
| Optional extensions loaded by bare `try/except ImportError` | `handlers.py` research/db/bot/dashboard registration blocks |
| README and code disagree about where `server/` lives | README describes `gateway/server/`, real layer is `backend/server/` |
| Frontend waits on same path discipline as the backend | `CONY_FRONTEND_DIR` traversal in handlers |
| Two import stories for the same physical package | ``from server import ...`` vs ``backend/server/__init__.py`` sys.path injection |

This document describes how to fix all of the above in seven independently
landable stages.

---

## Current state inventory

### Physical layout (today)

```
backend/
├── bot/                 (~ 210 LOC alias; re-exports tools.bot)
├── db/
│   ├── database/        (schema.py 245 LOC, store.py 466 LOC, __init__.py)
│   └── data/            (peron.db runtime file)
├── docs/                (Plan/todo, info, strategies)
├── frontconnect/        (assets.py, views.py ~267 LOC, __init__.py)
├── gateway/
│   ├── README.md
│   ├── cony/            (~ 1,400 LOC engine)
│   ├── deamon/          (~ 600 LOC, includes __main__.py 537 LOC)
│   ├── docs/api-reference.md
│   └── tools/           (verify, audit_*, lifecycle_test, introspect)
├── knowledgebase/       (~ 1,350 LOC of pure logic)
├── server/              (~ 800 LOC handlers + routes + validation)
└── tools/
    └── bot/             (~ 1,700 LOC across engine/patternchecker/runner/datafeed/live)
```

### Where code lives by responsibility (today)

| Responsibility | Modules that touch it |
|---|---|
| MT5 connection lifecycle | `gateway/cony/connection.py` only — good |
| MT5 operations | `gateway/cony/mt5_engine.py` — good (single owner) |
| HTTP routing | `server/routes.py` — good |
| HTTP transport (process, sockets, SSE) | `gateway/deamon/__main__.py` — good |
| Request handlers / validation / JSON shaping | `server/handlers.py`, `server/validation.py`, `server/errors.py` |
| HTML views (server-side render) | `frontconnect/views.py` |
| Strategic reference data (pure) | `knowledgebase/*` — good |
| Backtesting | `tools/bot/engine.py` |
| Pattern checking | `tools/bot/patternchecker.py` |
| Strategy/pattern scan CLI | `tools/bot/runner.py` |
| Live trading | `tools/bot/live.py` |
| HTTP market-data client | `tools/bot/datafeed.py` |
| Persistence | `db/database/store.py` |
| Configuration | `gateway/deamon/config.py` (partial); env reads scattered elsewhere |
| CLI surface | `run.py`, `tools/bot/runner.py`, `gateway/deamon/__main__.py` |

### Comment homes (today)

| Public symbol | Owner today | Notes |
|---|---|---|
| `ConnectionManager`, `MT5Engine`, `MarketBook` | `gateway/cony/` | Clean |
| `Router`, `RouteHandlers` | `server/` | `RouteHandlers` mixes transport-facing logic with MT5 |
| `Store` | `db/database/` | fine in isolation |
| `Strategy`, `Context`, `EntryRule`, etc. | `knowledgebase/` | pure, ideal |

---

## Dependency analysis

### Import edges (simplified)

```
gateway/deamon   ──► gateway/cony
gateway/deamon   ──► server            (via sys.path)
gateway/deamon   ──► server.errors / server.responses / server.streaming
server            ──► gateway/cony  (cony, enums)
server            ──► db.database   (Store)
server            ──► knowledgebase  (indicators, patterns, strategies)
server            ──► tools.bot     (datafeed, engine; research path)
server/research   ──► db.database
server/research   ──► knowledgebase / tools.bot
frontconnect      ──► server (responses, errors)
frontconnect      ──► (engine, at runtime)
tools/bot         ──► db.database (Store), knowledgebase, HTTP self-call
backend/bot       ──► tools.bot     (aliasing only)
run.py            ──► db.database, deamon, cony (cmd_routes)
app.py            ──► deamon.__main__
```

### Topology problems this reveals

1. **`server` is the hub, and it reaches in three directions**:
   `cony` (infra), `db` (infra), `knowledgebase` (domain), and `tools.bot` (infra/HTTP hybrid).
   Any change to a concrete class ripples up through `server/handlers.py`.
2. **`tools.bot.datafeed` calls back into the running daemon over HTTP while
   `tools.bot.runner` reuses the *same process's* SQLite.** Half the bot runs
   as an HTTP client, half as a direct library user. That duality exists
   because there is no shared `MarketDataPort`.
3. **`frontconnect` needs the whole `MT5Engine`.** Instead of asking for
   “account + positions + watchlist”, it is handed everything.
4. **Config is read in at least three places**: `gateway/deamon/config.py`,
   `tools/bot/datafeed.py` (`_resolve_base` reads `CONY_HOST`/`CONY_PORT`),
   and `run.py` (reads `PORT`, `HOST`, `CONY_PORT`).
5. **Extension loading** assumes a particular CWD/package layout, which is
   why `backend/server/__init__.py` does sys.path manipulation itself.

### Boundary violations catalogued in code (today)

- `backend/gateway/deamon/__main__.py`:
  - `from server import Router, RouteHandlers` → cross-package import, works
    only because `run.py`/`app.py` put `backend/` on `sys.path`.
  - `from deamon.config import config` (circular-ish: deamon is importing
    `deamon.config` which is fine but also `cony` indirectly through config? —
    config itself imports nothing internal).
- `backend/server/handlers.py`:
  - `from cony.mt5_engine import MT5Engine` purely for type hint; the real
    instance is passed in. Fine in isolation but it *documents* the concrete
    dependency in the HTTP layer.
  - calls `engine._conn.get_connection_info()` (infra internals in HTTP layer).
- `backend/tools/bot/datafeed.py`: reads `CONY_URL`, `CONY_HOST`, `CONY_PORT`.
- `backend/server/research.py`: defines `_gateway_fetch` (`urllib.request.urlopen`
  against the daemon) — HTTP calls from inside the HTTP server. This is the
  most inverted dependency in the project.

---

## Target layout (final)

```
backend/
├── core/
│   ├── __init__.py
│   ├── application/
│   │   ├── __init__.py
│   │   ├── ports.py
│   │   ├── container.py
│   │   ├── backtest_service.py
│   │   ├── scan_service.py
│   │   ├── validation_service.py
│   │   └── sizing_service.py
│   ├── config.py                # moved from gateway/deamon/config.py (or re-export)
│   ├── server/                  # moved from backend/server/
│   ├── frontconnect/            # moved from backend/frontconnect/
│   └── database/                # moved from backend/database/
├── db/
│   └── data/
│       └── peron.db
├── gateway/
│   ├── README.md
│   ├── cony/
│   ├── deamon/
│   ├── tools/
│   └── docs/
├── knowledgebase/
├── tools/
│   └── bot/
├── bot.py                       # optional 1-release shim (Stage 1.4)
└── cli/                         # added in Stage 4
```

Things deliberately kept exactly as they are:

- `backend/database/` and `backend/database/data/` stay separate: DB code lives
  under `database/`, but runtime data keeps its path under `backend/database/`.
- `backend/knowledgebase/` is untouched in shape (pure logic).
- `backend/gateway/cony/` and `backend/gateway/deamon/` keep their roles.
- Wire format, DB schema, and frontend remain identical.

## Core rules for every stage

1. The daemon must boot and `/health` must answer after each stage lands.
2. `knowledgebase/` keeps zero internal imports at all times.
3. `cony/` keeps zero imports of `server`, `core`, `db`, or `tools`.
4. Imports only move *downward*: `cli -> http/core -> application -> domain -> infra`.
5. One commit per stage, with a merged gate pass in CI before the next begins.
6. No file under `backend/` may mutate `sys.path` after Stage 4.
7. `docs/context.md` and the relevant `README.md` files are updated in every stage.

---

## Stage plans (detailed)

### Stage 0 — Baseline and guardrails

**Goal:** freeze the behaviour baseline so later stages can prove they didn't
change anything.

- [ ] Add a `tags/baseline` git tag at current `main`.
- [ ] Save golden `/health`, `/routes` output (minus `mtime`) under
  `backend/docs/reference/health.json`, `routes.json`.
- [ ] Run `gateway/tools/verify.py` once against the running daemon and save
  the pass/fail summary.
- [ ] Create `backend/docs/restructure.md` (this file) and `context.md`.

**Exit criteria:** a documented baseline the diff of any later stage can be
compare against.

### Stage 1 — Physical reorganization (no behaviour change)

**Goal:** move packages so the physical layout matches the dependency
direction. Logic untouched.

#### 1.0 Pre-move (import-chain surgery)

Before any `git mv`, fix the import roots in the three entrypoints so the new
locations will be findable:

```
run.py / app.py / gateway/deamon/__main__.py
  add to sys.path: backend/, backend/core/, backend/gateway/
```

This single change makes `/core/` importable regardless of CWD.

#### 1.1 Create `backend/core/`

```
backend/core/__init__.py    # module docstring only, no code
```

#### 1.2 Move packages

```bash
git mv backend/server        backend/core/server
git mv backend/frontconnect  backend/core/frontconnect
# database package now lives at backend/database/
```

`backend/database/data/` and `backend/database` itself stay.

#### 1.3 Update every internal import

Sed-like checklist (all symbols are already there; only the module paths
change):

| Old import | New import |
|---|---|
| `from server import Router, RouteHandlers` | `from core.server import Router, RouteHandlers` |
| `from server import validation as v` | `from core.server import validation as v` |
| `from server.errors import ...` | `from core.server.errors import ...` |
| `from server.responses import ...` | `from core.server.responses import ...` |
| `from server.streaming import ...` | `from core.server.streaming import ...` |
| `from frontconnect import register` (in handlers) | `from core.frontconnect import register` |
| `from frontconnect import assets, views` | `from core.frontconnect import assets, views` |
| `from database.store import Store` | `from core.database.store import Store` |
| `from database import Store` | `from core.database import Store` |
| `from database.schema import ...` | `from core.database.schema import ...` |
| `from database.store import new_run_id` | `from core.database.store import new_run_id` |
| `from tools.bot import ...` | unchanged (already `backend/tools/bot`) |
| `from knowledgebase import ...` | unchanged |
| `from cony import ...` | unchanged |

#### 1.4 Resolve the `backend/bot` shim

- Run `grep -rn "from bot\|import bot\b" backend/ run.py app.py`. (Expected
  hits: none besides `backend/bot/__init__.py`.)
- Delete `backend/bot/`.
- If any external consumer breaks, create `backend/bot.py` containing
  `from tools.bot import *` for exactly one release, then delete it.

#### 1.5 Deferred sys.path cleanup

- Keep all `sys.path` edits pointing at `backend/`, `backend/core/`,
  `backend/gateway/` only.
- `backend/core/server/__init__.py`'s own sys.path block becomes:
  ```
  for _d in (backend_dir, core_dir, gateway_dir): ...
  ```

#### 1.6 Path constants

- `core.database.store.DEFAULT_PATH` stays
  `backend/database/data/peron.db` (only the module moved).
- H in `handlers.py` (`_frontend_hint`, `_assets.FRONTEND_DIR`) — verify it
  still points at `repo/frontend/`. With the file now under
  `backend/core/server/`, the parent traversal
  `os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
  still resolves to `repo/`. Leave it, but note the fragility in a comment.

#### 1.7 Stage 1 gate (must pass before Stage 2)

- `python run.py routes` boots and lists every route.
- `python run.py db` prints stats and integrity = ok.
- Daemon with `CONY_AUTO_CONNECT=false`:
  `/health`, `/`, `/ui/{page}`, `/assets/*`, `/db/stats`,
  `/research`, `/bot/*` all respond 2xx.
- `py_compile` everything; `node --check` all frontend JS.

#### 1.8 Stage 1 rollback

Reverting the single commit restores the old layout exactly because every
move is `git mv`.

### Stage 2 — Introduce ports and an application layer

**Goal:** add the contracts (Protocols) and a thin service layer. No rewiring
yet.

#### 2.1 Add `core/application/ports.py`

See [Appendix B](#appendix-b--ports-and-adapters-reference-implementations)
for reference implementations. Ports: `MarketDataPort`, `MT5Port`,
`StrategyRepository`, `ReportRepository`, `PatternHitRepository`,
`AccountPort`, `MarketWatchPort`.

#### 2.2 Add `core/application/services/`

- `BacktestService` — wraps `tools.bot.engine` + data fetch.
- `PatternScanService` — wraps `tools.bot.patternchecker`.
- `ValidationService` — wraps `knowledgebase` strategy validation.
- `SizingService` — combines MT5 symbol info + `/calc/sizer` logic
  pulled out of `handlers.py` `calc_size`.

Each service takes its ports as constructor arguments, never reads env or
constructs `Store`.

#### 2.3 Container dataclass (stub)

```python
# core/application/container.py
@dataclass
class AppContainer:
    config: GatewayConfig
    engine: MT5Port          # placeholder, still cony.MT5Engine today
    strategy_repo: StrategyRepository
    report_repo: ReportRepository
    market_data: MarketDataPort
    backtest: BacktestService
    scans: PatternScanService
```

Keep a `build_container(config, engine)` factory that wires concrete impls —
reuse `cony.MT5Engine` and `core.database.Sqlite*Repository` (added in
Stage 3). In Stage 2 the repositories can be thin pass-through wrappers
around `Store`.

#### 2.4 Stage 2 gate

- New modules import cleanly.
- `core.application` has no import of `core.database` or `cony` other than
  in `container.py`/adapters (layering audit updated).
- Existing tests/gates stay green.

### Stage 3 — Dependency inversion

**Goal:** handlers, views, and bot logic read interfaces, never concrete
classes.

#### 3.1 Repository wrappers

```
database/repositories.py
  SqliteStrategyRepository(StrategyRepository)
  SqliteReportRepository(ReportRepository)
  SqlitePatternHitRepository(PatternHitRepository)
```

`core.server.handlers/bot_routes/db_routes/research` switch from
`with Store() as store:` to `container.*_repo`. Store stays public only for
maintenance (`vacuum`, `check_integrity`, `stats`) used by `db_routes`.

#### 3.2 MT5 adapter home

Move "engine owns ports" into `gateway/cony/adapter.py` (A thin class that
*implements* the ports using an `MT5Engine`). Then `Gateway` constructs
`engine_adapter = ConyMT5Adapter(engine)` and hands that to the container.

#### 3.3 Remove `engine._conn` from handlers

Replace `engine._conn.get_connection_info()` with `engine.connection_info()`
(small method addition to `MT5Engine`), and `engine.clock_offset()`-dependent
logic goes behind `AccountPort`. Never reach into `_name_cache`, `_conn`,
`_book` from `server/`.

#### 3.4 `tools.bot.*` refit

- `datafeed.fetch(symbol, ..., market_data=...)` — inject adapter.
- `runner.cmd_*` take `(container, args)`; remove internal `Store()` and
  `_resolve_base()` reads; `base = container.config.gateway_url`.
- `live.LiveTrader` takes `account/market_data/trading` ports instead of
  raw `datafeed`.

#### 3.5 Migration order within Stage 3 (one module per PR)

1. `core/server/db_routes.py` (simplest)
2. `core/server/bot_routes.py`
3. `core/server/handlers.py` (most handlers)
4. `core/server/research.py` (most complex — `_gateway_fetch` is the worst
   inverted dependency; replace with injected `MarketDataPort`)
5. `core/frontconnect/views.py`
6. `tools/bot/datafeed.py`, `runner.py`, `live.py`

#### 3.6 Stage 3 gate (per module)

- Module no longer imports `Store`, `MT5Engine`, or `datafeed` internals
  in a way that touches env/sockets.
- Existing behaviour golden matches baseline (diff `/routes`/`/health`,
  smoke test key workflows).
- Add one fake-based unit test per module moved.

### Stage 4 — Command registry / single CLI

See [Appendix C](#appendix-c--cli-command-map) for the command mapping.

#### 4.1 Add `cli/` layer

```
backend/gateway/cli/
├── __init__.py
├── __main__.py        # python -m cli
├── app.py             # argparser/typer root
└── commands/
    ├── serve.py
    ├── db.py
    ├── routes.py
    ├── sweep.py
    ├── scan.py
    ├── list.py
    ├── report.py
    └── doctor.py
```

Each command function is `def run(container, args) -> int`.

#### 4.2 Migrate

- `run.py` becomes:
  ```python
  from cli.app import main
  sys.exit(main())
  ```
  (keeping `python run.py` behaviour intact).
- Delete the argparse tree from `tools.bot.runner` and `gateway/deamon/__main__.py`
  except the daemon's `main()` that starts sockets (called by `cli/commands/serve.py`).
- `python -m tools.bot.runner` prints deprecation to stderr and calls `cli`.

#### 4.3 sys.path removal (the payoff)

After stages 3–4 land, delete every `sys.path.insert(...)` block and
install the package instead:

```bash
# repo root
pip install -e backend/
```

Add `backend/pyproject.toml` declaring the packages so imports resolve as
`cotrade.*`? No — keep *internal* imports bare (`server`, `cony`) for low
churn; the editable install keeps the existing bare import names working
because the package root is `backend/`. Only the `core/` * umbrella package
needs care: it lives under `backend/`, so `core` is a top-level package by
virtue of `backend/` being on `sys.path` — which the editable install *provides*,
and is the one reason we still keep `backend/` on the path, now via
packaging metadata instead of ad-hoc inserts.

#### 4.4 Stage 4 gate

- `grep -R "sys.path.insert" backend/` returns nothing.
- CLI parity test passes (see [Appendix C](#appendix-c--cli-command-map)).

### Stage 5 — Config and composition root

#### 5.1 Centralise env reads
Move all reads in:
- `gateway/deamon/config.py` (already authoritative for gateway)
- `tools/bot/datafeed.py` (`_resolve_base`)
- `run.py` / `app.py`

into `core/config.py::GatewayConfig`. Anything else uses `container.config.*`.

#### 5.2 `core/composition.py::build_container(config)`

Constructs every concrete implementation and service, returning an
`AppContainer`. This is the *only* place that knows about MT5, SQLite,
HTTP, or filesystem (frontend dir) in one place.

#### 5.3 Stage 5 gate
- Tests construct an `AppContainer` with fakes in <1 ms.
- `CONY_URL`/`CONY_HOST`/`MT5_LOGIN` etc. set during `core/config.py`
  loading; later modules never read env.

### Stage 6 — Plugin registry

#### 6.1 `core/plugins.py`

Replace try/except blocks in `core/server/handlers.py::setup_routes` with:

```python
EXTENSIONS = ("database", "research", "bot", "dashboard")
for name in EXTENSIONS:
    try:
        mod = importlib.import_module(f"core.extensions.{name}")
    except ImportError as e:
        logger.warning("extension %r unavailable: %s", name, e)
        continue
    added = mod.register(router, container)
    ...
```

Move the registration functions into `core/extensions/<name>.py` wrappers
that import the existing `core.server.db_routes`, `research`, `bot_routes`,
and delegate to `core.frontconnect.register`. This unifies the contract.

#### 6.2 Stage 6 gate

Behaviour identical: each extension returns a route count or raises a clear
`ImportError`; a failing extension never stops the others.

### Stage 7 — Observability and testing

#### 7.1 Tests to add (new tree `backend/tests/`)

See [Appendix D](#appendix-d--test-matrix).

#### 7.2 Tooling

```toml
# backend/pyproject.toml
[project]
name = "cotrade-backend"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = ["MetaTrader5 ; sys_platform == 'win32'"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
target-version = "py311"
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = false
warn_unused_ignores = true
```

---

## Compatibility policy

- `python run.py <cmd>` keeps working through Stage 4 (shim).
- `from bot import ...` keeps working through Stage 1 only (shim through
  1 release).
- JSON responses never change shape. If a new field is needed for isolation
  (e.g. `engine.connection_info()` output), it must mirror `_conn` exactly.
- Database schema and file path identical throughout.
- API routes (`/`, `/ui/*`, `/assets/*`, `/db/*`, `/bot/*`, `/research/*`)
  keep each pattern string identical. Implementation can move, the pattern
  list is the contract.

---

## Done definition and metrics

### Quantitative invariants (CI-checked)

| Check | Tool | Threshold |
|---|---|---|
| `sys.path` mutations | grep | 0 occurrences outside `pyproject` and `tests/conftest.py` |
| Layering violations | new `audit_layering.py` | 0 `engine._*` / `store._conn` / `os.environ.get` (outside `core/config.py`) |
| Cony importing http/core/db | grep | 0 |
| Knowledgebase importing project modules | grep | 0 |
| Routes count | `python run.py routes` | identical to baseline (`95` today) |
| Health shape | diff | byte-identical to baseline on keys |

### Behavioural

- Daemon boots end-to-end on a connected MT5 terminal (Windows).
- Every endpoint in `gateway/tools/verify.py` passes.
- `tools.bot.runner sweep` and `scan` produce identical reports to baseline.
- Demo lifecycle test places & closes one order successfully.

### Quality

- `ruff` clean on all `backend/` Python.
- `mypy` runs (non-fatal first) over `core/application` and `knowledgebase`.
- At least one fake-based test per service module runs in CI (<5s total).

---

## Out of scope

- Process/microservice split.
- Database engine changes (SQLite → Postgres).
- Replacing stdlib HTTP with an ASGI framework.
- Frontend build system or framework rewrite.
- API versioning or path changes.
- Any change to the strategy engine's math (`knowledgebase/`, `tools/bot/engine.py`
  simulation semantics) — isolation work moves call sites, not algorithms.

---

## Appendix A — file move map

| Before | After | Stage |
|---|---|---|
| `backend/bot/__init__.py` | deleted (shim optional) | 1.4 |
| `backend/database/schema.py` | `backend/database/schema.py` | 1.2 |
| `backend/database/store.py` | `backend/database/store.py` | 1.2 |
| `backend/database/__init__.py` | `backend/database/__init__.py` | 1.2 |
| `backend/frontconnect/__init__.py` | `backend/core/frontconnect/__init__.py` | 1.2 |
| `backend/frontconnect/assets.py` | `backend/core/frontconnect/assets.py` | 1.2 |
| `backend/frontconnect/views.py` | `backend/core/frontconnect/views.py` | 1.2 |
| `backend/server/__init__.py` | `backend/core/server/__init__.py` | 1.2 |
| `backend/server/routes.py` | `backend/core/server/routes.py` | 1.2 |
| `backend/server/handlers.py` | `backend/core/server/handlers.py` | 1.2 |
| `backend/server/validation.py` | `backend/core/server/validation.py` | 1.2 |
| `backend/server/streaming.py` | `backend/core/server/streaming.py` | 1.2 |
| `backend/server/research.py` | `backend/core/server/research.py` | 1.2 |
| `backend/server/responses.py` | `backend/core/server/responses.py` | 1.2 |
| `backend/server/errors.py` | `backend/core/server/errors.py` | 1.2 |
| `backend/server/bot_routes.py` | `backend/core/server/bot_routes.py` | 1.2 |
| `backend/server/db_routes.py` | `backend/core/server/db_routes.py` | 1.2 |
| `gateway/deamon/config.py` (logical) | `core/config.py` (re-export retained) | 5.1 |
| (new) | `core/application/ports.py` | 2.1 |
| (new) | `core/application/container.py` | 2.3 |
| (new) | `core/application/services/*` | 2.2 |
| (new) | `backend/database/repositories.py` | 3.1 |
| (new) | `gateway/cony/adapter.py` | 3.2 |
| (new) | `backend/gateway/cli/*` | 4.1 |
| (new) | `backend/core/composition.py` | 5.2 |
| (new) | `backend/core/plugins.py` | 6.1 |
| (new) | `backend/core/extensions/*` | 6.1 |

### New (empty) packages to create

- `backend/core/__init__.py`
- `backend/core/application/__init__.py`
- `backend/gateway/cli/__init__.py`
- `backend/tests/__init__.py`

---

## Appendix B — ports and adapters (reference implementations)

### `core/application/ports.py`

```python
from __future__ import annotations
from typing import Protocol, Optional, List, Dict, Any
from datetime import datetime
from knowledgebase.patterns import Bar
from knowledgebase.strategies import Strategy

class MarketDataPort(Protocol):
    def instrument(self, symbol: str) -> Dict[str, Any]: ...
    def candles(self, symbol: str, timeframe: str, count: int,
                days: Optional[int] = None) -> List[Bar]: ...

class MT5Port(Protocol):
    def is_connected(self) -> bool: ...
    def connection_info(self) -> Dict[str, Any]: ...
    def clock_offset(self) -> Optional[float]: ...
    def get_symbol_info(self, symbol: str) -> Dict[str, Any]: ...

class AccountPort(Protocol):
    def account_info(self) -> Dict[str, Any]: ...
    def get_positions(self, **kw) -> List[Dict[str, Any]]: ...
    def get_orders(self, **kw) -> List[Dict[str, Any]]: ...

class StrategyRepository(Protocol):
    def load(self, name: str) -> Optional[Strategy]: ...
    def save(self, strategy: Strategy) -> int: ...
    def list(self) -> List[Dict[str, Any]]: ...
    def delete(self, name: str) -> bool: ...

class ReportRepository(Protocol):
    def save(self, report: Dict[str, Any]) -> int: ...
    def list(self, *, strategy=None, verdict=None,
             limit: int = 100) -> List[Dict[str, Any]]: ...
    def best(self, limit: int = 20) -> List[Dict[str, Any]]: ...

class PatternHitRepository(Protocol):
    def save_hits(self, run_id, symbol, timeframe, hits): ...
    def query_hits(self, pattern=None, symbol=None, limit=500): ...

class TradingPort(Protocol):
    def check_order(self, request): ...
    def send_order(self, request): ...
    def close_position(self, ticket, ...): ...
```

### Adapter example (Stage 3.2)

```python
# gateway/cony/adapter.py
from core.application.ports import MT5Port, MarketDataPort, AccountPort
from cony.mt5_engine import MT5Engine
from knowledgebase.patterns import Bar, to_bars
from tools.bot import datafeed

class ConyMT5Adapter(MT5Port, MarketDataPort, AccountPort, TradingPort):
    def __init__(self, engine: MT5Engine, config: GatewayConfig):
        self._engine = engine
        self._config = config

    def is_connected(self) -> bool:
        return self._engine.is_connected

    def connection_info(self) -> dict:
        return self._engine._conn.get_connection_info()  # adapter is allowed

    def instrument(self, symbol):
        info = datafeed.instrument_from_engine(self._engine, symbol)
        ...

    def candles(self, symbol, timeframe, count, days=None):
        raw = self._engine.copy_rates_range(...) if days else ...
        return to_bars(raw)
```

The point: the body of `datafeed.fetch` ends up here, behind the port, so
`tools/bot` no longer reads env and the same adapter serves HTTP + bot.

### Adapter isolation rule

Adapters are the *only* modules in the codebase allowed to:
- import `cony` concretely
- import `core.database.Store` (well, repositories do that)
- read `GatewayConfig`
- perform `urllib`/`socket`/`sqlite` I/O

Everything else uses ports. This invariant is enforced in Stage 7 by a grep
audit (`audit_layering.py`).

---

## Appendix C — CLI command map

| Today (what users type) | After (single CLI) | Delegates to |
|---|---|---|
| `python run.py` | `python -m cli` | `serve` (defaults) |
| `python run.py server --port P --host H --open` | `python -m cli serve --port P --host H --open` | daemon main |
| `python run.py dev` | `python -m cli serve --dev` | daemon main |
| `python run.py db` | `python -m cli db` | `Store.stats()` + `check_integrity()` |
| `python run.py routes` | `python -m cli routes` | builds router, prints route list |
| `python run.py bot sweep EURUSD` | `python -m cli sweep EURUSD` | `BacktestService` + reports |
| `python run.py bot scan EURUSD` | `python -m cli scan EURUSD` | `PatternScanService` |
| `python -m tools.bot.runner list` | `python -m cli list` | repositories |
| `python -m tools.bot.runner report ...` | `python -m cli report ...` | repositories |
| `python -m deamon` | `python -m cli serve` | daemon main |
| `python app.py` | `python -m cli serve --host 0.0.0.0` (shimmed via `app.py`) | daemon main |

### Parity test (`tests/cli/test_parity.py`)

For every migration above, run the *old* path and the *new* path side by side
in a subprocess, on a fixture DB + no-MT5 daemon, and assert exit code and
JSON-equivalent stdout agree. Keep this test until 1 release after
deprecation.

---

## Appendix D — test matrix

### New test tree

```
backend/tests/
├── conftest.py                 # fixtures + fakes
├── fakes/
│   ├── fake_mt5.py             # implements MT5Port + MarketDataPort
│   ├── fake_repos.py           # in-memory repositories
│   └── fake sleeves         # (optional) partial
├── core/
│   ├── application/
│   │   ├── test_backtest_service.py
│   │   ├── test_scan_service.py
│   │   └── test_validation_service.py
│   └── database/
│       └── test_sqlite_repositories.py   # against tmp_path db
├── transport/
│   └── test_http_contracts.py  # real stdlib server, fake engine
├── cli/
│   └── test_parity.py
└── knowledgebase/
    ├── test_indicators.py       # numerical edge cases
    ├── test_patterns.py
    └── test_strategies.py
```

### What gets tested (minimum)

| Module | Current state | Target |
|---|---|---|
| `knowledgebase/indicators` | 0 tests | pure functions, equal length on every input incl. warm-up |
| `knowledgebase/patterns` | 0 tests | empty input, single bar, all-patterns-called-once |
| `knowledgebase/strategies` | 0 tests | `to_dict`/`from_dict` round trip, ENTRY_RULES register |
| `tools/bot/engine.run` | 0 tests | golden trades for a fixture Bar series |
| `tools/bot/patternchecker` | 0 tests | bonferroni threshold, `_grade`, `_consistent` |
| `core.application.services` | new | happy path + insufficient-data paths match verdict policy |
| repositories | new | round trip insert/read against tmp SQLite |
| HTTP contracts | verify.py (live) | fake-engine mode, schema golden |

### Execution policy

- Fast tests (`knowledgebase`, `application`, repositories with tmp_path) run
  on every commit; aim <5s.
- Integration tests (`verify.py` against a running daemon) run nightly or
  manually; depend on MT5 Windows.
- No test may touch the real `backend/database/data/peron.db`.
- Coverage target: >=80% on new `core/application` from Stage 2 onwards.

---

## Appendix E — risk register

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Broken import after `git mv` leaves daemon unable to start | High | Stage 1.0 fixes import roots *before* moving; one commit; rollback = revert |
| R2 | `verify.py` (live MT5) not available in Linux CI | Med | Hold live gates as manual/nightly; fast tests use fakes (Stage 7.1) |
| R3 | `tools.bot` HTTP-self-calls during backtests depend on live daemon | High | Stage 3.4 injects `MarketDataPort`; fakes let tests run offline |
| R4 | Two `server` implementations linger (doc vs code) | Med | Stage 1.2 makes `core.server` canonical; README updated the same commit |
| R5 | `backend/bot` deletion breaks an external caller | Low | one-release shim (Stage 1.4) |
| R6 | Faking MT5 hides real broker behaviour | Med | kept integration tests against demo account (nightly) |
| R7 | `engine._conn` removal causes `KeyError` in dashboards | Med | add `MT5Engine.connection_info()` method with byte-identical payload first |
| R8 | sys.path removal breaks an undocumented import location | Med | run `grep -R sys.path` and `grep -R "backend\\.server\|gateway\\.deamon"` in all files (incl. notebooks) before Stage 4 |
| R9 | Plugin registry swallows a real startup bug and shows empty routes | Med | log full traceback + fail-fast on `CONY_STRICT_EXTENSIONS=1` |
| R10 | Ruff/mypy strictness blocks legitimate code | Low | start with lint on *new* files only (ruff `--diff` baseline) then tighten |

### Monitoring during migration

- Keep a `MIGRATION_STATE.md` (one line per stage) updated at every commit:
  `stage=1, step=1.2 done, gate=routes ✅, db ✅`.
- Re-run `verify.py` against the dev daemon after each stage lands (it doubles
  as the smoke test).

---

## Glossary

- **Composition root**: the single place in the program that knows which
  concrete classes implement which interfaces (lives in `core/composition.py`
  after Stage 5).
- **Port**: a `typing.Protocol` describing a capability (e.g.
  `MarketDataPort`). Owns no implementation.
- **Adapter**: the concrete class bridging a port to a real library
  (`ConyMT5Adapter`, `SqliteStrategyRepository`).
- **container**: an `AppContainer` dataclass holding injected ports + services.
- **Service**: stateless application use-case object taking ports; never reads
  env, never opens sockets/files/DB directly.
- **Extension**: an optional feature module with
  `register(router, container) -> int`.
- **Domain**: `knowledgebase/` — pure logic, no I/O.
- **Infrastructure**: `cony/`, `db/`, `frontconnect assets`, HTTP routes.
- **Layer**: ordered from infrastructure up to HTTP/CLI; imports only
  downward.
- **Stage gate**: a checklist of tests/builds that must pass before the next
  stage may start.

---

(End of plan.)