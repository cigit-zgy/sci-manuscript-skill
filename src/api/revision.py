"""Revision-focused public functions."""
from __future__ import annotations
from pathlib import Path
from ..results import ReindexResult, RevisionResult, RollbackResult
from ..workflow.revision import start_revision as _start
from ..workflow.rollback import inspect_rollback as _inspect, rollback_latest as _rollback
from ..workflow.reindex import plan_reindex as _plan, execute_reindex as _execute

def start_revision(project: str | Path, reviews: str | Path | None = None, requested_round: int | None = None) -> RevisionResult:
    return _start(project, reviews, requested_round)

def rollback_plan(project: str | Path) -> RollbackResult:
    return _inspect(project)

def rollback_latest(project: str | Path) -> RollbackResult:
    return _rollback(project)

def reindex_plan(project: str | Path) -> ReindexResult:
    return _plan(project)

def reindex(project: str | Path) -> ReindexResult:
    return _execute(project)
