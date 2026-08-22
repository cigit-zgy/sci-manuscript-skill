"""Public error boundary for manuscript lifecycle operations."""


class ManuscriptError(RuntimeError):
    """Raised when a deterministic manuscript workflow invariant fails."""
