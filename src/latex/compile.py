"""Internal LaTeX compiler selection and isolated PDF builds."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..workflow.project import ProjectConfig
from ..exceptions import WorkflowError


@dataclass(frozen=True)
class CompileResult:
    """One successfully compiled PDF and captured compiler diagnostics."""

    pdf: Path
    output: str


def resolve_engine(config: ProjectConfig, override: str | None = None) -> str:
    """Resolve the configured compiler without installing dependencies."""
    requested = override or config.engine
    if requested == "auto":
        if shutil.which("tectonic"):
            return "tectonic"
        if shutil.which("latexmk"):
            requested = "latex"
        else:
            raise WorkflowError("Neither Tectonic nor latexmk is available.")
    if requested == "tectonic":
        if not shutil.which("tectonic"):
            raise WorkflowError("Tectonic is not available.")
        return requested
    if requested == "latex":
        if not shutil.which("latexmk"):
            raise WorkflowError("Traditional LaTeX mode requires latexmk.")
        if config.language == "zh" and not shutil.which("xelatex"):
            raise WorkflowError("Chinese traditional mode requires XeLaTeX.")
        if not (shutil.which("xelatex") or shutil.which("pdflatex")):
            raise WorkflowError("Traditional LaTeX mode requires XeLaTeX or pdfLaTeX.")
        return requested
    raise WorkflowError(f"Unsupported engine: {requested}")


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one deterministic command and preserve combined diagnostics."""
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        details = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        raise WorkflowError(f"Command failed: {' '.join(command)}\n{details}")
    return result


def compile_tex(
    source: Path,
    build_dir: Path,
    config: ProjectConfig,
    engine_override: str | None = None,
    keep_intermediates: bool = False,
) -> CompileResult:
    """Compile one TeX source with all intermediates isolated in ``build_dir``."""
    if not source.exists():
        raise WorkflowError(f"TeX source is missing: {source}")
    build_dir.mkdir(parents=True, exist_ok=True)
    engine = resolve_engine(config, engine_override)
    if engine == "tectonic":
        command = [
            shutil.which("tectonic") or "tectonic",
            "-X",
            "compile",
            f"--outdir={build_dir}",
        ]
        if keep_intermediates:
            command.append("--keep-intermediates")
        command.append(str(source))
    else:
        driver = "-xelatex" if shutil.which("xelatex") else "-pdf"
        command = [
            shutil.which("latexmk") or "latexmk",
            driver,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-outdir={build_dir}",
            str(source),
        ]
    result = run_command(command, cwd=source.parent)
    pdf = build_dir / f"{source.stem}.pdf"
    if not pdf.exists():
        raise WorkflowError(f"Compiler did not produce the expected PDF: {pdf}")
    chatter = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return CompileResult(pdf=pdf, output=chatter)


def build_clean_manuscript(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None = None,
) -> Path:
    """Build and publish the clean PDF for one existing round."""
    round_dir = config.round_dir(round_number)
    if not round_dir.is_dir():
        raise WorkflowError(f"Manuscript round is missing: {round_dir}")
    result = compile_tex(
        round_dir / "manuscript.tex",
        run_dir / "clean",
        config,
        engine_override,
    )
    output_dir = round_dir / "output"
    output_dir.mkdir(exist_ok=True)
    filename = "manuscript.pdf" if round_number == 0 else "manuscript_clean.pdf"
    target = output_dir / filename
    shutil.copy2(result.pdf, target)
    return target
