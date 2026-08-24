"""Compiler selection and isolated LaTeX source staging."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
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


@dataclass(frozen=True)
class CjkProbeResult:
    """Result of a real minimal CJK compilation and glyph extraction probe."""

    ready: bool
    detail: str


@dataclass(frozen=True)
class OverfullBox:
    """One unique overfull box reported by a LaTeX compiler."""

    axis: str
    excess_pt: float
    source: str
    line_start: int
    line_end: int


OVERFULL_BOX = re.compile(
    r"(?:warning:\s+)?(?P<source>[^:\n]+):(?P<source_line>\d+):\s+"
    r"Overfull \\(?P<axis>[hv])box \((?P<excess>\d+(?:\.\d+)?)pt too "
    r"(?:wide|high)\).*?at lines? (?P<start>\d+)(?:--(?P<end>\d+))?",
    re.I,
)
UNDERFULL_BOX = re.compile(r"Underfull \\[hv]box", re.I)


def parse_overfull_boxes(output: str) -> tuple[OverfullBox, ...]:
    """Parse and de-duplicate Tectonic/LaTeX overfull-box diagnostics."""
    issues: list[OverfullBox] = []
    seen: set[tuple[str, float, str, int, int]] = set()
    for match in OVERFULL_BOX.finditer(output):
        start = int(match.group("start"))
        issue = OverfullBox(
            axis=match.group("axis").lower(),
            excess_pt=float(match.group("excess")),
            source=match.group("source").strip(),
            line_start=start,
            line_end=int(match.group("end") or start),
        )
        key = (
            issue.axis,
            round(issue.excess_pt, 5),
            issue.source,
            issue.line_start,
            issue.line_end,
        )
        if key not in seen:
            seen.add(key)
            issues.append(issue)
    return tuple(issues)


def _overflow_signature(issue: OverfullBox) -> tuple[str, float]:
    return issue.axis, round(issue.excess_pt, 2)


def validate_revision_layout(
    clean_output: str,
    marked_output: str,
    report_path: Path,
) -> Path:
    """Compare clean/marked logs and reject every marked-specific overflow."""
    clean = parse_overfull_boxes(clean_output)
    marked = parse_overfull_boxes(marked_output)
    remaining = Counter(_overflow_signature(issue) for issue in clean)
    marked_specific: list[OverfullBox] = []
    for issue in marked:
        signature = _overflow_signature(issue)
        if remaining[signature] > 0:
            remaining[signature] -= 1
        else:
            marked_specific.append(issue)

    def render(label: str, issues: tuple[OverfullBox, ...]) -> list[str]:
        lines = [f"{label}: {len(issues)}"]
        lines.extend(
            f"- {issue.axis}box {issue.excess_pt:.5f} pt; "
            f"{issue.source}:{issue.line_start}--{issue.line_end}"
            for issue in issues
        )
        return lines

    lines = [
        "Revision layout QA",
        "",
        *render("Clean overfull boxes", clean),
        "",
        *render("Marked overfull boxes", marked),
        "",
        *render("Marked-specific overfull boxes", tuple(marked_specific)),
        "",
        f"Clean underfull diagnostics: {len(UNDERFULL_BOX.findall(clean_output))}",
        f"Marked underfull diagnostics: {len(UNDERFULL_BOX.findall(marked_output))}",
        "",
        "Result: " + ("FAIL" if marked_specific else "PASS"),
        "Visual PDF inspection remains required before submission.",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if marked_specific:
        details = ", ".join(
            f"{issue.axis}box {issue.excess_pt:.2f} pt at "
            f"{issue.source}:{issue.line_start}--{issue.line_end}"
            for issue in marked_specific
        )
        raise WorkflowError(
            "Marked manuscript has overflow not present in the clean build: "
            f"{details}. See {report_path}."
        )
    return report_path


def _cjk_font_directories() -> tuple[Path, ...]:
    configured = os.environ.get("SCI_MANUSCRIPT_CJK_FONT_DIR")
    candidates = [
        Path.home() / "Library" / "Fonts",
        Path("/Library/Fonts"),
        Path("/usr/share/fonts/opentype/fandol"),
    ]
    if configured:
        candidates.insert(0, Path(configured).expanduser())
    return tuple(dict.fromkeys(path.resolve() for path in candidates))


def stage_cjk_fonts(target: Path) -> tuple[Path, ...]:
    """Stage installed Fandol fonts beside one CJK source without bundling fonts."""
    target.mkdir(parents=True, exist_ok=True)
    for directory in _cjk_font_directories():
        regular = directory / "FandolSong-Regular.otf"
        if not regular.is_file():
            continue
        staged: list[Path] = []
        for source in sorted(directory.glob("Fandol*.otf")):
            destination = target / source.name
            if not destination.exists():
                shutil.copy2(source, destination)
            staged.append(destination)
        return tuple(staged)
    return ()


def probe_cjk_environment(engine: str = "auto") -> CjkProbeResult:
    """Compile and extract a minimal Chinese document with the selected engine."""
    selected = engine
    if selected == "auto":
        selected = "tectonic" if shutil.which("tectonic") else "latex"
    if selected == "tectonic":
        executable = shutil.which("tectonic")
        if executable is None:
            return CjkProbeResult(False, "Tectonic is not available.")
    elif selected == "latex":
        executable = shutil.which("xelatex")
        if executable is None:
            return CjkProbeResult(False, "XeLaTeX is not available.")
    else:
        return CjkProbeResult(False, f"Unsupported engine: {selected}")
    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        return CjkProbeResult(False, "pdftotext is required for CJK glyph validation.")
    with tempfile.TemporaryDirectory(prefix="sci-manuscript-cjk-") as temporary:
        root = Path(temporary)
        source = root / "cjk_probe.tex"
        output = root / "output"
        output.mkdir()
        staged_fonts = stage_cjk_fonts(root)
        font_setup = (
            "\\setCJKmainfont[Path=./]{FandolSong-Regular.otf}\n"
            if staged_fonts
            else ""
        )
        source_text = (
            "\\documentclass{article}\n"
            "\\usepackage{xeCJK}\n"
            f"{font_setup}"
            "\\begin{document}\n"
            "中文环境测试\n"
            "\\end{document}\n"
        )
        source.write_text(source_text, encoding="utf-8")
        if selected == "tectonic":
            command = [
                executable,
                "-X",
                "compile",
                f"--outdir={output}",
                str(source),
            ]
        else:
            command = [
                executable,
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={output}",
                str(source),
            ]
        compiled = subprocess.run(
            command,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if compiled.returncode != 0:
            diagnostics = (compiled.stdout + compiled.stderr).strip()
            tail = "\n".join(diagnostics.splitlines()[-8:])
            return CjkProbeResult(
                False,
                f"{selected} could not compile the xeCJK probe. {tail}",
            )
        pdf = output / "cjk_probe.pdf"
        if not pdf.is_file():
            return CjkProbeResult(False, "CJK probe did not produce a PDF.")
        extracted = subprocess.run(
            [pdftotext, str(pdf), "-"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if extracted.returncode != 0:
            return CjkProbeResult(False, "CJK probe PDF text extraction failed.")
        normalized = "".join(extracted.stdout.split())
        if "中文环境测试" not in normalized:
            return CjkProbeResult(
                False, "CJK probe compiled but Chinese glyphs are empty."
            )
    return CjkProbeResult(
        True, f"{selected} compiled xeCJK and preserved Chinese glyphs."
    )


def ensure_cjk_environment(config: ProjectConfig, engine: str | None = None) -> None:
    """Block Chinese targets unless the real CJK probe succeeds."""
    if config.language != "zh" and config.metadata.publisher != "chinese":
        return
    result = probe_cjk_environment(engine or config.engine)
    if not result.ready:
        raise WorkflowError(f"Chinese environment is blocked: {result.detail}")


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
    diagnostics = "\n".join(part for part in (result.stdout, result.stderr) if part)
    (build_dir / f"{source.stem}.compiler.log").write_text(
        diagnostics,
        encoding="utf-8",
    )
    pdf = build_dir / f"{source.stem}.pdf"
    if not pdf.is_file():
        raise WorkflowError(f"Compiler did not produce the expected PDF: {pdf}")
    return CompileResult(pdf, diagnostics)


def _render_preamble(config: ProjectConfig, target: Path) -> None:
    source = resources_root() / "manuscript" / "preamble"
    mapping_path = publisher_resource(config) / "sections.yaml"
    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    package = data["bibliography"]["package"]
    target.mkdir(parents=True, exist_ok=True)
    for name in ("common.tex", "zh.tex", "en.tex"):
        template = (source / name).read_text(encoding="utf-8")
        (target / name).write_text(
            template.replace("%%BIBLIOGRAPHY_PACKAGE%%", str(package)),
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
    if config.language == "zh" or config.metadata.publisher == "chinese":
        stage_cjk_fonts(target)
    if include_manuscript:
        shutil.copy2(version / "manuscript.tex", target / "manuscript.tex")
        for directory in ("sections", "figures", "tables", "preamble"):
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
    if not (target / "preamble").is_dir():
        _render_preamble(config, target / "preamble")
    (target / "preamble.tex").write_text(
        f"\\input{{preamble/{config.language}}}\n", encoding="utf-8"
    )
    generate_metadata(config.project, version, target)
    return target / "manuscript.tex"


def build_clean_manuscript(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None = None,
) -> Path:
    """Build and publish the clean PDF for one existing version."""
    ensure_cjk_environment(config, engine_override)
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
