"""Filesystem discovery helpers."""
from __future__ import annotations
from pathlib import Path
from ..domain.project import ProjectState
from ..domain.revision import RevisionChain, parse_round, round_directory_name
from ..exceptions import WorkflowError

def normalize_project(project: str | Path) -> Path:
    return Path(project).expanduser().resolve()

def scan_round_directories(root: Path) -> tuple[int, ...]:
    found: dict[int, Path] = {}
    initial = root / "initial_submission"
    if initial.is_dir():
        found[0] = initial
    for path in root.glob("revision_*"):
        if not path.is_dir():
            continue
        try:
            number = parse_round(path.name)
        except WorkflowError:
            continue
        if number in found:
            raise WorkflowError(f"Duplicate round identity for {number}: {path}")
        found[number] = path
    return tuple(sorted(found))

def project_state(project: str | Path) -> ProjectState:
    root = normalize_project(project)
    if not root.is_dir():
        raise WorkflowError(f"Project directory does not exist: {root}")
    chain = RevisionChain(scan_round_directories(root))
    if not chain.rounds:
        raise WorkflowError("Project is not initialized.")
    return ProjectState(root, chain)

def actual_round_directory(root: Path, number: int) -> Path:
    canonical = root / round_directory_name(number)
    if canonical.is_dir():
        return canonical
    legacy = root / ("initial_submission" if number == 0 else f"revision_{number}")
    if legacy.is_dir():
        return legacy
    raise WorkflowError(f"Round directory is missing: {round_directory_name(number)}")
