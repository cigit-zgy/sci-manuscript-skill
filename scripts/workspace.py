"""Project structure, revision ancestry, bibliography sync, and temporary runs."""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml
from metadata import (
    ManuscriptMetadata,
    generate_author_metadata,
    load_manuscript,
    save_manuscript,
    with_revision,
)

SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSETS = SKILL_ROOT / "assets"
ROUND_PATTERN = re.compile(r"^r(0|[1-9]\d*)$")
REVISION_DIRECTORY_PATTERN = re.compile(r"^revision_([1-9]\d*)$")
ENTRYPOINT_MARKER = "%%SCI_MANUSCRIPT_SKILL_ROOT%%"


class WorkflowError(RuntimeError):
    """Raised when a lifecycle invariant or required resource is violated."""


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

    def round_dir(self, round_number: int) -> Path:
        """Return one user-facing manuscript version directory."""
        if round_number < 0:
            raise WorkflowError("Round numbers must be non-negative.")
        return self.project / round_directory_name(round_number)


def round_name(round_number: int) -> str:
    """Format a non-negative internal round number as ``rN``."""
    if round_number < 0:
        raise WorkflowError("Round numbers must be non-negative.")
    return f"r{round_number}"


def round_directory_name(round_number: int) -> str:
    """Map an internal round number to its user-facing directory name."""
    if round_number < 0:
        raise WorkflowError("Round numbers must be non-negative.")
    return "initial_submission" if round_number == 0 else f"revision_{round_number}"


def parse_round(value: str | int | None, default: int | None = None) -> int:
    """Parse ``rN`` or a semantic directory name into an internal number."""
    if value is None:
        if default is None:
            raise WorkflowError("A round is required.")
        return default
    if isinstance(value, int):
        if value < 0:
            raise WorkflowError("Round numbers must be non-negative.")
        return value
    normalized = value.strip().lower()
    if normalized == "initial_submission":
        return 0
    internal_match = ROUND_PATTERN.fullmatch(normalized)
    if internal_match is not None:
        return int(internal_match.group(1))
    semantic_match = REVISION_DIRECTORY_PATTERN.fullmatch(normalized)
    if semantic_match is not None:
        return int(semantic_match.group(1))
    raise WorkflowError(
        f"Invalid round {value!r}; use r0, r1, initial_submission, or revision_N."
    )


def normalize_project(path: str | Path) -> Path:
    """Resolve a user-selected project root without inventing a child path."""
    return Path(path).expanduser().resolve()


def _round_number_from_directory(name: str) -> int | None:
    match = REVISION_DIRECTORY_PATTERN.fullmatch(name)
    return int(match.group(1)) if match is not None else None


def _round_numbers(project: Path) -> tuple[int, ...]:
    if not (project / "initial_submission" / "manuscript.yaml").is_file():
        raise WorkflowError(f"Project is not initialized: {project}")
    shared = project / "references"
    required_shared = (
        shared / "authors.yaml",
        shared / "references.bib",
        shared / "revision_style.tex",
        shared / "journal_template",
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
        version = root / round_directory_name(number)
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
    selected_dir = root / round_directory_name(selected)
    metadata = load_manuscript(selected_dir / "manuscript.yaml")
    return ProjectConfig(root, metadata)


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
    if target.exists():
        raise WorkflowError(f"Refusing to overwrite user file: {target}")
    text = source.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"%%{key}%%", value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _install_project_entrypoint(project: Path) -> None:
    source = SKILL_ROOT / "scripts" / "run.py"
    text = source.read_text(encoding="utf-8")
    text = text.replace(ENTRYPOINT_MARKER, str(SKILL_ROOT))
    target = project / "run.py"
    target.write_text(text, encoding="utf-8")
    target.chmod(0o755)


def _publisher_layout(
    config: ProjectConfig,
) -> tuple[list[dict[str, str]], str, str]:
    path = (
        config.references
        / "journal_template"
        / config.metadata.publisher
        / "sections.yaml"
    )
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
        config.references
        / "journal_template"
        / config.metadata.publisher
        / "workflow.tex",
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
    render_template(
        ASSETS / "manuscript" / "preamble.tex",
        version / "preamble.tex",
        {
            "CJK_PACKAGE": cjk,
            "BIBLIOGRAPHY_PACKAGE": bibliography_package,
        },
    )
    default_sections = ASSETS / "manuscript" / "sections" / "default"
    for item in plan:
        render_template(
            default_sections / item["source"],
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
        initial / "output",
        root / "tmp",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        ASSETS / "journal_templates",
        config.references / "journal_template",
    )
    author_library = authors_source or ASSETS / "authors.yaml"
    if not author_library.is_file():
        raise WorkflowError(f"Author library is missing: {author_library}")
    shutil.copy2(author_library, config.references / "authors.yaml")
    shutil.copy2(
        ASSETS / "revision_style.tex",
        config.references / "revision_style.tex",
    )
    bibliography = bibliography_source or ASSETS / "manuscript" / "references.bib"
    if not bibliography.is_file():
        raise WorkflowError(f"Bibliography source is missing: {bibliography}")
    shutil.copy2(bibliography, config.references / "references.bib")
    _create_manuscript_sources(config, initial)
    save_manuscript(initial / "manuscript.yaml", config.metadata)
    generate_author_metadata(root, initial)
    _install_project_entrypoint(root)
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
    for tex_file in [
        staged / "manuscript.tex",
        *sorted((staged / "sections").rglob("*.tex")),
    ]:
        normalized = strip_provenance_wrappers(tex_file.read_text(encoding="utf-8"))
        tex_file.write_text(normalized, encoding="utf-8")
    for generated_directory in (staged / "output", staged / "response"):
        generated_directory.mkdir()
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
        render_template(
            ASSETS / "submission" / f"cover_letter_{config.language}.tex",
            target / "cover_letter.tex",
            values,
        )
    if settings.highlights and not (target / "highlights.tex").exists():
        render_template(
            ASSETS / "submission" / "highlights.tex",
            target / "highlights.tex",
            values,
        )
    checklist = target / "checklist.md"
    if not checklist.exists():
        shutil.copy2(ASSETS / "submission" / "checklist.md", checklist)
    if settings.graphical_abstract:
        graphical = target / "graphical_abstract"
        graphical.mkdir(exist_ok=True)
        graphical_source = graphical / "graphical_abstract.tex"
        if not graphical_source.exists():
            shutil.copy2(
                ASSETS / "submission" / "graphical_abstract" / "graphical_abstract.tex",
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
