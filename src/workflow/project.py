"""Project structure, revision ancestry, bibliography checks, and temporary runs."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml

from ..metadata.manuscript import (
    ManuscriptMetadata,
    generate_author_metadata,
    load_manuscript,
    save_manuscript,
    with_revision,
)
from ..resources import (
    copy_resource_file,
    copy_resource_tree,
    read_resource_text,
)
from ..latex.numbering import (
    REVISION_DIRECTORY_PATTERN as REVISION_DIRECTORY_PATTERN,
)
from ..latex.numbering import (
    ROUND_PATTERN as ROUND_PATTERN,
)
from ..latex.numbering import (
    parse_round as parse_round_value,
)
from ..latex.numbering import (
    round_directory_name,
    round_name,
)

CITATION_PATTERN = re.compile(
    r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|nocite|parencite|"
    r"textcite|autocite|footcite|smartcite|supercite)"
    r"\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}"
)
BIBTEX_ENTRY_PATTERN = re.compile(
    r"@[A-Za-z]+\s*[({]\s*([^,\s]+)\s*,",
    re.MULTILINE,
)


from ..exceptions import WorkflowError  # noqa: F401 (re-exported)
from ..results import (
    Artifact,
    ChainDiagnosticsResult,
    CheckResult,
    StatusResult,
    ZoteroSetupResult,
    BibliographySyncResult,
)


@dataclass(frozen=True)
class ProjectConfig:
    """Resolved view of one manuscript version and its project paths."""

    project: Path
    metadata: ManuscriptMetadata
    engine: str = "auto"

    @property
    def title(self) -> str:
        """Return the manuscript title."""
        return self.metadata.title

    @property
    def journal(self) -> str:
        """Return the target journal name."""
        return self.metadata.journal_name

    @property
    def article_type(self) -> str:
        """Return the article type."""
        return self.metadata.article_type

    @property
    def language(self) -> str:
        """Return the manuscript and correspondence language."""
        return self.metadata.language

    @property
    def response_language(self) -> str:
        """Return the response template language."""
        return self.metadata.language

    @property
    def current_round(self) -> int:
        """Return the internal revision number."""
        return self.metadata.round_number

    @property
    def references(self) -> Path:
        """Return the manuscript-level shared references directory."""
        return self.project / "references"

    @property
    def journal_templates(self) -> Path:
        """Return the shared publisher resources, including the v3.0 fallback."""
        current = self.references / "journal_templates"
        legacy = self.references / "journal_template"
        return current if current.exists() or not legacy.exists() else legacy

    def round_dir(self, round_number: int) -> Path:
        """Return one user-facing manuscript version directory."""
        if round_number < 0:
            raise WorkflowError("Round numbers must be non-negative.")
        return actual_round_directory(self.project, round_number)


def parse_round(value: str | int | None, default: int | None = None) -> int:
    """Parse ``rN``/``rNN`` or a semantic directory name into an internal number."""
    parsed = parse_round_value(value, default)
    if parsed is None:
        if value is None:
            raise WorkflowError("A round is required.")
        raise WorkflowError(
            f"Invalid round {value!r}; use r00, r01, initial_submission, or revision_01."
        )
    return parsed


def normalize_project(path: str | Path) -> Path:
    """Resolve a user-selected project root without inventing a child path."""
    return Path(path).expanduser().resolve()


def actual_round_directory(project: Path, round_number: int) -> Path:
    """Resolve one version directory, accepting legacy single-digit names.

    New projects use canonical names (``revision_01``); legacy projects may
    still carry ``revision_1`` directories. The canonical name wins when both
    exist.
    """
    canonical = project / round_directory_name(round_number)
    if canonical.is_dir() or round_number == 0:
        return canonical
    legacy = project / f"revision_{round_number}"
    return legacy if legacy.is_dir() else canonical


def _round_number_from_directory(name: str) -> int | None:
    match = REVISION_DIRECTORY_PATTERN.fullmatch(name)
    return int(match.group(1)) if match is not None else None


def _round_numbers(project: Path) -> tuple[int, ...]:
    if not (project / "initial_submission" / "manuscript.yaml").is_file():
        raise WorkflowError(f"Project is not initialized: {project}")
    shared = project / "references"
    template_directory = (
        shared / "journal_templates"
        if (shared / "journal_templates").exists()
        else shared / "journal_template"
    )
    required_shared = (
        shared / "authors.yaml",
        shared / "references.bib",
        shared / "revision_style.tex",
        template_directory,
    )
    missing_shared = [path for path in required_shared if not path.exists()]
    if missing_shared:
        missing = ", ".join(path.name for path in missing_shared)
        raise WorkflowError(f"Shared references are incomplete: {missing}.")
    forbidden = project / "revision_0"
    if forbidden.exists():
        raise WorkflowError(f"Forbidden lifecycle directory exists: {forbidden}")
    numbers = sorted(
        number
        for path in project.iterdir()
        if path.is_dir()
        if (number := _round_number_from_directory(path.name)) is not None
    )
    numbers.insert(0, 0)
    expected = list(range(numbers[-1] + 1))
    if numbers != expected:
        raise WorkflowError(
            f"Revision directories must be continuous; observed {numbers}."
        )
    return tuple(numbers)


def is_initialized(project: Path) -> bool:
    """Return whether the semantic initial-submission configuration exists."""
    return (project / "initial_submission" / "manuscript.yaml").is_file()


def load_project(
    project: str | Path,
    round_number: int | None = None,
) -> ProjectConfig:
    """Load one version and verify the complete adjacent ancestry."""
    root = normalize_project(project)
    numbers = _round_numbers(root)
    selected = numbers[-1] if round_number is None else round_number
    if selected not in numbers:
        raise WorkflowError(f"Round {round_name(selected)} does not exist yet.")
    for number in numbers:
        version = actual_round_directory(root, number)
        if (version / "references").exists():
            raise WorkflowError(
                f"Version directories must not contain references/: {version}"
            )
        path = version / "manuscript.yaml"
        metadata = load_manuscript(path)
        if metadata.round_number != number:
            raise WorkflowError(
                f"{path} declares r{metadata.round_number}, expected r{number}."
            )
    selected_dir = actual_round_directory(root, selected)
    metadata = load_manuscript(selected_dir / "manuscript.yaml")
    return ProjectConfig(root, metadata)


def scientific_source_hashes(project: Path) -> dict[str, str]:
    """Hash user-controlled manuscript TeX sources across every version."""
    hashes: dict[str, str] = {}
    for number in _round_numbers(project):
        version = actual_round_directory(project, number)
        sources = [version / "manuscript.tex", version / "preamble.tex"]
        for directory in ("sections", "figures", "tables"):
            root = version / directory
            if root.exists():
                sources.extend(sorted(root.rglob("*.tex")))
        for source in sources:
            if source.is_file():
                relative = source.relative_to(project).as_posix()
                hashes[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
    return hashes


GENERATED_VERSION_PART = frozenset({"output", "tmp", "package"})


def user_source_hashes(
    version_dir: Path,
    *,
    normalize_tex: bool = False,
) -> dict[str, str]:
    """Hash user-editable sources of one version, excluding generated artifacts.

    Generated outputs (``output/``), submission packages (``submission/package/``),
    and compiler staging are not user sources and never block a rollback. With
    ``normalize_tex``, TeX sources are compared after stripping inherited
    provenance wrappers, so a fresh revision copied from its parent is not
    mistaken for a user edit.
    """
    hashes: dict[str, str] = {}
    if not version_dir.is_dir():
        return hashes
    for path in sorted(version_dir.rglob("*")):
        if not path.is_file() or path.suffix not in {".tex", ".md", ".yaml", ".bib"}:
            continue
        parts = path.relative_to(version_dir).parts
        if parts[0] in GENERATED_VERSION_PART or "package" in parts:
            continue
        relative = path.relative_to(version_dir).as_posix()
        if normalize_tex and path.suffix == ".tex":
            text = strip_provenance_wrappers(path.read_text(encoding="utf-8"))
            hashes[relative] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        else:
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def scan_round_directories(project: Path) -> tuple[int, ...]:
    """Scan existing round directories allowing gaps (for broken-chain repair).

    Unlike :func:`_round_numbers`, this does not require a continuous sequence,
    so it can inspect a chain after a user deleted an intermediate revision.
    """
    if not (project / "initial_submission" / "manuscript.yaml").is_file():
        raise WorkflowError(f"Project is not initialized: {project}")
    numbers = sorted(
        number
        for path in project.iterdir()
        if path.is_dir()
        if (number := _round_number_from_directory(path.name)) is not None
    )
    return (0, *numbers)


def _latex_escape(value: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in value)


def template_values(config: ProjectConfig) -> dict[str, str]:
    """Return non-author replacements shared by correspondence templates."""
    return {
        "TITLE": _latex_escape(config.title),
        "JOURNAL": _latex_escape(config.journal),
        "ARTICLE_TYPE": _latex_escape(config.article_type),
        "EDITOR_NAME": "Editor",
    }


def render_template(source: Path, target: Path, values: dict[str, str]) -> None:
    """Render one tokenized UTF-8 template without overwriting user content."""
    _render_template_text(source.read_text(encoding="utf-8"), target, values)


def _render_resource_template(
    parts: tuple[str, ...],
    target: Path,
    values: dict[str, str],
) -> None:
    _render_template_text(read_resource_text(*parts), target, values)


def _render_template_text(
    text: str,
    target: Path,
    values: dict[str, str],
) -> None:
    if target.exists():
        raise WorkflowError(f"Refusing to overwrite user file: {target}")
    for key, value in values.items():
        text = text.replace(f"%%{key}%%", value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")



def _publisher_layout(
    config: ProjectConfig,
) -> tuple[list[dict[str, str]], str, str]:
    path = config.journal_templates / config.metadata.publisher / "sections.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowError(f"Cannot load publisher section mapping: {path}") from exc
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list) or not sections:
        raise WorkflowError(f"Publisher section mapping is empty: {path}")
    bibliography = data.get("bibliography")
    if not isinstance(bibliography, dict):
        raise WorkflowError(f"Publisher bibliography mapping is missing: {path}")
    bibliography_package = str(bibliography.get("package", "")).strip()
    bibliography_style = str(bibliography.get("style", "")).strip()
    if not bibliography_package or not bibliography_style:
        raise WorkflowError(f"Publisher bibliography mapping is incomplete: {path}")
    plan: list[dict[str, str]] = []
    for index, item in enumerate(sections, 1):
        if not isinstance(item, dict):
            raise WorkflowError(f"Invalid section mapping item {index}: {path}")
        try:
            plan.append(
                {
                    "file": str(item["file"]),
                    "source": str(item["source"]),
                    "title": str(item.get("title", "")),
                }
            )
        except KeyError as exc:
            raise WorkflowError(
                f"Section mapping item {index} lacks {exc.args[0]}: {path}"
            ) from exc
    return plan, bibliography_package, bibliography_style


def _create_manuscript_sources(config: ProjectConfig, version: Path) -> None:
    plan, bibliography_package, bibliography_style = _publisher_layout(config)
    abstract = plan[0]
    section_inputs = "\n".join(
        f"\\input{{sections/{Path(item['file']).stem}}}" for item in plan[1:]
    )
    render_template(
        config.journal_templates / config.metadata.publisher / "workflow.tex",
        version / "manuscript.tex",
        {
            "ABSTRACT_INPUT": (f"\\input{{sections/{Path(abstract['file']).stem}}}"),
            "SECTION_INPUTS": section_inputs,
            "BIBLIOGRAPHY_STYLE": bibliography_style,
            "BIBLIOGRAPHY_PATH": "references/references",
        },
    )
    cjk = (
        "\\usepackage{xeCJK}\n  \\renewcommand{\\abstractname}{摘要}"
        if config.language == "zh"
        else ""
    )
    _render_resource_template(
        ("manuscript", "preamble.tex"),
        version / "preamble.tex",
        {
            "CJK_PACKAGE": cjk,
            "BIBLIOGRAPHY_PACKAGE": bibliography_package,
        },
    )
    for item in plan:
        _render_resource_template(
            ("manuscript", "sections", "default", item["source"]),
            version / "sections" / item["file"],
            {"SECTION_TITLE": item["title"]},
        )


def initialize_project(
    config: ProjectConfig,
    authors_source: Path | None = None,
    bibliography_source: Path | None = None,
) -> ProjectConfig:
    """Create a root entrypoint, shared references, and initial submission."""
    root = config.project
    if root.exists() and any(root.iterdir()):
        raise WorkflowError(f"Refusing to initialize non-empty project: {root}")
    if config.current_round != 0 or config.metadata.parent_round is not None:
        raise WorkflowError("Initialization metadata must describe r0 with no parent.")
    root.mkdir(parents=True, exist_ok=True)
    initial = config.round_dir(0)
    for directory in (
        config.references,
        initial / "sections",
        initial / "figures",
        initial / "tables",
        initial / "submission",
        initial / "output",
        root / "tmp",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    copy_resource_tree(
        ("journal_templates",),
        config.references / "journal_templates",
    )
    if authors_source is None:
        copy_resource_file(("authors.yaml",), config.references / "authors.yaml")
    else:
        if not authors_source.is_file():
            raise WorkflowError(f"Author library is missing: {authors_source}")
        shutil.copy2(authors_source, config.references / "authors.yaml")
    copy_resource_file(
        ("revision_style.tex",),
        config.references / "revision_style.tex",
    )
    if bibliography_source is None:
        copy_resource_file(
            ("manuscript", "references.bib"),
            config.references / "references.bib",
        )
    else:
        if not bibliography_source.is_file():
            raise WorkflowError(
                f"Bibliography source is missing: {bibliography_source}"
            )
        shutil.copy2(bibliography_source, config.references / "references.bib")
    _setup_zotero_files(root)
    _create_manuscript_sources(config, initial)
    save_manuscript(initial / "manuscript.yaml", config.metadata)
    generate_author_metadata(root, initial)
    return config


def _skip_space(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _extract_braced(text: str, position: int) -> tuple[str, int]:
    position = _skip_space(text, position)
    if position >= len(text) or text[position] != "{":
        raise ValueError("Expected a braced field.")
    depth = 0
    escaped = False
    for cursor in range(position, len(text)):
        character = text[cursor]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[position + 1 : cursor], cursor + 1
    raise ValueError("Unbalanced braces in revision provenance wrapper.")


def strip_provenance_wrappers(text: str) -> str:
    """Make inherited ``review`` and ``selfadd`` wrappers transparent."""
    output = text
    changed = True
    while changed:
        changed = False
        for command, field_count in ((r"\review", 2), (r"\selfadd", 1)):
            cursor = 0
            pieces: list[str] = []
            while True:
                start = output.find(command, cursor)
                if start < 0:
                    pieces.append(output[cursor:])
                    break
                end = start + len(command)
                if end < len(output) and output[end].isalpha():
                    pieces.append(output[cursor:end])
                    cursor = end
                    continue
                try:
                    fields: list[str] = []
                    for _ in range(field_count):
                        field, end = _extract_braced(output, end)
                        fields.append(field)
                except ValueError:
                    pieces.append(output[cursor:end])
                    cursor = end
                    continue
                pieces.extend((output[cursor:start], fields[-1]))
                cursor = end
                changed = True
            output = "".join(pieces)
    return output


def start_revision(
    config: ProjectConfig,
    target_round: int,
    staging_root: Path,
) -> ProjectConfig:
    """Create exactly the next revision from the current highest version."""
    latest = load_project(config.project)
    if config.current_round != latest.current_round:
        raise WorkflowError("A revision must start from the current highest round.")
    expected = config.current_round + 1
    if target_round != expected:
        raise WorkflowError(
            f"Revision chain violation: current is r{config.current_round}; "
            f"the only valid next round is r{expected}."
        )
    source = config.round_dir(config.current_round)
    target = config.round_dir(target_round)
    if target.exists():
        raise WorkflowError(f"Revision already exists: {target}")
    staged = staging_root / round_directory_name(target_round)
    staged.mkdir(parents=True, exist_ok=False)
    for filename in ("manuscript.tex", "preamble.tex"):
        source_file = source / filename
        if not source_file.exists():
            raise WorkflowError(f"Previous version source is missing: {source_file}")
        shutil.copy2(source_file, staged / filename)
    for directory_name in ("sections", "figures", "tables"):
        source_dir = source / directory_name
        if source_dir.exists():
            shutil.copytree(source_dir, staged / directory_name)
        else:
            (staged / directory_name).mkdir()
    source_submission = source / "submission"
    if source_submission.exists():
        shutil.copytree(
            source_submission,
            staged / "submission",
            ignore=shutil.ignore_patterns("package"),
        )
    else:
        (staged / "submission").mkdir()
    source_response = source / "response"
    if source_response.exists():
        shutil.copytree(
            source_response,
            staged / "response",
            ignore=shutil.ignore_patterns(
                "response_letter.tex",
                "reviewer_comments.md",
                "*.pdf",
            ),
        )
    else:
        (staged / "response").mkdir()
    for tex_file in [
        staged / "manuscript.tex",
        *sorted((staged / "sections").rglob("*.tex")),
    ]:
        normalized = strip_provenance_wrappers(tex_file.read_text(encoding="utf-8"))
        tex_file.write_text(normalized, encoding="utf-8")
    (staged / "output").mkdir()
    (staged / "response" / "reviewer_comments.md").write_text(
        "# Reviewer #1\n\nGeneral comment.\n\n1. First specific comment.\n",
        encoding="utf-8",
    )
    child_metadata = with_revision(config.metadata, target_round)
    save_manuscript(staged / "manuscript.yaml", child_metadata)
    shutil.move(str(staged), str(target))
    return ProjectConfig(config.project, child_metadata, config.engine)


def ensure_submission_workspace(config: ProjectConfig, round_number: int) -> Path:
    """Create enabled submission sources inside the selected version."""
    if round_number != config.current_round:
        raise WorkflowError("Submission config must match the selected version.")
    target = config.round_dir(round_number) / "submission"
    values = template_values(config)
    values["AUTHOR_METADATA_PATH"] = "../../references/author_metadata.tex"
    target.mkdir(parents=True, exist_ok=True)
    settings = config.metadata.submission
    if settings.cover_letter and not (target / "cover_letter.tex").exists():
        _render_resource_template(
            ("submission", f"cover_letter_{config.language}.tex"),
            target / "cover_letter.tex",
            values,
        )
    if settings.highlights and not (target / "highlights.tex").exists():
        _render_resource_template(
            ("submission", "highlights.tex"),
            target / "highlights.tex",
            values,
        )
    checklist = target / "checklist.md"
    if not checklist.exists():
        copy_resource_file(("submission", "checklist.md"), checklist)
    if settings.graphical_abstract:
        graphical = target / "graphical_abstract"
        graphical.mkdir(exist_ok=True)
        graphical_source = graphical / "graphical_abstract.tex"
        if not graphical_source.exists():
            copy_resource_file(
                ("submission", "graphical_abstract", "graphical_abstract.tex"),
                graphical_source,
            )
    (target / "package").mkdir(exist_ok=True)
    return target


def _find_bib_export(project: Path, explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser().resolve())
    environment = os.environ.get("ZOTERO_BETTER_BIBTEX_EXPORT")
    if environment:
        candidates.append(Path(environment).expanduser().resolve())
    candidates.extend(
        [
            project / "references" / "zotero-export.bib",
            project / "zotero-export.bib",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise WorkflowError(
        "No Better BibTeX export was found. Use --bib-export PATH, set "
        "ZOTERO_BETTER_BIBTEX_EXPORT, or create references/zotero-export.bib."
    )


def sync_bibliography(project: Path, explicit: Path | None = None) -> tuple[Path, ...]:
    """Atomically replace the manuscript-level shared BibTeX file."""
    if not is_initialized(project):
        raise WorkflowError(f"Project is not initialized: {project}")
    source = _find_bib_export(project, explicit)
    text = source.read_text(encoding="utf-8")
    if "@" not in text or "{" not in text:
        raise WorkflowError(
            f"Bibliography export does not contain BibTeX entries: {source}"
        )
    target = project / "references" / "references.bib"
    temporary = target.with_suffix(".bib.new")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return (target,)


def _setup_zotero_files(project: Path) -> tuple[Path, Path]:
    """Prepare the shared export target and user guide without controlling Zotero."""
    references = project / "references"
    if not references.is_dir():
        raise WorkflowError(f"Shared references directory is missing: {references}")
    bibliography = references / "references.bib"
    if bibliography.exists() and not bibliography.is_file():
        raise WorkflowError(f"Bibliography target is not a file: {bibliography}")
    if not bibliography.exists():
        bibliography.write_text("", encoding="utf-8")
    guide = references / "zotero_setup.md"
    if guide.exists() and not guide.is_file():
        raise WorkflowError(f"Zotero setup target is not a file: {guide}")
    if not guide.exists():
        _render_resource_template(
            ("manuscript", "zotero_setup.md"),
            guide,
            {"EXPORT_PATH": "references/references.bib"},
        )
    return bibliography, guide


def _without_latex_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        cursor = 0
        while True:
            marker = line.find("%", cursor)
            if marker < 0:
                lines.append(line)
                break
            backslashes = 0
            index = marker - 1
            while index >= 0 and line[index] == "\\":
                backslashes += 1
                index -= 1
            if backslashes % 2 == 0:
                lines.append(line[:marker])
                break
            cursor = marker + 1
    return "\n".join(lines)


def _manuscript_tex_sources(round_dir: Path) -> tuple[Path, ...]:
    candidates = [round_dir / "manuscript.tex", round_dir / "preamble.tex"]
    for directory_name in ("sections", "tables"):
        directory = round_dir / directory_name
        if directory.is_dir():
            candidates.extend(sorted(directory.rglob("*.tex")))
    return tuple(dict.fromkeys(path for path in candidates if path.is_file()))


def check_citations(config: ProjectConfig, round_number: int) -> tuple[str, ...]:
    """Return manuscript citation keys absent from the shared BibTeX database."""
    if round_number != config.current_round:
        raise WorkflowError("Citation config must match the selected version.")
    bibliography = config.references / "references.bib"
    if not bibliography.is_file():
        raise WorkflowError(f"Shared bibliography is missing: {bibliography}")
    cited: set[str] = set()
    for source in _manuscript_tex_sources(config.round_dir(round_number)):
        text = _without_latex_comments(source.read_text(encoding="utf-8"))
        for match in CITATION_PATTERN.finditer(text):
            cited.update(
                key.strip()
                for key in match.group(1).split(",")
                if key.strip() and key.strip() != "*"
            )
    bibliography_text = _without_latex_comments(
        bibliography.read_text(encoding="utf-8")
    )
    available = {
        match.group(1).strip()
        for match in BIBTEX_ENTRY_PATTERN.finditer(bibliography_text)
    }
    return tuple(sorted(cited - available))


@contextlib.contextmanager
def temporary_run(project: Path, keep: bool) -> Iterator[Path]:
    """Create one visible run directory and remove it only after success."""
    root = project / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = root / f"run_{stamp}_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    run_dir.mkdir()
    try:
        yield run_dir
    except Exception:
        print(f"Run failed; temporary files retained: {run_dir.relative_to(project)}")
        raise
    else:
        if keep:
            print(
                "Temporary files retained by --keep-temp: "
                f"{run_dir.relative_to(project)}"
            )
        else:
            shutil.rmtree(run_dir)
            desktop_metadata = root / ".DS_Store"
            if desktop_metadata.exists():
                desktop_metadata.unlink()

def check(
    project: str | Path,
    selected_round: str | int | None,
) -> CheckResult:
    """Validate shared bibliography coverage for one version."""
    root, config, round_number = _selected_project(project, selected_round)
    return CheckResult(
        project=root,
        version=round_directory_name(round_number),
        missing_citations=check_citations(config, round_number),
    )


def status(project: str | Path) -> StatusResult:
    """Resolve current lifecycle state and published final artifacts."""
    root = normalize_project(project)
    _require_project(root)
    latest = load_project(root)
    artifacts: list[Artifact] = []
    for number in range(latest.current_round + 1):
        config = load_project(root, number)
        version_directory = config.round_dir(number)
        paths = sorted((version_directory / "output").glob("*.pdf"))
        paths.extend(sorted((version_directory / "submission" / "package").glob("*")))
        artifacts.extend(Artifact("Generated artifact", path) for path in paths)
    parent = latest.metadata.parent_round
    return StatusResult(
        project=root,
        version=actual_round_directory(root, latest.current_round).name,
        round_number=latest.current_round,
        parent=(
            actual_round_directory(root, parent).name if parent is not None else None
        ),
        authors=latest.metadata.author_names,
        publisher=latest.metadata.publisher,
        journal=latest.journal,
        project_format_version=latest.metadata.format_version,
        artifacts=tuple(artifacts),
    )


def setup_zotero(project: str | Path) -> ZoteroSetupResult:
    """Prepare the shared bibliography target and non-invasive setup guide."""
    root = normalize_project(project)
    _require_project(root)
    bibliography, guide = _setup_zotero_files(root)
    return ZoteroSetupResult(
        project=root,
        artifacts=(
            Artifact("Bibliography target", bibliography),
            Artifact("Setup guide", guide),
        ),
    )


def sync_bib(
    project: str | Path,
    export: str | Path | None,
) -> BibliographySyncResult:
    """Synchronize the explicit export into the one shared bibliography."""
    root = normalize_project(project)
    _require_project(root)
    explicit = Path(export).expanduser().resolve() if export is not None else None
    targets = sync_bibliography(root, explicit)
    return BibliographySyncResult(
        project=root,
        artifacts=tuple(Artifact("Bibliography", target) for target in targets),
    )


def _legacy_wrapper_hash(text: str) -> str:
    normalized = _LEGACY_ROOT_LINE.sub(
        '_SKILL_ROOT_HINT = Path("<GENERATED_SKILL_ROOT>")',
        text,
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def chain_diagnostics(project: str | Path) -> ChainDiagnosticsResult:
    """Inspect the round sequence without requiring a continuous chain."""
    root = normalize_project(project)
    _require_project(root)
    numbers = runtime_workspace.scan_round_directories(root)
    expected = list(range(len(numbers)))
    broken = list(numbers) != expected
    missing = tuple(
        round_directory_name(number) for number in expected if number not in numbers
    )
    versions = tuple(
        (actual_round_directory(root, number).name, round_name(number))
        for number in numbers
    )
    current = versions[-1][0] if versions and not broken else None
    return ChainDiagnosticsResult(
        project=root,
        versions=versions,
        current=current,
        broken=broken,
        missing=missing,
    )


def _require_project(project: Path) -> None:
    if not is_initialized(project):
        raise WorkflowError(
            f"Project is not initialized: {project}. Run the init command first."
        )

