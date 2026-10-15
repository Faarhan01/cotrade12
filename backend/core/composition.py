"""Composition helpers — sole construction site for app dependencies."""
from __future__ import annotations

from core.application.container import build_container as build_container

__all__ = ["build_container"]