"""Typed result objects returned by public operations."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Artifact:
    label: str
    path: Path

@dataclass(frozen=True)
class StatusResult:
    project: Path
    version: str
    round_number: int
    parent: str | None
    broken: bool
    versions: tuple[str, ...]
    artifacts: tuple[Artifact, ...] = ()

@dataclass(frozen=True)
class RevisionResult:
    project: Path
    version: str
    parent: str
    artifacts: tuple[Artifact, ...] = ()

@dataclass(frozen=True)
class RollbackResult:
    project: Path
    version: str
    parent: str
    changed_files: tuple[str, ...]

@dataclass(frozen=True)
class ReindexResult:
    project: Path
    applied: bool
    renames: tuple[tuple[str, str], ...]
    invalidated: tuple[str, ...] = ()
    status: str = "planned"

@dataclass(frozen=True)
class BuildResult:
    project: Path
    version: str
    artifacts: tuple[Artifact, ...]

@dataclass(frozen=True)
class InitializationResult:
    project: Path
    version: str
    artifacts: tuple[Artifact, ...]

@dataclass(frozen=True)
class SubmissionResult:
    project: Path
    version: str
    artifacts: tuple[Artifact, ...]
