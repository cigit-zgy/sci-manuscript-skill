"""Canonical revision-round identity formatting and parsing.

The canonical user-facing form uses two-digit numbers: ``r00``/``r01``/``r02``
and directories ``initial_submission``/``revision_01``/``revision_02``. Legacy
one-digit forms (``r0``/``r1``, ``revision_1``/``revision_2``) are accepted on
input so existing projects keep working; newly created metadata always uses
the two-digit canonical form.
"""

from __future__ import annotations

import re

ROUND_PATTERN = re.compile(r"^r(\d+)$")
REVISION_DIRECTORY_PATTERN = re.compile(r"^revision_(\d+)$")


def round_name(round_number: int) -> str:
    """Format an internal round number as the canonical ``rNN`` label."""
    if round_number < 0:
        raise ValueError("Round numbers must be non-negative.")
    return f"r{round_number:02d}"


def round_directory_name(round_number: int) -> str:
    """Map an internal round number to its canonical user-facing directory."""
    if round_number < 0:
        raise ValueError("Round numbers must be non-negative.")
    if round_number == 0:
        return "initial_submission"
    return f"revision_{round_number:02d}"


def parse_round_name(value: str) -> int | None:
    """Parse ``r0``/``r00``/``r1``/``r01`` into an internal round number."""
    match = ROUND_PATTERN.fullmatch(value.strip().lower())
    if match is None:
        return None
    return int(match.group(1))


def parse_round_directory(value: str) -> int | None:
    """Parse ``initial_submission`` or ``revision_1``/``revision_01``."""
    normalized = value.strip().lower()
    if normalized == "initial_submission":
        return 0
    match = REVISION_DIRECTORY_PATTERN.fullmatch(normalized)
    if match is None:
        return None
    number = int(match.group(1))
    return number if number >= 1 else None


def parse_round(value: str | int | None, default: int | None = None) -> int | None:
    """Parse ``rN``/``rNN`` or a semantic directory into an internal number."""
    if value is None:
        return default
    if isinstance(value, int):
        return value if value >= 0 else None
    if value.strip().lower() == "initial_submission":
        return 0
    internal = parse_round_name(value)
    if internal is not None:
        return internal
    return parse_round_directory(value)
