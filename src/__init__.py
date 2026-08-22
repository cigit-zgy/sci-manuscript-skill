"""Scientific manuscript lifecycle package."""
from .api import ManuscriptProject, initialize_manuscript
from .exceptions import ManuscriptError, WorkflowError
__version__ = "4.1.0"
__all__ = ["ManuscriptProject", "initialize_manuscript", "ManuscriptError", "WorkflowError", "__version__"]
