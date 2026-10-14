"""
deamon — MT5 Gateway Daemon
==============================
Service entry point for the cony gateway.

This package owns process lifecycle only:
  - configuration   (deamon/config.py)
  - logging         (deamon/logger.py)
  - HTTP server     (deamon/__main__.py)

The MT5 logic lives in cony, the HTTP routing lives in server.
Neither of those import deamon, so either can be swapped freely.
"""

__version__ = "1.0.0"
