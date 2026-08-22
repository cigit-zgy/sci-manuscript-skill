"""Explicit shared bibliography operations."""
from __future__ import annotations
from pathlib import Path
import shutil
from ..exceptions import WorkflowError
from ..infrastructure.filesystem import project_state

def setup_zotero(project: str | Path) -> tuple[Path, Path]:
    state = project_state(project)
    refs = state.root / "references"
    refs.mkdir(exist_ok=True)
    bib = refs / "references.bib"
    bib.touch(exist_ok=True)
    guide = refs / "zotero_setup.md"
    guide.write_text("# Zotero setup\n\nConfigure Better BibTeX Automatic Export to `references/references.bib`. The runtime never controls Zotero.\n", encoding="utf-8")
    return bib, guide

def sync_bibliography(project: str | Path, export: str | Path) -> Path:
    state = project_state(project)
    source = Path(export).expanduser().resolve()
    if not source.is_file():
        raise WorkflowError(f"Bibliography export is missing: {source}")
    target = state.root / "references" / "references.bib"
    target.parent.mkdir(exist_ok=True)
    shutil.copy2(source, target)
    return target
