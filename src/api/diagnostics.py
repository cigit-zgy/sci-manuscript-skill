"""Read-only diagnostics API."""
from __future__ import annotations
from pathlib import Path
from ..results import StatusResult
from ..workflow.project import status

def inspect_project(project: str | Path) -> StatusResult:
    return status(project)
