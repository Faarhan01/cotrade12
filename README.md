# Cotrade

MetaTrader 5 gateway, real-time trading dashboard, research analytics, and algorithmic strategy engine.

Python drives the terminal through the official `MetaTrader5` package and exposes it three ways: a JSON REST API for autonomous agents, a research API for strategy work, and a vanilla HTML/CSS/JavaScript dashboard for users.

---

## Quick Start from Root

Run directly from the repository root:

```bash
# Start the development server & web dashboard (binds 0.0.0.0:3000)
python run.py

# Or explicitly start the dev server
python run.py dev

# Start on custom port and host
python run.py server --port 8890 --host 127.0.0.1

# Open the browser automatically on launch
python run.py server --open

# Inspect SQLite database statistics and verify integrity
python run.py db

# Print directory of all 73 active API & UI endpoints
python run.py routes
```

---

## Web Dashboard & Navigation

| Route | Description |
|---|---|
| `http://localhost:3000/` | **Account Overview** — Live balance, equity, margin, open positions, pending orders, closed deals, and streaming Market Watch. |
| `http://localhost:3000/ui/symbols` | **Instrument Browser** — Search and inspect specifications, contract sizes, tick sizes, swap rates, and derived pip values. |
| `http://localhost:3000/ui/research` | **Strategy & Pattern Lab** — Algorithmic pattern scanning, empirical follow-through edge calculation, and historical backtests. |
| `http://localhost:3000/ui/history` | **Account History** — Date-windowed deals, realised profit, commission, swap, and net profit. |
| `http://localhost:3000/ui/bot` | **Bot & Database Hub** — Stored trading strategies, backtest reports, individual trade logs, and database maintenance/vacuuming. |
| `http://localhost:3000/health` | **Health Probe** — Gateway status, active connections, and latency telemetry. |
| `http://localhost:3000/routes` | **Route Directory** — Interactive JSON catalog of all API routes. |

---

## Strategy & Bot CLI

You can also run algorithmic sweeps and pattern detectors directly from the CLI:

```bash
# Run a parameter sweep over an instrument
python run.py bot sweep EURUSD

# Run a technical pattern scan over historical bars
python run.py bot scan EURUSD
```

---

## Architecture

- **Backend**: Pure Python HTTP server with SSE event streaming (`/stream/portfolio`, `/stream/ticks`). Zero npm dependencies needed at runtime.
- **Frontend**: Plain Vanilla HTML, CSS, and modern JavaScript in `frontend/`. No build step or bundler needed.
- **Database**: Embedded SQLite in `backend/db/data/peron.db` running in WAL mode with auto-indexing.
- **Gateway**: Decoupled 3-layer architecture (`deamon` → `server` → `cony`).
