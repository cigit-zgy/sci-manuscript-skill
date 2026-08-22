"""Marked-manuscript generation."""
from __future__ import annotations
from pathlib import Path
import shutil
from ..exceptions import WorkflowError
from .compile import compile_tex

def build_marked(parent_tex: Path, current_tex: Path, output_pdf: Path, engine: str = "auto") -> Path:
    latexdiff = shutil.which("latexdiff")
    if latexdiff is None:
        raise WorkflowError("latexdiff is required to build a marked manuscript.")
    import subprocess
    result = subprocess.run([latexdiff, "--flatten", str(parent_tex), str(current_tex)], capture_output=True, text=True, check=False)
    if result.returncode:
        raise WorkflowError(result.stderr or "latexdiff failed")
    diff_tex = output_pdf.parent / "manuscript_marked.tex"
    diff_tex.write_text(result.stdout, encoding="utf-8")
    return compile_tex(diff_tex, output_pdf, engine, reject_overfull=True)
