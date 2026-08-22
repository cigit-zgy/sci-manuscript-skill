"""Deterministic LaTeX build helpers with optional strict layout auditing."""
from __future__ import annotations
from pathlib import Path
import re
import shutil
import subprocess
from ..exceptions import WorkflowError

_OVERFULL = re.compile(r"Overfull \\([hv])box \(([^)]+) too (?:wide|high)\)")


def available_engine() -> str | None:
    for engine in ("tectonic", "latexmk", "xelatex", "pdflatex"):
        if shutil.which(engine):
            return engine
    return None


def overfull_warnings(log_text: str) -> tuple[str, ...]:
    """Return normalized overfull box diagnostics from a LaTeX log."""
    warnings: list[str] = []
    for line in log_text.splitlines():
        if "Overfull \\hbox" in line or "Overfull \\vbox" in line:
            warnings.append(line.strip())
    return tuple(warnings)


def compile_tex(
    source: Path,
    output_pdf: Path,
    engine: str = "auto",
    *,
    reject_overfull: bool = False,
) -> Path:
    """Compile a TeX source and optionally reject any overfull box warning."""
    selected = available_engine() if engine == "auto" else engine
    if selected is None:
        raise WorkflowError("No LaTeX engine found. Install tectonic or TeX Live.")
    work = output_pdf.parent / ".compile"
    work.mkdir(parents=True, exist_ok=True)
    if selected == "tectonic":
        cmd = [selected, "--outdir", str(work), source.name]
    elif selected == "latexmk":
        cmd = [selected, "-pdf", "-interaction=nonstopmode", f"-outdir={work}", source.name]
    else:
        cmd = [selected, "-interaction=nonstopmode", f"-output-directory={work}", source.name]
    result = subprocess.run(cmd, cwd=source.parent, capture_output=True, text=True, check=False)
    built = work / f"{source.stem}.pdf"
    log_path = work / f"{source.stem}.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    if result.returncode or not built.exists():
        raise WorkflowError(
            f"LaTeX compilation failed for {source}:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )
    if reject_overfull:
        warnings = overfull_warnings(log_text)
        if warnings:
            detail = "\n".join(warnings[:20])
            raise WorkflowError(
                "Marked-manuscript layout audit failed: LaTeX reported overfull boxes. "
                "Revise the affected content before submission.\n" + detail
            )
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, output_pdf)
    shutil.rmtree(work, ignore_errors=True)
    return output_pdf
