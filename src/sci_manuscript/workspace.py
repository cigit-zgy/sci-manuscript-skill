"""Workspace structure, revision transactions, bibliography, and temporary runs."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Iterator

import yaml

from .errors import ManuscriptError
from .metadata import (
    ManuscriptMetadata,
    load_meta,
    revision_directory_name,
    round_name,
    save_meta,
    with_revision,
)


class WorkflowError(ManuscriptError):
    """Raised when a lifecycle or filesystem invariant is violated."""


REVISION_DIRECTORY_PATTERN = re.compile(r"^revision_(\d{2,})$")
ROUND_PATTERN = re.compile(r"^r(\d{2,})$")
PROTECTED_DIRECTORIES = ("sections", "figures", "tables", "response")
SCIENTIFIC_DIRECTORIES = ("sections", "figures", "tables")


def resources_root() -> Path:
    """Return the installed package-resource directory."""
    resource = files("sci_manuscript.resources")
    return Path(str(resource))


@dataclass(frozen=True)
class ProjectConfig:
    """Resolved view of one manuscript version."""

    project: Path
    metadata: ManuscriptMetadata
    engine: str = "auto"

    @property
    def title(self) -> str:
        """Return the manuscript title."""
        return self.metadata.title

    @property
    def journal(self) -> str:
        """Return the target journal."""
        return self.metadata.journal_name

    @property
    def article_type(self) -> str:
        """Return the configured article type."""
        return self.metadata.article_type

    @property
    def language(self) -> str:
        """Return the manuscript language."""
        return self.metadata.language

    @property
    def current_round(self) -> int:
        """Return the semantic revision number."""
        return self.metadata.round_number

    @property
    def references(self) -> Path:
        """Return the only manuscript-level references directory."""
        return self.project / "references"

    def round_dir(self, round_number: int) -> Path:
        """Return one version directory."""
        return self.project / revision_directory_name(round_number)


def normalize_project(path: str | Path, *, initialize: bool = False) -> Path:
    """Resolve a project argument to its canonical ``manuscript/`` directory."""
    selected = Path(path).expanduser().resolve()
    if initialize:
        return selected / "manuscript"
    if selected.name == "manuscript" and (selected / "initial_submission").exists():
        return selected
    return selected / "manuscript"


def parse_round(value: str | int | None, default: int | None = None) -> int:
    """Parse r00, initial_submission, or revision_01."""
    if value is None:
        if default is None:
            raise WorkflowError("A revision round is required.")
        return default
    if isinstance(value, int):
        if value < 0:
            raise WorkflowError("Round numbers must be non-negative.")
        return value
    normalized = value.strip().lower()
    if normalized == "initial_submission":
        return 0
    match = ROUND_PATTERN.fullmatch(normalized)
    if match is not None:
        return int(match.group(1))
    directory = REVISION_DIRECTORY_PATTERN.fullmatch(normalized)
    if directory is not None:
        return int(directory.group(1))
    raise WorkflowError(
        f"Invalid round {value!r}; use r00, r01, initial_submission, or revision_01."
    )


def _observed_revisions(project: Path) -> tuple[int, ...]:
    numbers = []
    if not project.exists():
        return ()
    for path in project.iterdir():
        if not path.is_dir():
            continue
        match = REVISION_DIRECTORY_PATTERN.fullmatch(path.name)
        if match is not None:
            numbers.append(int(match.group(1)))
    return tuple(sorted(numbers))


def _round_numbers(project: Path) -> tuple[int, ...]:
    if not (project / "initial_submission" / "meta.yaml").is_file():
        raise WorkflowError(f"Manuscript workspace is not initialized: {project}")
    required = (
        project / "00_archive",
        project / "references" / "authors.yaml",
        project / "references" / "references.bib",
        project / "references" / "revision_style.tex",
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        raise WorkflowError(
            "Manuscript workspace is incomplete: "
            + ", ".join(path.name for path in missing)
        )
    revisions = _observed_revisions(project)
    expected = tuple(range(1, len(revisions) + 1))
    if revisions != expected:
        raise WorkflowError(
            f"Revision directories require reindex; observed {revisions}, "
            f"expected {expected}."
        )
    return (0, *revisions)


def is_initialized(path: str | Path) -> bool:
    """Return whether a project contains the canonical manuscript workspace."""
    project = normalize_project(path)
    return (project / "initial_submission" / "meta.yaml").is_file()


def load_project(
    path: str | Path,
    round_number: int | None = None,
) -> ProjectConfig:
    """Load one version and validate the complete adjacent chain."""
    project = normalize_project(path)
    numbers = _round_numbers(project)
    selected = numbers[-1] if round_number is None else round_number
    if selected not in numbers:
        raise WorkflowError(f"Round {round_name(selected)} does not exist.")
    for number in numbers:
        version = project / revision_directory_name(number)
        if (version / "references").exists():
            raise WorkflowError(f"Version-local references are forbidden: {version}")
        metadata = load_meta(version / "meta.yaml")
        if metadata.round_number != number:
            raise WorkflowError(
                f"{version / 'meta.yaml'} declares {round_name(metadata.round_number)}, "
                f"expected {round_name(number)}."
            )
    return ProjectConfig(
        project,
        load_meta(project / revision_directory_name(selected) / "meta.yaml"),
    )


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
    """Return non-author replacements for editable correspondence sources."""
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
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read template: {source}") from exc
    for key, value in values.items():
        text = text.replace(f"%%{key}%%", value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def publisher_resource(config: ProjectConfig) -> Path:
    """Resolve a built-in package resource or one explicit custom template."""
    if config.metadata.publisher == "custom":
        custom = config.references / "journal_template"
        if not custom.is_dir():
            raise WorkflowError(f"Custom journal template is missing: {custom}")
        return custom
    resource = resources_root() / "journal_templates" / config.metadata.publisher
    if not resource.is_dir():
        raise WorkflowError(f"Publisher package resource is missing: {resource}")
    return resource


def _publisher_layout(
    config: ProjectConfig,
) -> tuple[dict[str, str] | None, list[dict[str, str]], str, str]:
    path = publisher_resource(config) / "sections.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkflowError(f"Cannot load publisher section mapping: {path}") from exc
    sections = data.get("sections") if isinstance(data, dict) else None
    bibliography = data.get("bibliography") if isinstance(data, dict) else None
    frontmatter = data.get("frontmatter") if isinstance(data, dict) else None
    if (
        not isinstance(sections, list)
        or not sections
        or not isinstance(bibliography, dict)
    ):
        raise WorkflowError(f"Invalid publisher section mapping: {path}")
    package = str(bibliography.get("package", "")).strip()
    style = str(bibliography.get("style", "")).strip()
    if not package or not style:
        raise WorkflowError(f"Publisher bibliography mapping is incomplete: {path}")
    frontmatter_plan: dict[str, str] | None = None
    if frontmatter is not None:
        if (
            not isinstance(frontmatter, dict)
            or "file" not in frontmatter
            or "source" not in frontmatter
        ):
            raise WorkflowError(f"Invalid publisher frontmatter mapping: {path}")
        frontmatter_plan = {
            "file": str(frontmatter["file"]),
            "source": str(frontmatter["source"]),
            "title": "",
        }
    plan: list[dict[str, str]] = []
    for index, item in enumerate(sections, 1):
        if not isinstance(item, dict) or "file" not in item or "source" not in item:
            raise WorkflowError(f"Invalid section mapping item {index}: {path}")
        plan.append(
            {
                "file": str(item["file"]),
                "source": str(item["source"]),
                "title": str(item.get("title", "")),
            }
        )
    return frontmatter_plan, plan, package, style


def _create_manuscript_sources(config: ProjectConfig, version: Path) -> None:
    frontmatter, plan, _, style = _publisher_layout(config)
    abstract_input = ""
    body_plan = plan
    if frontmatter is None:
        abstract = plan[0]
        abstract_input = f"\\input{{sections/{Path(abstract['file']).stem}}}"
        body_plan = plan[1:]
    section_inputs = "\n".join(
        f"\\input{{sections/{Path(item['file']).stem}}}" for item in body_plan
    )
    frontmatter_input = (
        f"\\input{{sections/{Path(frontmatter['file']).stem}}}"
        if frontmatter is not None
        else ""
    )
    render_template(
        publisher_resource(config) / "workflow.tex",
        version / "manuscript.tex",
        {
            "ABSTRACT_INPUT": abstract_input,
            "FRONTMATTER_INPUT": frontmatter_input,
            "SECTION_INPUTS": section_inputs,
            "BIBLIOGRAPHY_STYLE": style,
            "BIBLIOGRAPHY_PATH": "references",
        },
    )
    defaults = resources_root() / "manuscript" / "sections" / "default"
    source_plan = ([frontmatter] if frontmatter is not None else []) + plan
    for item in source_plan:
        render_template(
            defaults / item["source"],
            version / "sections" / item["file"],
            {"SECTION_TITLE": item["title"]},
        )


def initialize_project(
    config: ProjectConfig,
    authors_source: Path,
    bibliography_source: Path | None = None,
    custom_template: Path | None = None,
) -> ProjectConfig:
    """Create ``project/manuscript`` without requiring an empty parent project."""
    root = config.project
    if root.exists():
        raise WorkflowError(f"Refusing to overwrite existing manuscript/: {root}")
    if config.current_round != 0 or config.metadata.parent_round is not None:
        raise WorkflowError("Initialization metadata must describe r00 with no parent.")
    root.mkdir(parents=True)
    initial = config.round_dir(0)
    for directory in (
        root / "00_archive",
        config.references,
        initial / "sections",
        initial / "figures",
        initial / "tables",
        initial / "output",
        initial / "submission",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    bibliography = (
        bibliography_source or resources_root() / "manuscript" / "references.bib"
    )
    if not authors_source.is_file():
        raise WorkflowError(f"Author library is missing: {authors_source}")
    if not bibliography.is_file():
        raise WorkflowError(f"Bibliography is missing: {bibliography}")
    shutil.copy2(authors_source, config.references / "authors.yaml")
    shutil.copy2(bibliography, config.references / "references.bib")
    shutil.copy2(
        resources_root() / "revision_style.tex",
        config.references / "revision_style.tex",
    )
    if config.metadata.publisher == "custom":
        if custom_template is None or not custom_template.is_dir():
            raise WorkflowError(
                "publisher=custom requires --custom-template directory."
            )
        shutil.copytree(custom_template, config.references / "journal_template")
    elif custom_template is not None:
        raise WorkflowError("--custom-template requires publisher=custom.")
    _create_manuscript_sources(config, initial)
    save_meta(initial / "meta.yaml", config.metadata)
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
    raise ValueError("Unbalanced provenance command braces.")


def strip_provenance_wrappers(text: str) -> str:
    """Make inherited review/user wrappers transparent in a child revision."""
    output = text
    changed = True
    while changed:
        changed = False
        for command, fields in ((r"\review", 2), (r"\user", 1), (r"\selfadd", 1)):
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
                    values: list[str] = []
                    for _ in range(fields):
                        value, end = _extract_braced(output, end)
                        values.append(value)
                except ValueError:
                    pieces.append(output[cursor:end])
                    cursor = end
                    continue
                pieces.extend((output[cursor:start], values[-1]))
                cursor = end
                changed = True
            output = "".join(pieces)
    return output


def _digest_entries(version: Path, *, scientific_only: bool) -> list[Path]:
    paths = [version / "manuscript.tex"]
    if not scientific_only:
        paths.append(version / "meta.yaml")
    directories = SCIENTIFIC_DIRECTORIES if scientific_only else PROTECTED_DIRECTORIES
    for directory in directories:
        root = version / directory
        if root.exists():
            paths.extend(path for path in sorted(root.rglob("*")) if path.is_file())
    return [path for path in paths if path.is_file()]


def source_digest(version: Path, *, scientific_only: bool = False) -> str:
    """Hash source names and bytes in deterministic order."""
    digest = hashlib.sha256()
    for path in _digest_entries(version, scientific_only=scientific_only):
        digest.update(path.relative_to(version).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def start_revision(
    config: ProjectConfig,
    target_round: int,
    staging_root: Path,
    reviews: Path | None = None,
) -> ProjectConfig:
    """Create exactly the next revision without outputs or inherited response."""
    latest = load_project(config.project)
    expected = latest.current_round + 1
    if config.current_round != latest.current_round or target_round != expected:
        raise WorkflowError(
            f"The only valid next revision is {round_name(expected)} from "
            f"{round_name(latest.current_round)}."
        )
    source = config.round_dir(config.current_round)
    target = config.round_dir(target_round)
    if target.exists():
        raise WorkflowError(f"Revision already exists: {target}")
    staged = staging_root / revision_directory_name(target_round)
    staged.mkdir(parents=True)
    source_manuscript = source / "manuscript.tex"
    if not source_manuscript.is_file():
        raise WorkflowError(f"Parent manuscript source is missing: {source_manuscript}")
    shutil.copy2(source_manuscript, staged / "manuscript.tex")
    for directory in SCIENTIFIC_DIRECTORIES:
        source_dir = source / directory
        if source_dir.exists():
            shutil.copytree(source_dir, staged / directory)
        else:
            (staged / directory).mkdir()
    for tex_file in [
        staged / "manuscript.tex",
        *sorted((staged / "sections").rglob("*.tex")),
    ]:
        tex_file.write_text(
            strip_provenance_wrappers(tex_file.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
    for directory in ("response", "output", "submission"):
        (staged / directory).mkdir()
    comments = staged / "response" / "reviewer_comments.md"
    if reviews is None:
        comments.write_text(
            "# Reviewer #1\n\n## 1-1 | manuscript_revised\n\nFirst specific comment.\n",
            encoding="utf-8",
        )
    else:
        shutil.copy2(reviews, comments)
    child = with_revision(config.metadata, target_round)
    save_meta(staged / "meta.yaml", child)
    os.replace(staged, target)
    return ProjectConfig(config.project, child, config.engine)


def finalize_revision_creation(config: ProjectConfig) -> Path:
    """Record the protected post-creation source digest."""
    version = config.round_dir(config.current_round)
    path = version / "revision_creation.yaml"
    data = {
        "round": round_name(config.current_round),
        "parent": round_name(config.current_round - 1),
        "created_from": revision_directory_name(config.current_round - 1),
        "protected_source_digest": source_digest(version),
    }
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


def _load_creation(version: Path) -> dict[str, str]:
    path = version / "revision_creation.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkflowError(f"Invalid revision creation record: {path}") from exc
    if not isinstance(data, dict) or not isinstance(
        data.get("protected_source_digest"), str
    ):
        raise WorkflowError(f"Invalid revision creation record: {path}")
    return {str(key): str(value) for key, value in data.items()}


def _archive_directory(project: Path, operation: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = project / "00_archive" / f"{operation}_{stamp}_{uuid.uuid4().hex[:6]}"
    target.mkdir(parents=True)
    return target


def rollback_revision(config: ProjectConfig) -> tuple[Path, int]:
    """Archive the untouched latest revision and return the new latest round."""
    latest = load_project(config.project)
    if latest.current_round == 0:
        raise WorkflowError("initial_submission cannot be rolled back.")
    version = latest.round_dir(latest.current_round)
    record = _load_creation(version)
    if source_digest(version) != record["protected_source_digest"]:
        raise WorkflowError(
            "Rollback refused: protected user or scientific source has changed."
        )
    archive = _archive_directory(latest.project, "rollback")
    archived = archive / version.name
    try:
        os.replace(version, archived)
        load_project(latest.project)
    except Exception:
        if archived.exists() and not version.exists():
            os.replace(archived, version)
        raise
    return archived, latest.current_round - 1


def _clear_generated(version: Path) -> None:
    for name in ("output", "submission"):
        target = version / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()


def reindex_revisions(
    project: Path,
    run_dir: Path,
    *,
    fail_after_swap: bool = False,
) -> tuple[tuple[str, str], ...]:
    """Transactionally close revision gaps while preserving scientific bytes."""
    root = normalize_project(project)
    revisions = _observed_revisions(root)
    if not revisions:
        return ()
    mapping = tuple(
        (f"revision_{old:02d}", f"revision_{new:02d}")
        for new, old in enumerate(revisions, 1)
        if old != new
    )
    if not mapping:
        return ()
    archive = _archive_directory(root, "reindex")
    for number in revisions:
        source = root / f"revision_{number:02d}"
        shutil.copytree(source, archive / source.name)
    stage = run_dir / "reindex_stage"
    originals = run_dir / "reindex_originals"
    stage.mkdir()
    originals.mkdir()
    scientific_before: dict[int, str] = {}
    for new_number, old_number in enumerate(revisions, 1):
        source = root / f"revision_{old_number:02d}"
        scientific_before[new_number] = source_digest(source, scientific_only=True)
        target = stage / f"revision_{new_number:02d}"
        shutil.copytree(source, target)
        metadata = load_meta(target / "meta.yaml")
        save_meta(target / "meta.yaml", with_revision(metadata, new_number))
        _clear_generated(target)
        creation = target / "revision_creation.yaml"
        if creation.exists():
            creation.unlink()
        data = {
            "round": round_name(new_number),
            "parent": round_name(new_number - 1),
            "created_from": revision_directory_name(new_number - 1),
            "protected_source_digest": source_digest(target),
        }
        (target / "revision_creation.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        if source_digest(target, scientific_only=True) != scientific_before[new_number]:
            raise WorkflowError("Reindex staging changed scientific source bytes.")
    moved: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for number in revisions:
            source = root / f"revision_{number:02d}"
            backup = originals / source.name
            os.replace(source, backup)
            moved.append((backup, source))
        if fail_after_swap:
            raise WorkflowError("Injected reindex failure after source swap.")
        for path in sorted(stage.iterdir()):
            target = root / path.name
            os.replace(path, target)
            installed.append(target)
        load_project(root)
    except Exception:
        for target in installed:
            if target.exists():
                shutil.rmtree(target)
        for backup, source in reversed(moved):
            if backup.exists():
                os.replace(backup, source)
        raise
    return mapping


def ensure_submission_workspace(config: ProjectConfig, round_number: int) -> Path:
    """Create editable submission sources once within one version."""
    if round_number != config.current_round:
        raise WorkflowError("Submission config must match the selected version.")
    target = config.round_dir(round_number) / "submission"
    target.mkdir(parents=True, exist_ok=True)
    values = template_values(config)
    values["AUTHOR_METADATA_PATH"] = "author_metadata.tex"
    settings = config.metadata.submission
    resources = resources_root() / "submission"
    if settings.cover_letter and not (target / "cover_letter_body.tex").exists():
        render_template(
            resources / f"cover_letter_body_{config.language}.tex",
            target / "cover_letter_body.tex",
            values,
        )
    if settings.highlights and not (target / "highlights.tex").exists():
        render_template(
            resources / "highlights.tex",
            target / "highlights.tex",
            values,
        )
    checklist = target / "checklist.md"
    if not checklist.exists():
        shutil.copy2(resources / "checklist.md", checklist)
    if settings.graphical_abstract:
        graphical = target / "graphical_abstract"
        graphical.mkdir(exist_ok=True)
        source = graphical / "graphical_abstract.tex"
        if not source.exists():
            shutil.copy2(
                resources / "graphical_abstract" / "graphical_abstract.tex",
                source,
            )
    return target


def _find_bib_export(project: Path, explicit: Path | None) -> Path:
    candidates = []
    if explicit is not None:
        candidates.append(explicit.expanduser().resolve())
    environment = os.environ.get("ZOTERO_BETTER_BIBTEX_EXPORT")
    if environment:
        candidates.append(Path(environment).expanduser().resolve())
    candidates.extend(
        [
            project / "references" / "zotero-export.bib",
            project.parent / "zotero-export.bib",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise WorkflowError("No Better BibTeX export found; use --bib-export PATH.")


def sync_bibliography(project: Path, explicit: Path | None = None) -> Path:
    """Atomically replace the single manuscript-level BibTeX database."""
    root = normalize_project(project)
    _round_numbers(root)
    source = _find_bib_export(root, explicit)
    text = source.read_text(encoding="utf-8")
    if "@" not in text or "{" not in text:
        raise WorkflowError(f"Bibliography does not contain BibTeX entries: {source}")
    target = root / "references" / "references.bib"
    temporary = target.with_suffix(".bib.new")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return target


@contextlib.contextmanager
def temporary_run(project: Path, keep: bool = False) -> Iterator[Path]:
    """Create tmp lazily, remove it after success, retain diagnostics on failure."""
    root = normalize_project(project) / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = root / f"run_{stamp}_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    run_dir.mkdir()
    try:
        yield run_dir
    except Exception:
        raise
    else:
        if not keep:
            shutil.rmtree(run_dir)
            if root.exists() and not any(root.iterdir()):
                root.rmdir()
