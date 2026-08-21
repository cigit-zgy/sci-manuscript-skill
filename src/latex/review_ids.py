"""Strict stable identifiers shared by response and marked-manuscript paths."""

from __future__ import annotations

import re

REVIEW_ID_PATTERN = re.compile(r"^(?:[1-9]\d*|E|AE)-[1-9]\d*$")


def is_review_id(value: str) -> bool:
    """Return whether a reviewer, editor, or associate-editor ID is canonical."""
    return REVIEW_ID_PATTERN.fullmatch(value) is not None
