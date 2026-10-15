# Local Instructions

Run the gateway locally:

```bash
python app.py
# or
python run.py
```

Run without MT5 for UI development:

```bash
CONY_AUTO_CONNECT=false python app.py
```

Database diagnostics:

```bash
python run.py db
```

Route listing:

```bash
python run.py routes
python cli.py routes
```

Validation commands:

```bash
cd backend
PYTHONPATH=. pytest -q tools/simulatedtester/tests
PYTHONPATH=. python gateway/tools/audit_layering.py
cd ..
for f in frontend/assets/js/lib/*.js frontend/assets/js/pages/*.js; do node --check "$f"; done
```

Notes:
- Live MetaTrader 5 usage requires the official `MetaTrader5` Python package and a connected terminal.
- CI/container/service-stack items are intentionally out of scope for local use.

Self-contained tester:

```bash
PYTHONPATH=backend/tools/simulatedtester python backend/tools/simulatedtester/test_simulator.py
```
