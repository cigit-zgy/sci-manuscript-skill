"""Shared exception hierarchy for the manuscript workflow engine."""

from __future__ import annotations


class ManuscriptError(RuntimeError):
    """Raised when a public lifecycle operation cannot complete safely."""


class WorkflowError(RuntimeError):
    """Raised when a lifecycle invariant or required resource is violated."""


class MetadataError(WorkflowError):
    """Raised when manuscript or author metadata is invalid or inconsistent."""
