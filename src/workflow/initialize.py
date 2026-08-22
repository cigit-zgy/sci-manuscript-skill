"""Project initialization workflow."""
from __future__ import annotations
from pathlib import Path
from ..domain.manuscript import ManuscriptMetadata, dump_metadata
from ..domain.revision import round_directory_name
from ..exceptions import WorkflowError
from ..results import Artifact, InitializationResult
from .common import copy_default_sections, render_master
from ..resources import read_resource_text

def initialize_manuscript(
    path: str | Path,
    title: str,
    journal: str,
    publisher: str,
    language: str = "en",
    article_type: str = "Research Paper",
) -> InitializationResult:
    root = Path(path).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise WorkflowError(f"Target directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    references = root / "references"
    references.mkdir()
    (references / "references.bib").write_text("% Shared BibTeX target.\n", encoding="utf-8")
    (references / "revision_style.tex").write_text(read_resource_text("revision_style.tex"), encoding="utf-8")
    (references / "zotero_setup.md").write_text("# Zotero setup\n\nConfigure Better BibTeX Automatic Export to `references/references.bib`.\n", encoding="utf-8")
    (root / "tmp").mkdir()
    round_dir = root / round_directory_name(0)
    for name in ("figures", "tables", "output", "submission"):
        (round_dir / name).mkdir(parents=True, exist_ok=True)
    copy_default_sections(round_dir)
    metadata = ManuscriptMetadata(title, journal, publisher, language, article_type, 0, None)
    dump_metadata(metadata, round_dir / "manuscript.yaml")
    master = render_master(round_dir, title)
    (root / "run.py").write_text(
        "from sci_manuscript.cli import main\nif __name__ == '__main__':\n    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    return InitializationResult(root, round_directory_name(0), (Artifact("Manuscript source", master),))
