"""Structured results returned by the public manuscript lifecycle API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Artifact:
    """One named final workflow artifact."""

    label: str
    path: Path


@dataclass(frozen=True)
class DependencyCheck:
    """One read-only environment dependency observation."""

    name: str
    available: bool
    detail: str
    required: bool


@dataclass(frozen=True)
class DoctorResult:
    """Environment readiness without installation side effects."""

    ready: bool
    checks: tuple[DependencyCheck, ...]


@dataclass(frozen=True)
class InitializationResult:
    """Initialized project and its first compiled artifact."""

    project: Path
    version: str
    artifacts: tuple[Artifact, ...]
    authors_need_review: bool
    bibliography_needs_configuration: bool


@dataclass(frozen=True)
class BuildResult:
    """Completed clean-manuscript build."""

    project: Path
    version: str
    artifacts: tuple[Artifact, ...]


@dataclass(frozen=True)
class RevisionResult:
    """New adjacent revision workspace and direct parent identity."""

    project: Path
    version: str
    parent: str
    artifacts: tuple[Artifact, ...]


@dataclass(frozen=True)
class SubmissionResult:
    """Completed submission build with every existing final artifact."""

    project: Path
    version: str
    artifacts: tuple[Artifact, ...]


@dataclass(frozen=True)
class CheckResult:
    """Citation-key validation result for one manuscript version."""

    project: Path
    version: str
    missing_citations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether every manuscript citation key exists."""
        return not self.missing_citations


@dataclass(frozen=True)
class StatusResult:
    """Resolved lifecycle state and all currently published artifacts."""

    project: Path
    version: str
    round_number: int
    parent: str | None
    authors: tuple[str, ...]
    publisher: str
    journal: str
    artifacts: tuple[Artifact, ...]


@dataclass(frozen=True)
class ZoteroSetupResult:
    """Project-local Better BibTeX target and manual setup guide."""

    project: Path
    artifacts: tuple[Artifact, ...]


@dataclass(frozen=True)
class BibliographySyncResult:
    """Explicitly synchronized shared bibliography files."""

    project: Path
    artifacts: tuple[Artifact, ...]
