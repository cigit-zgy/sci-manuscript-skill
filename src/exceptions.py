"""Public and internal exceptions."""

class ManuscriptError(RuntimeError):
    """Base public error."""

class WorkflowError(ManuscriptError):
    """Lifecycle contract violation."""
