"""Public Python interface for sci-manuscript-skill."""

from ._version import package_version
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
    UpgradeResult,
    ZoteroSetupResult,
)

__version__ = package_version()

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
    "UpgradeResult",
    "ZoteroSetupResult",
    "__version__",
    "initialize_manuscript",
]
