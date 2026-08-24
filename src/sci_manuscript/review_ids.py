"""Canonical grammar and validation for reviewer and editor identifiers."""

from __future__ import annotations

import re

from .errors import WorkflowError

REVIEW_ID = re.compile(r"^(?:E|AE|[1-9]\d*)-[1-9]\d*$")


def is_review_id(value: str) -> bool:
    """Return whether a single reviewer/editor ID is valid."""
    return REVIEW_ID.fullmatch(value.strip()) is not None


def validate_review_id_list(value: str) -> tuple[str, ...]:
    """Validate a comma-separated review provenance list."""
    ids = tuple(item.strip() for item in value.split(","))
    if not ids or any(not is_review_id(item) for item in ids):
        raise WorkflowError(
            f"Invalid review ID list {value!r}; use E-1, AE-1, 1-1, "
            "or comma-separated IDs."
        )
    if len(ids) != len(set(ids)):
        raise WorkflowError(f"Review ID list contains duplicates: {value!r}")
    return ids
