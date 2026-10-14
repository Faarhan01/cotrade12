"""
deamon — Logging
==================
Single logging setup for the daemon process. Also used by the
server layer if it wants to log.
"""

import logging
import sys


_configured = False


def setup_logging(level: str = "INFO", log_file: str = None) -> None:
    """Configure root logging once per process."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
            )
        )
        root.addHandler(file_handler)

    _configured = True


def get_logger(name: str = "deamon") -> logging.Logger:
    """Get a logger, configuring logging on first call."""
    setup_logging()
    return logging.getLogger(name)
