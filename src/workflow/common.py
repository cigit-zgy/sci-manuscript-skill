"""Shared workflow helpers; no lifecycle operation ownership here."""
from __future__ import annotations
from pathlib import Path
import shutil
from importlib.resources import as_file
from ..domain.manuscript import ManuscriptMetadata, load_metadata
from ..infrastructure.filesystem import actual_round_directory, project_state
from ..resources import resource

COPY_DIRS = ("sections", "figures", "tables", "submission")

def metadata_for_round(root: Path, number: int) -> ManuscriptMetadata:
    return load_metadata(actual_round_directory(root, number) / "manuscript.yaml")

def render_master(round_dir: Path, title: str) -> Path:
    sections = sorted((round_dir / "sections").glob("*.tex"))
    body = "\n".join(f"\\input{{sections/{p.name}}}" for p in sections)
    text = "\\documentclass[11pt]{article}\n\\usepackage[margin=1in]{geometry}\n\\usepackage{xcolor}\n\\usepackage{hyperref}\n\\title{" + title.replace("&", "\\&") + "}\n\\author{}\n\\date{}\n\\begin{document}\n\\maketitle\n" + body + "\n\\end{document}\n"
    target = round_dir / "manuscript.tex"
    target.write_text(text, encoding="utf-8")
    return target

def copy_default_sections(target: Path) -> None:
    source = resource("manuscript/sections/default")
    with as_file(source) as src:
        shutil.copytree(src, target / "sections", dirs_exist_ok=True)

def require_gap_free(project: str | Path):
    state = project_state(project)
    state.chain.require_gap_free()
    return state
