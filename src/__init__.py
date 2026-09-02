"""Public API for the scientific manuscript lifecycle."""

from importlib.metadata import PackageNotFoundError, version

from .api import (
    Artifact,
    DoctorCheck,
    DoctorResult,
    LifecycleResult,
    ManuscriptProject,
    StatusResult,
    doctor,
    initialize_manuscript,
)
from .errors import ManuscriptError

try:
    __version__ = version("sci-manuscript")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = [
    "Artifact",
    "DoctorCheck",
    "DoctorResult",
    "LifecycleResult",
    "ManuscriptError",
    "ManuscriptProject",
    "StatusResult",
    "__version__",
    "doctor",
    "initialize_manuscript",
]
