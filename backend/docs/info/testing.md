# Testing

Fast tests:
```bash
cd backend && PYTHONPATH=. pytest -q
```

Layering audit:
```bash
cd backend && PYTHONPATH=. python gateway/tools/audit_layering.py
```

Frontend syntax:
```bash
for f in frontend/assets/js/lib/*.js frontend/assets/js/pages/*.js; do node --check "$f"; done
```
