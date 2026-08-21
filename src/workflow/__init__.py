"""Workflow orchestration modules (lazy submodule access)."""

from __future__ import annotations

import importlib

__all__ = ["build", "initialize", "project", "revision", "rollback", "submission"]

_LOADED: dict[str, object] = {}


def __getattr__(name: str) -> object:
    if name in __all__:
        module = importlib.import_module(f".{name}", __name__)
        _LOADED[name] = module
        return module
    raise AttributeError(name)
