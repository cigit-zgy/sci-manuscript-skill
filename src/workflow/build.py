"""Clean manuscript build workflow."""
from __future__ import annotations
from pathlib import Path
from ..domain.revision import round_directory_name
from ..latex.compile import compile_tex
from ..latex.diff import build_marked
from ..results import Artifact, BuildResult
from .common import metadata_for_round, render_master, require_gap_free
from ..infrastructure.filesystem import actual_round_directory

def build_manuscript(project: str | Path, round_number: int | None = None, engine: str = "auto") -> BuildResult:
    state = require_gap_free(project)
    number = state.chain.latest if round_number is None else round_number
    round_dir = actual_round_directory(state.root, number)
    metadata = metadata_for_round(state.root, number)
    master = render_master(round_dir, metadata.title)
    pdf = compile_tex(master, round_dir / "output" / ("manuscript.pdf" if number == 0 else "manuscript_clean.pdf"), engine)
    return BuildResult(state.root, round_directory_name(number), (Artifact("Clean manuscript", pdf),))


def build_revision_artifacts(project: str | Path, round_number: int | None = None, engine: str = "auto") -> BuildResult:
    state = require_gap_free(project)
    number = state.chain.latest if round_number is None else round_number
    if number == 0:
        return build_manuscript(state.root, 0, engine)
    round_dir = actual_round_directory(state.root, number)
    parent_dir = actual_round_directory(state.root, number - 1)
    metadata = metadata_for_round(state.root, number)
    parent_metadata = metadata_for_round(state.root, number - 1)
    current_master = render_master(round_dir, metadata.title)
    parent_master = render_master(parent_dir, parent_metadata.title)
    clean = compile_tex(current_master, round_dir / "output" / "manuscript_clean.pdf", engine)
    marked = build_marked(parent_master, current_master, round_dir / "output" / "manuscript_marked.pdf", engine)
    response_source = round_dir / "response" / "response_letter.tex"
    response = compile_tex(response_source, round_dir / "output" / "response_letter.pdf", engine)
    return BuildResult(
        state.root,
        round_directory_name(number),
        (Artifact("Clean manuscript", clean), Artifact("Marked manuscript", marked), Artifact("Response letter", response)),
    )
