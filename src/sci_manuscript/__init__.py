"""Public Python interface for sci-manuscript-skill."""

from .api import ManuscriptError, ManuscriptProject, initialize_manuscript
from .results import (
    Artifact,
    BibliographySyncResult,
    BuildResult,
    CheckResult,
    DependencyCheck,
    DoctorResult,
    InitializationResult,
    RevisionResult,
    StatusResult,
    SubmissionResult,
    ZoteroSetupResult,
)

__all__ = [
    "Artifact",
    "BibliographySyncResult",
    "BuildResult",
    "CheckResult",
    "DependencyCheck",
    "DoctorResult",
    "InitializationResult",
    "ManuscriptError",
    "ManuscriptProject",
    "RevisionResult",
    "StatusResult",
    "SubmissionResult",
    "ZoteroSetupResult",
    "initialize_manuscript",
]
