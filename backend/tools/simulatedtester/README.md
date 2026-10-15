# Simulated Tester

Self-contained test tooling for the Cotrade backend.

- `simulator.py` is a standalone MT5-like order simulator.
- `test_simulator.py` tests the simulator only.
- `tests/` contains deterministic Cotrade unit/regression tests.

This package must never be imported by the running gateway, HTTP handlers,
frontend connector, or knowledgebase.
