"""Compiler selection and isolated LaTeX source staging."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import WorkflowError
from .metadata import generate_metadata
from .templates import publisher_resource, resources_root
from .tex import scan_tex_commands
from .timing import BuildTelemetry
from .workspace import ProjectConfig, bibliography_source_for_round

SUPPORTED_ENGINES = ("auto", "tectonic", "latex")


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
PRE_DOCUMENT_SECTION_INPUT = re.compile(
    r"(?m)^[ \t]*\\(?:input|include)\s*\{sections/[^}\n]+\}"
    r"[ \t]*(?:%[^\n]*)?\n?"
)
DOCUMENTCLASS = re.compile(r"(?m)^[ \t]*\\documentclass\b")
DVIPSNAMES_OPTION = r"\PassOptionsToPackage{dvipsnames}{xcolor}"


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


def probe_cjk_environment(
    engine: str = "auto", telemetry: BuildTelemetry | None = None
) -> CjkProbeResult:
    """Compile and extract a minimal Chinese document with the selected engine."""
    selected = engine
    if selected == "auto":
        selected = "tectonic" if shutil.which("tectonic") else "latex"
    if selected == "tectonic":
        executable = shutil.which("tectonic")
        if executable is None:
            return CjkProbeResult(False, "Tectonic is not available.")
    elif selected == "latex":
        if shutil.which("latexmk") is None or shutil.which("xelatex") is None:
            return CjkProbeResult(False, "latexmk and XeLaTeX are required.")
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
        command: list[str]
        if selected == "tectonic":
            command = [
                executable or "tectonic",
                "-X",
                "compile",
                f"--outdir={output}",
                str(source),
            ]
        else:
            command = [
                shutil.which("latexmk") or "latexmk",
                "-xelatex",
                f"-outdir={output}",
                str(source),
            ]
        if telemetry is not None:
            telemetry.latex_invocations += 1
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


def ensure_cjk_environment(
    config: ProjectConfig,
    engine: str | None = None,
    telemetry: BuildTelemetry | None = None,
) -> None:
    """Block Chinese targets unless the real CJK probe succeeds."""
    if config.language != "zh" and config.metadata.publisher != "chinese":
        return
    result = probe_cjk_environment(engine or config.engine, telemetry)
    if not result.ready:
        raise WorkflowError(f"Chinese environment is blocked: {result.detail}")


def resolve_engine(config: ProjectConfig, override: str | None = None) -> str:
    """Resolve a configured compiler without changing the environment."""
    requested = select_engine(override or config.engine)
    if requested == "tectonic":
        return requested
    if requested == "latex":
        _latex_driver(config)
        if shutil.which("bibtex") is None and shutil.which("biber") is None:
            raise WorkflowError("BibTeX or Biber is required for latex mode.")
        return requested
    raise WorkflowError(f"Unsupported engine: {requested}")


def select_engine(requested: str) -> str:
    """Apply the canonical explicit/automatic engine selection policy."""
    if requested == "auto":
        if shutil.which("tectonic") is not None:
            requested = "tectonic"
        elif shutil.which("latexmk") is not None:
            requested = "latex"
        else:
            raise WorkflowError("No supported LaTeX engine is available.")
    if requested == "tectonic":
        if shutil.which("tectonic") is None:
            raise WorkflowError("Tectonic is not available.")
        return requested
    if requested == "latex":
        if shutil.which("latexmk") is None:
            raise WorkflowError("latexmk is not available.")
        return requested
    raise WorkflowError(f"Unsupported engine: {requested}")


def _latex_driver(config: ProjectConfig) -> tuple[str, str]:
    """Return the latexmk flag and executable selected for one manuscript."""
    if config.language == "zh" or config.metadata.publisher == "chinese":
        if shutil.which("xelatex") is None:
            raise WorkflowError("XeLaTeX is required for Chinese latex mode.")
        return "-xelatex", "xelatex"
    if shutil.which("pdflatex") is not None:
        return "-pdf", "pdflatex"
    if shutil.which("xelatex") is not None:
        return "-xelatex", "xelatex"
    raise WorkflowError("pdfLaTeX or XeLaTeX is required for latex mode.")


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


def publish_file_atomically(source: Path, target: Path) -> Path:
    """Copy one generated file through a sibling temporary and atomic replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.new")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def compile_tex(
    source: Path,
    build_dir: Path,
    config: ProjectConfig,
    engine_override: str | None = None,
    *,
    keep_intermediates: bool = False,
    telemetry: BuildTelemetry | None = None,
) -> CompileResult:
    """Compile one source with all compiler output isolated in ``build_dir``."""
    if not source.is_file():
        raise WorkflowError(f"TeX source is missing: {source}")
    build_dir.mkdir(parents=True, exist_ok=True)
    selected = resolve_engine(config, engine_override)
    if selected == "tectonic":
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
        driver_flag, _driver = _latex_driver(config)
        command = [
            shutil.which("latexmk") or "latexmk",
            driver_flag,
            f"-outdir={build_dir}",
            "-interaction=nonstopmode",
            "-halt-on-error",
            str(source),
        ]
    if telemetry is not None:
        telemetry.latex_invocations += 1
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


def _bibliography_cache_key(
    source: Path,
    flattened: str,
    config: ProjectConfig,
    engine_override: str | None,
) -> str:
    """Hash deterministic inputs that affect a materialized bibliography."""
    digest = hashlib.sha256()
    digest.update(flattened.encode("utf-8"))
    digest.update(b"\0")
    selected_engine = resolve_engine(config, engine_override)
    digest.update(selected_engine.encode("utf-8"))
    executable_name = "tectonic" if selected_engine == "tectonic" else "latexmk"
    executable = shutil.which(executable_name)
    if executable is not None:
        executable_path = Path(executable).resolve()
        stat = executable_path.stat()
        digest.update(str(executable_path).encode("utf-8"))
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    relevant_suffixes = {".bbx", ".bib", ".bst", ".cbx", ".cls", ".sty", ".tex"}
    for path in sorted(
        item
        for item in source.parent.rglob("*")
        if item.is_file() and item.suffix.lower() in relevant_suffixes
    ):
        digest.update(path.relative_to(source.parent).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def materialize_bibliography(
    source: Path,
    flattened: str,
    build_dir: Path,
    config: ProjectConfig,
    engine_override: str | None,
    telemetry: BuildTelemetry | None = None,
    cache_root: Path | None = None,
) -> str:
    """Compile one staged round and return its cached publisher-rendered BBL."""
    if not scan_tex_commands(flattened, ("bibliography",), field_count=1):
        raise WorkflowError("Manuscript has no active bibliography command.")
    cache: Path | None = None
    if cache_root is not None:
        key = _bibliography_cache_key(source, flattened, config, engine_override)
        cache = cache_root / f"{key}.bbl"
        if cache.is_file():
            if telemetry is not None:
                telemetry.bibliography_cache_hits += 1
            return cache.read_text(encoding="utf-8")
    if telemetry is not None:
        telemetry.bibliography_invocations += 1
    compile_tex(
        source,
        build_dir,
        config,
        engine_override,
        keep_intermediates=True,
        telemetry=telemetry,
    )
    bibliography = build_dir / f"{source.stem}.bbl"
    if not bibliography.is_file():
        raise WorkflowError(
            "Compiler did not materialize the expected bibliography .bbl."
        )
    rendered = bibliography.read_text(encoding="utf-8")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".bbl.new")
        try:
            temporary.write_text(rendered, encoding="utf-8")
            os.replace(temporary, cache)
        finally:
            if temporary.is_file():
                temporary.unlink()
    return rendered


def relocate_pre_document_section_inputs(text: str) -> str:
    """Move visible section inputs into the document in a staged source copy."""
    marker = r"\begin{document}"
    boundary = text.find(marker)
    if boundary < 0:
        raise WorkflowError("Manuscript source does not contain \\begin{document}.")
    preamble = text[:boundary]
    matches = tuple(PRE_DOCUMENT_SECTION_INPUT.finditer(preamble))
    if not matches:
        return text
    visible_inputs = "".join(match.group(0) for match in matches).rstrip()
    for match in reversed(matches):
        preamble = preamble[: match.start()] + preamble[match.end() :]
    document = text[boundary + len(marker) :]
    return f"{preamble.rstrip()}\n\n{marker}\n\n{visible_inputs}\n{document.lstrip()}"


def enable_dvips_named_colors(text: str) -> str:
    """Enable xcolor's dvips names before a staged publisher class loads it."""
    match = DOCUMENTCLASS.search(text)
    if match is None:
        raise WorkflowError("Manuscript source does not contain \\documentclass.")
    if DVIPSNAMES_OPTION in text[: match.start()]:
        return text
    return text[: match.start()] + DVIPSNAMES_OPTION + "\n" + text[match.start() :]


def _render_preamble(config: ProjectConfig, target: Path) -> None:
    source = resources_root() / "manuscript_preamble"
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
        manuscript = target / "manuscript.tex"
        shutil.copy2(version / "manuscript.tex", manuscript)
        manuscript_text = manuscript.read_text(encoding="utf-8")
        if config.metadata.publisher == "chinese":
            manuscript_text = relocate_pre_document_section_inputs(manuscript_text)
        manuscript.write_text(
            enable_dvips_named_colors(manuscript_text),
            encoding="utf-8",
        )
        for directory in ("sections", "figures", "tables"):
            source = version / directory
            if source.exists():
                shutil.copytree(source, target / directory, dirs_exist_ok=True)
    else:
        for directory in ("figures", "tables"):
            source = version / directory
            if source.exists():
                shutil.copytree(source, target / directory, dirs_exist_ok=True)
    shutil.copy2(
        bibliography_source_for_round(config, round_number),
        target / "references.bib",
    )
    for resource in publisher_resource(config).iterdir():
        destination = target / resource.name
        if resource.is_dir():
            shutil.copytree(resource, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(resource, destination)
    _render_preamble(config, target / "preamble")
    (target / "preamble.tex").write_text(
        f"\\input{{preamble/{config.language}}}\n", encoding="utf-8"
    )
    generate_metadata(version, target)
    return target / "manuscript.tex"


def build_clean_manuscript(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None = None,
    telemetry: BuildTelemetry | None = None,
) -> Path:
    """Build and publish the clean PDF for one existing version."""
    preflight = (
        telemetry.measure("preflight") if telemetry else contextlib.nullcontext()
    )
    with preflight:
        ensure_cjk_environment(config, engine_override, telemetry)
    source_stage = (
        telemetry.measure("source_projection")
        if telemetry
        else contextlib.nullcontext()
    )
    with source_stage:
        source_dir = run_dir / "clean_source"
        source = stage_runtime_resources(
            config, round_number, source_dir, include_manuscript=True
        )
    compile_stage = (
        telemetry.measure("clean_compile") if telemetry else contextlib.nullcontext()
    )
    with compile_stage:
        compiled = compile_tex(
            source,
            run_dir / "clean_build",
            config,
            engine_override,
            keep_intermediates=True,
            telemetry=telemetry,
        )
    output_dir = config.output_dir(round_number)
    filename = "manuscript.pdf" if round_number == 0 else "manuscript_clean.pdf"
    target = output_dir / filename
    publish_stage = (
        telemetry.measure("artifact_publish") if telemetry else contextlib.nullcontext()
    )
    with publish_stage:
        return publish_file_atomically(compiled.pdf, target)
