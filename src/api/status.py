"""Status and chain-diagnostics services."""

from __future__ import annotations

from pathlib import Path

from ..results import ChainDiagnosticsResult, DependencyCheck, DoctorResult, StatusResult
from .project import ManuscriptProject

__all__ = [
    "ChainDiagnosticsResult",
    "DependencyCheck",
    "DoctorResult",
    "StatusResult",
    "chain_diagnostics",
    "status",
]


def status(project: str | Path) -> StatusResult:
    """Return the lifecycle status of one manuscript project."""
    return ManuscriptProject(project).status()


def chain_diagnostics(project: str | Path) -> ChainDiagnosticsResult:
    """Inspect the round sequence even when the chain is broken."""
    return ManuscriptProject(project).chain_diagnostics()
