"""Read-only project status workflow."""
from __future__ import annotations
from pathlib import Path
from ..domain.revision import round_directory_name
from ..infrastructure.filesystem import actual_round_directory, project_state
from ..results import Artifact, StatusResult

def status(project: str | Path) -> StatusResult:
    state = project_state(project)
    versions = tuple(actual_round_directory(state.root, n).name for n in state.chain.rounds)
    artifacts: list[Artifact] = []
    for number in state.chain.rounds:
        round_dir = actual_round_directory(state.root, number)
        for path in sorted((round_dir / "output").glob("*.pdf")):
            artifacts.append(Artifact("Generated PDF", path))
    latest = state.chain.latest
    return StatusResult(state.root, round_directory_name(latest), latest, None if latest == 0 else round_directory_name(latest - 1), state.chain.broken, versions, tuple(artifacts))
