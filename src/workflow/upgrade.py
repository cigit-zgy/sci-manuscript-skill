"""Conservative project upgrade workflow."""
from __future__ import annotations
from pathlib import Path
from ..infrastructure.filesystem import project_state
from ..results import ReindexResult
from .reindex import execute_reindex, plan_reindex

def upgrade_project(project: str | Path) -> ReindexResult:
    state = project_state(project)
    plan = plan_reindex(state.root)
    return execute_reindex(state.root) if plan.renames else ReindexResult(state.root, False, (), status="already_current")
