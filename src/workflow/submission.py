"""Submission package assembly workflow."""
from __future__ import annotations
from pathlib import Path
import shutil
from ..domain.revision import round_directory_name
from ..exceptions import WorkflowError
from ..domain.review import has_pending_response
from ..infrastructure.filesystem import actual_round_directory
from ..results import Artifact, SubmissionResult
from .build import build_manuscript, build_revision_artifacts
from .common import require_gap_free

def prepare_submission(project: str | Path, round_number: int | None = None, engine: str = "auto", allow_placeholders: bool = False) -> SubmissionResult:
    state = require_gap_free(project)
    number = state.chain.latest if round_number is None else round_number
    round_dir = actual_round_directory(state.root, number)
    if number > 0:
        response = round_dir / "response" / "response_letter.tex"
        if not response.is_file():
            raise WorkflowError("Revision response source is missing.")
        if not allow_placeholders and has_pending_response(response.read_text(encoding="utf-8")):
            raise WorkflowError("Submission blocked by pending reviewer responses.")
    build = build_manuscript(state.root, number, engine) if number == 0 else build_revision_artifacts(state.root, number, engine)
    package = round_dir / "submission" / "package"
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)
    artifacts: list[Artifact] = []
    names = ("manuscript.pdf",) if number == 0 else ("manuscript.pdf", "marked_manuscript.pdf", "response_letter.pdf")
    for source_artifact, name in zip(build.artifacts, names, strict=True):
        target = package / name
        shutil.copy2(source_artifact.path, target)
        artifacts.append(Artifact(f"Packaged {source_artifact.label}", target))
    artifacts.append(Artifact("Submission package", package))
    return SubmissionResult(state.root, round_directory_name(number), tuple(artifacts))
