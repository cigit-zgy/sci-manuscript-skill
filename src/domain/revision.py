"""Revision identity and chain invariants."""
from __future__ import annotations
from dataclasses import dataclass
import re
from ..exceptions import WorkflowError

ROUND_RE = re.compile(r"^r(\d+)$")
DIR_RE = re.compile(r"^revision_(\d+)$")
LEGACY_DIR_RE = re.compile(r"^revision_(\d)$")

def round_name(number: int) -> str:
    if number < 0:
        raise WorkflowError("Round number cannot be negative.")
    return f"r{number:02d}"

def round_directory_name(number: int) -> str:
    return "initial_submission" if number == 0 else f"revision_{number:02d}"

def parse_round(value: str | int) -> int:
    if isinstance(value, int):
        if value < 0:
            raise WorkflowError("Round number cannot be negative.")
        return value
    if value == "initial_submission":
        return 0
    if value.isdigit():
        return int(value)
    match = ROUND_RE.fullmatch(value)
    if match:
        return int(match.group(1))
    match = DIR_RE.fullmatch(value) or LEGACY_DIR_RE.fullmatch(value)
    if match:
        return int(match.group(1))
    raise WorkflowError(f"Invalid revision identity: {value!r}")

@dataclass(frozen=True)
class RevisionChain:
    rounds: tuple[int, ...]

    @property
    def broken(self) -> bool:
        return self.rounds != tuple(range(len(self.rounds)))

    @property
    def latest(self) -> int:
        if not self.rounds:
            raise WorkflowError("Project contains no manuscript rounds.")
        return self.rounds[-1]

    def require_gap_free(self) -> None:
        if self.broken:
            raise WorkflowError(f"Broken revision chain: {self.rounds}")

    def next_round(self) -> int:
        self.require_gap_free()
        return self.latest + 1
