"""Public error boundary for manuscript lifecycle operations."""


class ManuscriptError(RuntimeError):
    """Raised when a deterministic manuscript workflow invariant fails."""


class WorkflowError(ManuscriptError):
    """Raised when a lifecycle, parser, or filesystem invariant fails."""


class MetadataError(ManuscriptError):
    """Raised when manuscript metadata or an author library is invalid."""
