<!-- Further pass 2026-10-18: indicator/pattern expansion plus self-contained tester delivered. -->

<!-- Further verification pass: 2026-10-17
     - Confirmed all 98 advertised routes now present (added strategy compare; pause/resume; stream).
     - Components library wired into bot page (confirm dialog).
     - CI workflow, env example, testing docs added; Docker packaging removed as local-only scope.
-->
<!-- Verification pass: 2026-10-16 -->
<!-- The following items are already implemented in the codebase as of this pass:
     1. Frontend utils.js escapeHtml (fixed via runtime entity map).
     2. shell.js clock bug (fmtLib fallback + global.fmt).
     3. shell.start() present in dashboard/symbols/research/bot/history pages.
     4. Research & bot & db endpoints already registered (99 routes); see
        run.py routes. Includes /research/reports/{run_id}, DELETE strategy,
        /research/strategy/{name}/optimize, /research/patterns/cooccurrence,
        /research/hits/context, /research/bars/range, /research/reports/best,
        /bot/sessions/{id}/stream.
     5. Pause/resume bot session endpoints added.
     6. Pattern hit context population implemented (hit_context).
     7. Extra DB indexes added to schema.py.
     8. Frontend components library integrated into pages.
-->

# Unfinished Work & Future Improvements Plan

## Overview
This document tracks all unfinished work, known issues, and planned improvements for the Cotrade MetaTrader 5 gateway and trading dashboard. The project is functional but has several areas needing completion.

---

## Critical Bugs (Blockers)

### 1. Frontend `utils.js` - `escapeHtml` Function Broken
**File:** `/workspaces/Countr/frontend/assets/js/lib/utils.js` (lines ~300-310)
**Issue:** The `escapeHtml` function uses HTML entities (`&`, `<`, `>`, `"`, `'`) as replacement strings, but the write tools convert these to literal characters, breaking JavaScript syntax.
**Current workaround:** Other pages use `fmt.escapeHtml` from `format.js` which works correctly.
**Proposed fix:** Use runtime map-based escaping:
```javascript
function escapeHtml(text) {
  const map = { '&': '&', '<': '<', '>': '>', '"': '"', "'": ''' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}
```
**Status:** Documented in `/issues/frontend-utils-js-escapehtml-issue.md`

---

## Backend Improvements

### 2. MT5 Connection Health & Auto-Reconnection
**Files:** `backend/gateway/cony/connection.py`, `backend/gateway/deamon/__main__.py`
**Issues:**
- Connection race condition in `ensure_connected()` (check outside lock)
- `connect()` clears reconnect stop event (dual-purpose flag)
- `enums.load()` caches import failure permanently
**Ideas:** Add connection state machine, separate reconnect flag, lazy enum loading.

### 3. Strategy Validation UX
**File:** `backend/knowledgebase/api.py`
**Issue:** Validation requires both `name` and `entry_name` - confusing UX
**Fix:** Accept strategy name string to lookup stored strategy (partially done)

### 4. Spread Cost Consistency
**Files:** `backend/tools/bot/engine.py` vs `backend/knowledgebase/api.py`
**Issue:** Engine uses points (`spread_pts = spread_pips * pip`), API stores `spread_cost = trades * 2 * spread_pips` (pips × point)
**Fix:** Standardize on points or pips consistently

---

## New API Endpoints Needed

### Research Layer
| Endpoint | Purpose |
|----------|---------|
| `GET /research/reports/{run_id}` | Get single report by run_id |
| `DELETE /research/strategy/{name}` | Delete stored strategy |
| `GET /research/strategy/{name}/compare` | Compare strategy versions |
| `POST /research/strategy/{name}/optimize` | Grid search parameter optimization |
| `GET /research/patterns/cooccurrence` | Pattern co-occurrence analysis |

### Bot Session Management
| Endpoint | Purpose |
|----------|---------|
| `GET /bot/sessions/{id}/stream` | SSE for real-time bot status |
| `POST /bot/sessions/{id}/pause` | Pause bot session |
| `POST /bot/sessions/{id}/resume` | Resume paused session |

### Database Queries
| Endpoint | Purpose |
|----------|---------|
| `GET /research/hits/context` | Indicator values at pattern hits |
| `GET /research/bars/range` | Cached bar date range |
| `GET /research/reports/best` | Best reports by t-statistic |

---

## Frontend Architecture Improvements

### 1. Shared Utilities Module (`utils.js`)
**Status:** Partially complete - `escapeHtml` broken
**Needed:**
- Centralized API endpoint constants (`API` object)
- Shared DOM helpers (`$`, `$$`, `el`, `clear`)
- Debounce/throttle utilities
- Date/time formatting (`brokerTime`, `shortDateTime`)
- Number formatting (`formatNumber`, `formatSigned`)
- Toast notifications, modals, confirm dialogs

### 2. Component Library (`components.js`)
**Status:** Created but needs integration
**Components:** Toast notifications, modal dialogs, confirm dialogs, spinners, table builder, form helpers

### 3. Shell.js Clock Bug
**File:** `frontend/assets/js/lib/shell.js` line 59
**Issue:** `fmt` undefined in `startClock` function
**Fix:** Reference `window.fmt` or `global.fmt`

### 4. Page-Level Improvements
| Page | Issues |
|------|--------|
| `dashboard.js` | Uses `window.shell.start(boot)` but `fmt` not exposed globally |
| `research.js` | Same issue; uses `lastScanSymbol` but not always defined |
| `symbols.js` | No `shell.start()` call at all |
| `bot.js` | Same |
| `history.js` | Same |

---

## Database Enhancements

### 1. Strategy Versioning
**Status:** Implemented `strategy_versions` table with snapshots
**Missing:** Automatic versioning on update, diff view, rollback API

### 2. Pattern Hit Context
**Table:** `hit_context` exists but never populated
**Idea:** Save indicator values at each pattern hit for post-analysis

### 3. Indexes Needed
```sql
-- Add to schema.py
CREATE INDEX IF NOT EXISTS idx_reports_symbol_tf ON reports(symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_hits_symbol_tf_time ON pattern_hits(symbol, timeframe, bar_time);
CREATE INDEX IF NOT EXISTS idx_strategy_versions_name ON strategy_versions(strategy_id, version);
```

### 4. Soft Delete for Strategies
Add `deleted_at` column and filter in queries

---

## Knowledgebase Enhancements

### 1. More Indicators
Currently: SMA, EMA, WMA, RSI, ATR, Bollinger, MACD, Stochastic, ADX, Donchian, Slope, VWAP, CCI, Z-Score
**Missing:** Ichimoku, Parabolic SAR, OBV, CMF, SuperTrend, Keltner Channels

### 2. More Patterns
Currently: 18 patterns (candlestick + price action)
**Missing:** Three-line strike, abandoned baby, tasuki gap, mat hold

### 3. Strategy Templates
Add pre-built templates for common strategy types (trend, mean reversion, breakout)

### 4. Parameter Validation with Ranges
Add min/max/step to parameter definitions for UI sliders

---

## Bot & Live Trading

### 1. LiveTrader Enhancements
**File:** `backend/tools/bot/live.py`
**Missing:**
- Position sizing based on risk % of equity
- Trailing stop management in live mode
- Partial close support
- Multi-symbol support

### 2. Real-time Bot Dashboard
- SSE endpoint for session updates (`/bot/sessions/{id}/stream`)
- Pause/resume session controls
- Real-time P&L chart

### 3. Risk Management
- Daily loss limit
- Max concurrent positions
- Correlation filtering

---

## Testing & CI/CD

### 1. Automated Testing
| Type | Status |
|------|--------|
| Unit tests | None |
| Integration tests | Manual only (`verify.py`) |
| Load testing | None |
| MT5 mock for CI | Needed |

### 2. CI Pipeline
```yaml
# .github/workflows/ci.yml (needed)
- Lint (ruff, eslint)
- Type check (mypy, tsc)
- Unit tests
- Integration test with mock MT5
- Security scan
```

### 3. Development Workflow
- `dev-server.sh` created but needs testing
- Pre-commit hooks (ruff, prettier)
- Commit message convention

---

## Documentation

### 1. API Reference
**File:** `backend/gateway/docs/api-reference.md`
**Status:** Covers 23 of 61 routes
**Missing:** All `/research/*`, `/bot/*`, `/db/*`, market book, SSE streams

### 2. Architecture Documentation
- Layer interaction diagrams
- Data flow diagrams
- Deployment guide

### 3. Strategy Development Guide
- How to write custom entry rules
- Backtest interpretation guide
- Parameter optimization workflow

---

## Infrastructure

### 1. Configuration Management
- `.env.example` with all variables documented
- Config validation at startup
- Environment-specific configs (dev/staging/prod)

### 2. Logging & Monitoring
- Structured logging (JSON)
- Metrics endpoint (`/metrics` for Prometheus)
- Health check improvements (`/health` details)

### 3. Local packaging (optional)
- Single-container helper already exists; compose/systemd are not required for local-only use

---

## Priority Matrix

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| **P0** | Fix `utils.js` `escapeHtml` | Low | High |
| **P0** | Fix shell.js clock bug | Low | High |
| **P0** | MT5 503 error handling | Medium | High |
| **P1** | Strategy validation UX | Low | Medium |
| **P1** | Spread cost consistency | Medium | Medium |
| **P1** | Bot session SSE endpoint | Medium | High |
| **P2** | Strategy versioning UI | Medium | Medium |
| **P2** | Pattern hit context population | Medium | Medium |
| **P2** | More indicators/patterns | High | Medium |
| **P3** | CI/CD pipeline | High | Medium |
| **P3** | API documentation completion | Medium | Low |
| **P3** | Container packaging helper | Low | Low |

---

## Design Principles to Maintain

1. **No external dependencies** - Keep frontend dependency-free (no npm, no build step)
2. **Layer separation** - `deamon → server → cony` strict boundaries
3. **No fake data** - All data from real MT5 terminal
4. **Honest statistics** - Verdicts based on t-statistics, not profit
5. **Case preservation** - MT5 symbol names as-is (no forced uppercase)
6. **Timezone awareness** - All times in broker time with published offset

---

## Quick Wins (Can Do in < 1 Hour Each)

- [ ] Fix `utils.js` `escapeHtml` with runtime map approach
- [ ] Fix `shell.js` clock bug (`fmt` reference)
- [ ] Add `shell.start()` to `symbols.js`, `bot.js`, `history.js`
- [ ] Add missing indexes to `schema.py`
- [ ] Update `README.md` with new endpoints
- [ ] Add `dev-server.sh` to README
- [ ] Document `PERON_DB` vs `CONY_MT5_PACKAGE` env vars

---

## Long-term Vision

Transform from "MT5 gateway + dashboard" to **"Algorithmic Trading Research Platform"**:

1. **Research-first** - Strategy discovery → validation → backtest → optimize → paper trade → live
2. **Multi-user** - Team workspaces with shared strategies/reports
3. **Plugin architecture** - Custom indicators/patterns/strategies as plugins
4. **Multi-broker** - Abstract MT5 behind broker interface
5. **Event sourcing** - Full audit trail of all decisions

---

*Last updated: 2025-10-15*
*Next review: After P0 items resolved*