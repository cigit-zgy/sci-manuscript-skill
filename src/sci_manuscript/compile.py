"""Compiler selection and isolated LaTeX source staging."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from .metadata import generate_metadata
from .workspace import (
    ProjectConfig,
    WorkflowError,
    publisher_resource,
    resources_root,
)


@dataclass(frozen=True)
class CompileResult:
    """One compiled PDF and its complete compiler diagnostics."""

    pdf: Path
    output: str


def resolve_engine(config: ProjectConfig, override: str | None = None) -> str:
    """Resolve a configured compiler without changing the environment."""
    requested = override or config.engine
    if requested == "auto":
        if shutil.which("tectonic"):
            return "tectonic"
        if shutil.which("latexmk"):
            requested = "latex"
        else:
            raise WorkflowError("Neither Tectonic nor latexmk is available.")
    if requested == "tectonic":
        if shutil.which("tectonic") is None:
            raise WorkflowError("Tectonic is not available.")
        return requested
    if requested == "latex":
        if shutil.which("latexmk") is None:
            raise WorkflowError("Traditional LaTeX mode requires latexmk.")
        if config.language == "zh" and shutil.which("xelatex") is None:
            raise WorkflowError("Chinese traditional mode requires XeLaTeX.")
        if shutil.which("xelatex") is None and shutil.which("pdflatex") is None:
            raise WorkflowError("Traditional mode requires XeLaTeX or pdfLaTeX.")
        return requested
    raise WorkflowError(f"Unsupported engine: {requested}")


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a subprocess without a shell and preserve its diagnostics."""
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
    *,
    keep_intermediates: bool = False,
) -> CompileResult:
    """Compile one source with all compiler output isolated in ``build_dir``."""
    if not source.is_file():
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
        driver = "-xelatex" if config.language == "zh" else "-pdf"
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
    if not pdf.is_file():
        raise WorkflowError(f"Compiler did not produce the expected PDF: {pdf}")
    diagnostics = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return CompileResult(pdf, diagnostics)


def _render_preamble(config: ProjectConfig, target: Path) -> None:
    template = (resources_root() / "manuscript" / "preamble.tex").read_text(
        encoding="utf-8"
    )
    cjk = (
        "\\usepackage{xeCJK}\n  \\renewcommand{\\abstractname}{摘要}"
        if config.language == "zh"
        else ""
    )
    mapping_path = publisher_resource(config) / "sections.yaml"
    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    package = data["bibliography"]["package"]
    target.write_text(
        template.replace("%%CJK_PACKAGE%%", cjk).replace(
            "%%BIBLIOGRAPHY_PACKAGE%%", str(package)
        ),
        encoding="utf-8",
    )


def stage_runtime_resources(
    config: ProjectConfig,
    round_number: int,
    target: Path,
    *,
    include_manuscript: bool,
) -> Path:
    """Stage package resources and current metadata without mutating user source."""
    version = config.round_dir(round_number)
    target.mkdir(parents=True, exist_ok=True)
    if include_manuscript:
        shutil.copy2(version / "manuscript.tex", target / "manuscript.tex")
        for directory in ("sections", "figures", "tables"):
            source = version / directory
            if source.exists():
                shutil.copytree(source, target / directory, dirs_exist_ok=True)
    else:
        for directory in ("figures", "tables"):
            source = version / directory
            if source.exists():
                shutil.copytree(source, target / directory, dirs_exist_ok=True)
    shutil.copy2(config.references / "references.bib", target / "references.bib")
    for resource in publisher_resource(config).iterdir():
        if resource.is_file():
            shutil.copy2(resource, target / resource.name)
    _render_preamble(config, target / "preamble.tex")
    generate_metadata(config.project, version, target)
    return target / "manuscript.tex"


def build_clean_manuscript(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None = None,
) -> Path:
    """Build and publish the clean PDF for one existing version."""
    source_dir = run_dir / "clean_source"
    source = stage_runtime_resources(
        config, round_number, source_dir, include_manuscript=True
    )
    compiled = compile_tex(source, run_dir / "clean_build", config, engine_override)
    output_dir = config.round_dir(round_number) / "output"
    output_dir.mkdir(exist_ok=True)
    filename = "manuscript.pdf" if round_number == 0 else "manuscript_clean.pdf"
    target = output_dir / filename
    shutil.copy2(compiled.pdf, target)
    return target
