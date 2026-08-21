"""Citation and chain validation services."""

from __future__ import annotations

from pathlib import Path

from ..results import CheckResult
from .project import ManuscriptProject

__all__ = ["CheckResult", "check"]


def check(project: str | Path, round: str | int | None = None) -> CheckResult:
    """Validate manuscript citation keys against the shared bibliography."""
    return ManuscriptProject(project).check(round)
