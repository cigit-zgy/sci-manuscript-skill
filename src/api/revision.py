"""Revision lifecycle services: creation, rollback, and reindex."""

from __future__ import annotations

from pathlib import Path

from ..results import ReindexResult, RevisionResult, RollbackResult
from .project import ManuscriptProject

__all__ = [
    "ReindexResult",
    "RevisionResult",
    "RollbackResult",
    "create_revision",
    "reindex",
    "rollback",
]


def create_revision(
    project: str | Path,
    reviews: str | Path | None = None,
    *,
    round: str | int | None = None,
    keep_temp: bool = False,
) -> RevisionResult:
    """Create the next adjacent revision workspace (no content edits)."""
    return ManuscriptProject(project).start_revision(
        reviews, round=round, keep_temp=keep_temp
    )


def rollback(project: str | Path) -> RollbackResult:
    """Inspect the latest revision; removal requires explicit confirmation."""
    return ManuscriptProject(project).rollback_plan()


def reindex(project: str | Path, apply: bool = False) -> ReindexResult:
    """Plan (apply=False) or transactionally execute a round-sequence reindex."""
    return ManuscriptProject(project).reindex(apply=apply)
