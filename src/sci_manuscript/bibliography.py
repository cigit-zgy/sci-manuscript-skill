"""Discovery and atomic synchronization of the shared BibTeX export."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import WorkflowError
from .workspace import load_project, normalize_project


def find_bibliography_export(project: Path, explicit: Path | None) -> Path:
    """Resolve the explicit, configured, or conventional BibTeX export."""
    candidates = []
    if explicit is not None:
        candidates.append(explicit.expanduser().resolve())
    environment = os.environ.get("ZOTERO_BETTER_BIBTEX_EXPORT")
    if environment:
        candidates.append(Path(environment).expanduser().resolve())
    candidates.extend(
        [
            project / "references" / "zotero-export.bib",
            project.parent / "zotero-export.bib",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise WorkflowError("No Better BibTeX export found; use --bib-export PATH.")


def sync_bibliography(project: Path, explicit: Path | None = None) -> Path:
    """Atomically replace the single manuscript-level BibTeX database."""
    root = normalize_project(project)
    config = load_project(root)
    source = find_bibliography_export(root, explicit)
    text = source.read_text(encoding="utf-8")
    if "@" not in text or "{" not in text:
        raise WorkflowError(f"Bibliography does not contain BibTeX entries: {source}")
    target = config.references / "references.bib"
    temporary = target.with_suffix(".bib.new")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return target
