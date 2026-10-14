# Testing Documentation

## Overview
This document describes the testing procedures and checks for the Cotrade frontend and backend systems.

## Testing the "No Hardcoding" Feature

### How to Verify
The audit tool `tools/audit_hardcode.py` checks for hardcoded paths, ports, MT5 constants, and magic numbers:

```bash
python tools/audit_hardcode.py
```

**Expected Output:**
```
No hardcoded paths, ports, MT5 constants or magic numbers found.
```

### What It Checks
- Absolute Windows paths (e.g., `C:\path\to\something`)
- Hardcoded port numbers (8888, 8890, 8899)
- MT5 literals outside `cony/enums.py` (e.g., `TRADE_RETCODE_*`, `ORDER_TYPE_*`, `TIMEFRAME_*`)
- Long numeric literals that could be magic numbers or account numbers

### Running the Verification
```bash
# From the root directory
cd /workspaces/Countr
python backend/gateway/tools/audit_hardcode.py
```

**Result:** Should output: `No hardcoded paths, ports, MT5 constants or magic numbers found.`

## Frontend Testing

### JavaScript Syntax Check
```bash
node --check frontend/assets/js/lib/shell.js
node --check frontend/assets/js/lib/format.js
node --check frontend/assets/js/lib/dom.js
node --check frontend/assets/js/lib/api.js
node --check frontend/assets/js/lib/chart.js
node --check frontend/assets/js/pages/dashboard.js
node --check frontend/assets/js/pages/research.js
node --check frontend/assets/js/pages/bot.js
node --check frontend/assets/js/pages/symbols.js
node --check frontend/assets/js/pages/history.js
```

**Expected:** All files pass without errors

### HTML Page Structure
Verify all HTML pages have the required structure:
- `#include head` marker
- `#bootstrap` marker (replaced with JSON block)
- `#include header` marker
- `shell.js` script inclusion
- Proper `<title>` tag

### Frontend Pages Checklist
- `frontend/pages/index.html` - Account overview
- `frontend/pages/research.html` - Strategy work
- `frontend/pages/symbols.html` - Instrument browser
- `frontend/pages/bot.html` - Bot & Database Hub
- `frontend/pages/history.html` - Account history

## Backend Testing

### Python Syntax Check
```bash
python -m py_compile backend/dashboard/__init__.py
python -m py_compile backend/dashboard/views.py
python -m py_compile backend/database/store.py
# ... all backend Python files
```

**Expected:** All files compile without errors

### Key backend tests:
- `python run.py db` - Database statistics and integrity
- `python run.py routes` - Print all API routes
- `python run.py server --port 3000` - Start the server
- `python tools/audit_coverage.py` - Check MT5 package coverage (requires MT5)

## Known Testing Gates

### Critical Gates (require MT5 terminal)
- `python tools/verify.py` - 174 end-to-end checks
- Requires live MetaTrader 5 terminal connected

### Gates Without MT5
- `python run.py db` - Database stats and integrity check
- `python run.py routes` - API route directory
- `python tools/audit_hardcode.py` - No hardcoded paths/ports/constants
- `python tools/audit_coverage.py` - Package function coverage (may fail without MT5)

## Frontend Testing Without Server

### Static Verification
```bash
# Check JS syntax
node --check frontend/assets/js/lib/*.js
node --check frontend/assets/js/pages/*.js

# Check HTML structure
grep -c '#bootstrap' frontend/pages/*.html  # Should be 5 (one per page)
grep -c 'shell.js' frontend/pages/*.html     # Should be 5 (one per page)
grep 'casefold' backend/server/handlers.py    # Case-insensitive search
```

### CSS Validation
```bash
# All CSS files should exist and have content
frontend/assets/css/base.css
frontend/assets/css/layout.css
frontend/assets/css/components.css
frontend/assets/css/pages/dashboard.css
frontend/assets/css/pages/research.css
frontend/assets/css/pages/symbols.css
```

## Testing Workflow

1. **Static Checks:** Run JS syntax and CSS validation
2. **Frontend Checks:** Verify HTML structure and page content
3. **Backend Checks:** Run database stats and route directory
4. **Hardcoding Check:** Run `audit_hardcode.py`
5. **Integration:** Start server and test key endpoints

## Recent Improvements Verified

- Timezone-aware datetime in 8 backend files
- Case-insensitive MT5 symbol matching (3 occurrences of `casefold()`)
- Atomic database upserts with `ON CONFLICT`
- History page `/ui/history` with proper data flow
- Shell.js shared header/footer on all 5 frontend pages
- Frontconnect backend folder rename from `dashboard`
- Audit hardcode passes: no hardcoded paths/ports/constants
- Research sweep requires explicit `symbol` parameter
- No hardcoded paths/ports/constants in the codebase
Regression bugs from port changes prevented
