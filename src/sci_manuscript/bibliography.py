"""Discovery and atomic synchronization of the shared BibTeX export."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import WorkflowError
from .workspace import load_project, normalize_project


def sync_bibliography(project: Path, explicit: Path) -> Path:
    """Atomically replace the single manuscript-level BibTeX database."""
    root = normalize_project(project)
    config = load_project(root)
    source = explicit.expanduser().resolve()
    if not source.is_file():
        raise WorkflowError(f"Bibliography export is missing: {source}")
    text = source.read_text(encoding="utf-8")
    if "@" not in text or "{" not in text:
        raise WorkflowError(f"Bibliography does not contain BibTeX entries: {source}")
    target = config.references / "references.bib"
    temporary = target.with_suffix(".bib.new")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return target
