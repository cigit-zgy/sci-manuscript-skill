"""Submission-focused public function."""
from __future__ import annotations
from pathlib import Path
from ..results import SubmissionResult
from ..workflow.submission import prepare_submission as _prepare

def prepare_submission(project: str | Path, round_number: int | None = None, engine: str = "auto", allow_placeholders: bool = False) -> SubmissionResult:
    return _prepare(project, round_number, engine, allow_placeholders)
