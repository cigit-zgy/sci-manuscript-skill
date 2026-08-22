"""Safe rollback workflow for the latest unchanged revision."""
from __future__ import annotations
from pathlib import Path
import shutil
from ..domain.revision import round_directory_name
from ..exceptions import WorkflowError
from ..domain.review import has_pending_response
from ..infrastructure.filesystem import actual_round_directory
from ..infrastructure.hashing import source_hashes
from ..infrastructure.manifest import load_creation_manifest
from ..results import RollbackResult
from .common import require_gap_free

def inspect_rollback(project: str | Path) -> RollbackResult:
    state = require_gap_free(project)
    latest = state.chain.latest
    if latest == 0:
        raise WorkflowError("initial_submission (r00) cannot be rolled back.")
    target = actual_round_directory(state.root, latest)
    manifest = load_creation_manifest(target)
    baseline = dict(manifest.get("user_sources", {}))
    current = source_hashes(target)
    current.pop("manuscript.yaml", None)
    response_key = "response/response_letter.tex"
    response = target / response_key
    changed: set[str] = set()
    for name, digest in baseline.items():
        if current.get(name) != digest:
            changed.add(name)
    for name in current:
        if name not in baseline and name != response_key:
            changed.add(name)
    if response.is_file() and not has_pending_response(response.read_text(encoding="utf-8")):
        changed.add(response_key)
    return RollbackResult(state.root, round_directory_name(latest), round_directory_name(latest - 1), tuple(sorted(changed)))

def rollback_latest(project: str | Path) -> RollbackResult:
    inspection = inspect_rollback(project)
    if inspection.changed_files:
        raise WorkflowError("Rollback refused; user source modifications detected: " + ", ".join(inspection.changed_files))
    shutil.rmtree(inspection.project / inspection.version)
    return inspection
