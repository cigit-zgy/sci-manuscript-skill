"""Public Python interface for sci-manuscript-skill."""

from ._version import package_version
from .api import (
    ManuscriptError,
    ManuscriptProject,
    initialize_manuscript,
    inspect_environment,
)
from .results import (
    Artifact,
    BibliographySyncResult,
    BuildResult,
    ChainDiagnosticsResult,
    CheckResult,
    DependencyCheck,
    DoctorResult,
    InitializationResult,
    ReindexResult,
    RevisionResult,
    RollbackResult,
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
    "ChainDiagnosticsResult",
    "CheckResult",
    "DependencyCheck",
    "DoctorResult",
    "InitializationResult",
    "ManuscriptError",
    "ManuscriptProject",
    "ReindexResult",
    "RevisionResult",
    "RollbackResult",
    "StatusResult",
    "SubmissionResult",
    "UpgradeResult",
    "ZoteroSetupResult",
    "__version__",
    "initialize_manuscript",
    "inspect_environment",
]
