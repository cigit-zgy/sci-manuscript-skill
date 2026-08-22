"""Project state models."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .revision import RevisionChain

@dataclass(frozen=True)
class ProjectState:
    root: Path
    chain: RevisionChain
