"""Workspace structure, revision transactions, bibliography, and temporary runs."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml

from .bibliography import (
    citation_only_bibliography,
    resolved_citation_keys,
    source_citation_keys,
)
from .errors import WorkflowError
from .metadata import (
    ManuscriptMetadata,
    load_meta,
    revision_directory_name,
    round_name,
    save_meta,
    validate_publisher_language,
    with_revision,
    write_meta_template,
)
from .provenance import extract_provenance
from .templates import initialize_manuscript_sources, install_reference_resources
from .templates import resources_root as resources_root

REVISION_DIRECTORY_PATTERN = re.compile(r"^revision_(\d{2,})$")
ROUND_PATTERN = re.compile(r"^r(\d{2,})$")
PROTECTED_DIRECTORIES = ("sections", "figures", "tables", "response", "preamble")
SCIENTIFIC_DIRECTORIES = ("sections", "figures", "tables")
INHERITED_DIRECTORIES = SCIENTIFIC_DIRECTORIES
GENERATED_SUBMISSION_PATHS = (
    Path("manuscript.pdf"),
    Path("marked_manuscript.pdf"),
    Path("response_letter.pdf"),
    Path("cover_letter.pdf"),
    Path("highlights.pdf"),
)
REVIEW_COMPLETENESS_LINE = re.compile(
    rb"(?m)^- Review completeness: \*\*(?:COMPLETE|INCOMPLETE)\*\*\.\r?\n?"
)
LEGACY_REVISION_COLORS = {
    "RevisionAddedColor": r"\definecolor{RevisionAddedColor}{RGB}{0,92,153}",
    "RevisionReviewColor": r"\definecolor{RevisionReviewColor}{RGB}{220,45,45}",
}
LEGACY_DELETION_COMMANDS = (
    "RevisionDeletedColor",
    "RevisionDeletionThickness",
    "RevisionDeletedStrikeout",
    "RevisionDeletedBackground",
    "RevisionDeletedFont",
)


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

    def output_dir(self, round_number: int) -> Path:
        """Return the user-facing PDF directory for one round."""
        return self.round_dir(round_number) / "output"

    def response_dir(self, round_number: int) -> Path:
        """Return the editable reviewer-response directory for one round."""
        return self.round_dir(round_number) / "response"

    def submission_dir(self, round_number: int) -> Path:
        """Return the editable submission workspace for one round."""
        return self.round_dir(round_number) / "submission"

    def state_dir(self, round_number: int) -> Path:
        """Return the persistent machine-state directory for one round."""
        return self.project / "state" / revision_directory_name(round_number)

    def review_index_path(self, round_number: int) -> Path:
        """Return the canonical review-index state path."""
        return self.state_dir(round_number) / "review_index.yaml"

    def creation_record_path(self, round_number: int) -> Path:
        """Return the canonical rollback-protection record path."""
        return self.state_dir(round_number) / "creation.yaml"

    def generated_artifacts_path(self, round_number: int) -> Path:
        """Return the ownership record for generated submission artifacts."""
        return self.state_dir(round_number) / "generated_artifacts.yaml"

    def build_manifest_path(self, round_number: int) -> Path:
        """Return the reproducibility manifest for one round."""
        return self.state_dir(round_number) / "build_manifest.yaml"

    def round_state_path(self, round_number: int) -> Path:
        """Return the immutable scientific-state record for one round."""
        return self.state_dir(round_number) / "round_state.yaml"

    def author_snapshot_path(self, round_number: int) -> Path:
        """Return the frozen effective author library for one round."""
        return self.state_dir(round_number) / "authors.yaml"

    def bibliography_snapshot_path(self, round_number: int) -> Path:
        """Return the machine-owned bibliography snapshot for one round."""
        return self.state_dir(round_number) / "bibliography.bib"

    def tmp_root(self) -> Path:
        """Return the lazy reproducible run-diagnostics root."""
        return self.project / "tmp"

    def archive_root(self) -> Path:
        """Return the manuscript-lifecycle transaction archive."""
        return self.project / "00_archive"


def _remove_tex_command_lines(text: str, command_name: str) -> str:
    """Remove one obsolete top-level command definition without parsing TeX."""
    start_pattern = re.compile(
        rf"(?m)^[ \t]*\\(?:definecolor|newcommand|renewcommand|providecommand)"
        rf"\{{\\?{re.escape(command_name)}\}}"
    )
    while (match := start_pattern.search(text)) is not None:
        cursor = match.start()
        brace_depth = 0
        saw_brace = False
        end = match.end()
        while end < len(text):
            character = text[end]
            escaped = end > 0 and text[end - 1] == "\\"
            if not escaped and character == "{":
                brace_depth += 1
                saw_brace = True
            elif not escaped and character == "}":
                brace_depth -= 1
            end += 1
            if character == "\n" and saw_brace and brace_depth <= 0:
                break
        text = text[:cursor] + text[end:]
    return text


def migrate_revision_style_file(style: Path, archive_root: Path) -> Path | None:
    """Migrate known legacy semantic colors while preserving unrelated edits."""
    try:
        original = style.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read revision style: {style}") from exc
    legacy_tokens = (*LEGACY_REVISION_COLORS, *LEGACY_DELETION_COMMANDS)
    if not any(token in original for token in legacy_tokens):
        return None

    migrated = original
    for name, stock_definition in LEGACY_REVISION_COLORS.items():
        if name not in migrated:
            continue
        if migrated.count(stock_definition) != 1:
            raise WorkflowError(
                "REVISION_STYLE_MIGRATION_UNSUPPORTED: "
                f"{name} is customized in {style}. Remove the legacy semantic "
                "color override or migrate it manually to the package-owned "
                "RubineRed/ForestGreen/xcolor ProcessBlue contract."
            )
        migrated = migrated.replace(stock_definition, "", 1)
    for name in LEGACY_DELETION_COMMANDS:
        migrated = _remove_tex_command_lines(migrated, name)

    migrated = (
        migrated.replace(
            "%   ordinary latexdiff addition = blue text",
            "%   ordinary author addition    = ForestGreen",
        )
        .replace(
            "%   reviewer-linked addition    = red text",
            "%   reviewer-linked addition    = RubineRed",
        )
        .replace(
            "%   author ordinary addition    = blue text",
            "%   author ordinary addition    = ForestGreen",
        )
    )
    migrated = (
        migrated.replace("%   deletion                    = light-gray strikeout\n", "")
        .replace("% Deleted text\n", "")
        .replace("% Deleted text color.\n", "")
    )
    if any(token in migrated for token in legacy_tokens):
        remaining = ", ".join(token for token in legacy_tokens if token in migrated)
        raise WorkflowError(
            "REVISION_STYLE_MIGRATION_UNSUPPORTED: legacy semantic commands are "
            f"still consumed by project customizations in {style}: {remaining}."
        )
    required_hooks = (
        r"\RevisionAddedBackground",
        r"\RevisionReviewBackground",
        r"\RevisionAddedFont",
        r"\RevisionReviewFont",
    )
    missing = [hook for hook in required_hooks if hook not in migrated]
    if missing:
        raise WorkflowError(
            "REVISION_STYLE_MIGRATION_UNSUPPORTED: required presentation hooks "
            f"are missing from {style}: {', '.join(missing)}."
        )

    source_digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
    archive = (
        archive_root / f"resource_migration_{source_digest}" / "references" / style.name
    )
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.is_file():
        if archive.read_text(encoding="utf-8") != original:
            raise WorkflowError(
                "REVISION_STYLE_MIGRATION_ARCHIVE_CONFLICT: deterministic archive "
                f"does not match the source resource: {archive}"
            )
    else:
        shutil.copy2(style, archive)
    temporary = style.with_suffix(style.suffix + ".new")
    try:
        temporary.write_text(migrated, encoding="utf-8")
        os.replace(temporary, style)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return archive


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


def _validate_no_symlinks(version: Path) -> None:
    """Reject links that could make managed reads or copies escape the workspace."""
    roots = (
        version / "manuscript.tex",
        version / "meta.yaml",
        *(version / name for name in (*PROTECTED_DIRECTORIES, "submission")),
    )
    for root in roots:
        if root.is_symlink():
            raise WorkflowError(
                f"Symbolic links are forbidden in managed manuscript sources: {root}"
            )
        candidates = root.rglob("*") if root.is_dir() else ()
        for path in candidates:
            if path.is_symlink():
                raise WorkflowError(
                    f"Symbolic links are forbidden in managed manuscript sources: {path}"
                )


def _detect_v1_workspace(version: Path) -> None:
    legacy = (
        version / "response" / "response_letter.tex",
        version / "submission" / "package",
        version / "revision_creation.yaml",
    )
    detected = [path for path in legacy if path.exists()]
    if detected:
        names = ", ".join(path.relative_to(version).as_posix() for path in detected)
        raise WorkflowError(
            "Detected a v1 workspace while running 2.0: "
            f"{names}. Archive the workspace before migration and read the "
            "CHANGELOG and workflow migration section."
        )


def load_project(
    path: str | Path,
    round_number: int | None = None,
) -> ProjectConfig:
    """Load one version and validate the complete adjacent chain."""
    project = normalize_project(path)
    numbers = _round_numbers(project)
    selected = numbers[-1] if round_number is None else round_number
    if selected not in numbers:
        available = "\n".join(
            f"- {revision_directory_name(number)}" for number in numbers
        )
        raise WorkflowError(
            f'Round "{revision_directory_name(selected)}" does not exist.\n'
            f"Available rounds:\n{available}"
        )
    for number in numbers:
        version = project / revision_directory_name(number)
        _validate_no_symlinks(version)
        _detect_v1_workspace(version)
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


def initialize_project(
    config: ProjectConfig,
    bibliography_source: Path | None = None,
    custom_template: Path | None = None,
) -> ProjectConfig:
    """Create ``project/manuscript`` without requiring an empty parent project."""
    root = config.project
    if root.exists():
        raise WorkflowError(f"Refusing to overwrite existing manuscript/: {root}")
    if config.current_round != 0 or config.metadata.parent_round is not None:
        raise WorkflowError("Initialization metadata must describe r00 with no parent.")
    validate_publisher_language(config.metadata.publisher, config.metadata.language)
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
    if not bibliography.is_file():
        raise WorkflowError(f"Bibliography is missing: {bibliography}")
    install_reference_resources(
        config,
        bibliography,
    )
    if config.metadata.publisher == "custom":
        if custom_template is None or not custom_template.is_dir():
            raise WorkflowError("publisher='custom' requires --custom-template PATH.")
        shutil.copytree(custom_template, config.references / "journal_template")
    elif custom_template is not None:
        raise WorkflowError("--custom-template is valid only for publisher='custom'.")
    initialize_manuscript_sources(config, initial)
    save_meta(initial / "meta.yaml", config.metadata)
    return config


def initialize_draft_project(path: str | Path) -> Path:
    """Create a metadata-first workspace without selecting manuscript content."""
    root = normalize_project(path, initialize=True)
    if root.exists():
        raise WorkflowError(f"Refusing to overwrite existing manuscript/: {root}")
    initial = root / "initial_submission"
    references = root / "references"
    for directory in (
        root / "00_archive",
        references,
        initial / "sections",
        initial / "figures",
        initial / "tables",
        initial / "output",
        initial / "submission",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        resources_root() / "manuscript" / "references.bib",
        references / "references.bib",
    )
    shutil.copy2(
        resources_root() / "revision_style.template.tex",
        references / "revision_style.tex",
    )
    metadata_path = initial / "meta.yaml"
    write_meta_template(metadata_path)
    return metadata_path


def strip_provenance_wrappers(text: str) -> str:
    """Make inherited reviewer provenance transparent in a child revision."""
    return extract_provenance(text).text


def _generated_submission_paths(version: Path) -> set[Path]:
    registry = version.parent / "state" / version.name / "generated_artifacts.yaml"
    if not registry.is_file():
        return set()
    try:
        data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkflowError(f"Invalid generated artifact registry: {registry}") from exc
    values = data.get("paths") if isinstance(data, dict) else None
    hashes = data.get("sha256") if isinstance(data, dict) else None
    if not isinstance(values, list) or not isinstance(hashes, dict):
        raise WorkflowError(f"Invalid generated artifact registry: {registry}")
    generated: set[Path] = set()
    submission = version / "submission"
    for value in values:
        if not isinstance(value, str):
            raise WorkflowError(f"Invalid generated artifact registry: {registry}")
        relative = Path(value)
        expected = hashes.get(relative.as_posix())
        target = submission / relative
        if (
            relative.is_absolute()
            or not relative.parts
            or relative == Path(".")
            or ".." in relative.parts
            or not isinstance(expected, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected) is None
        ):
            raise WorkflowError(f"Invalid generated artifact registry: {registry}")
        if (
            not target.is_file()
            or hashlib.sha256(target.read_bytes()).hexdigest() == expected
        ):
            generated.add(relative)
    return generated


def _submission_source_entries(version: Path) -> list[Path]:
    submission = version / "submission"
    if not submission.is_dir():
        return []
    generated = set(GENERATED_SUBMISSION_PATHS) | _generated_submission_paths(version)
    return [
        path
        for path in sorted(submission.rglob("*"))
        if path.is_file() and path.relative_to(submission) not in generated
    ]


def _digest_entries(version: Path, *, scientific_only: bool) -> list[Path]:
    paths = [version / "manuscript.tex"]
    if not scientific_only:
        paths.append(version / "meta.yaml")
    directories = SCIENTIFIC_DIRECTORIES if scientific_only else PROTECTED_DIRECTORIES
    for directory in directories:
        root = version / directory
        if root.exists():
            paths.extend(path for path in sorted(root.rglob("*")) if path.is_file())
    if not scientific_only:
        paths.extend(_submission_source_entries(version))
    return [path for path in paths if path.is_file()]


def source_digest(version: Path, *, scientific_only: bool = False) -> str:
    """Hash source names and bytes in deterministic order."""
    digest = hashlib.sha256()
    for path in _digest_entries(version, scientific_only=scientific_only):
        digest.update(path.relative_to(version).as_posix().encode("utf-8"))
        digest.update(b"\0")
        content = path.read_bytes()
        if path.name == "checklist.md" and path.parent.name == "submission":
            content = REVIEW_COMPLETENESS_LINE.sub(b"", content)
            content = re.sub(rb"\n{2,}\Z", b"\n", content)
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _path_digest(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    paths = sorted(item for item in path.rglob("*") if item.is_file())
    for item in paths:
        digest.update(item.relative_to(path.parent).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_file_atomically(source: Path, target: Path) -> Path:
    """Copy one file through a sibling temporary and atomically replace it."""
    if not source.is_file():
        raise WorkflowError(f"Source file is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.new")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return target


def snapshot_bibliography(
    config: ProjectConfig,
    round_number: int,
    aux_path: Path | None = None,
    *,
    rebuild_historical: bool = False,
) -> Path:
    """Write one citation-only round snapshot from resolved build evidence.

    Existing snapshots are immutable unless the latest round is refreshed from
    a successful build, or an explicit historical migration requests a rebuild.
    """
    source = config.references / "references.bib"
    if not source.is_file():
        raise WorkflowError(f"Bibliography is missing: {source}")
    target = config.bibliography_snapshot_path(round_number)
    rounds = _round_numbers(config.project)
    latest = rounds[-1]
    if (
        target.is_file()
        and aux_path is None
        and not rebuild_historical
        and round_number != latest
    ):
        return target
    if round_number != latest and not rebuild_historical:
        if target.is_file():
            return target
        raise WorkflowError(
            f"Historical bibliography snapshot is frozen for {round_name(round_number)}."
        )
    if aux_path is not None:
        citation_keys = resolved_citation_keys(aux_path)
    else:
        version = config.round_dir(round_number)
        citation_keys = source_citation_keys(
            tuple(
                path
                for path in (
                    version / "manuscript.tex",
                    *sorted((version / "sections").rglob("*.tex")),
                )
                if path.is_file()
            )
        )
    bibliography_text = (
        target.read_text(encoding="utf-8")
        if rebuild_historical and target.is_file()
        else source.read_text(encoding="utf-8")
    )
    filtered = citation_only_bibliography(
        bibliography_text,
        citation_keys,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".bib.new")
    try:
        temporary.write_text(filtered, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return target


def bibliography_source_for_round(
    config: ProjectConfig,
    round_number: int,
) -> Path:
    """Resolve live bibliography for the latest round and snapshots for history."""
    rounds = _round_numbers(config.project)
    if round_number not in rounds:
        raise WorkflowError(f"Unknown bibliography round: {round_name(round_number)}")
    if round_number == rounds[-1]:
        return config.references / "references.bib"
    snapshot = config.bibliography_snapshot_path(round_number)
    if not snapshot.is_file():
        raise WorkflowError(
            "Historical bibliography snapshot is missing for "
            f"{round_name(round_number)}; its visible reference state cannot be "
            "reconstructed from the shared latest references.bib."
        )
    return snapshot


def author_library_source_for_round(
    config: ProjectConfig,
    round_number: int,
) -> Path:
    """Use live author metadata for the active round and its snapshot for history."""
    from .authors import resolve_author_library_path

    rounds = _round_numbers(config.project)
    if round_number == rounds[-1]:
        return resolve_author_library_path()
    snapshot = config.author_snapshot_path(round_number)
    if not snapshot.is_file():
        raise WorkflowError(
            "HISTORICAL_ROUND_STATE_UNAVAILABLE: effective author snapshot is "
            f"missing for {round_name(round_number)}: {snapshot}"
        )
    return snapshot


def _effective_author_snapshot_data(
    config: ProjectConfig,
    round_number: int,
    source: Path,
) -> dict[str, object]:
    """Return only author and affiliation records consumed by one round."""
    from .authors import load_author_library, resolve_authors

    metadata = load_meta(config.round_dir(round_number) / "meta.yaml")
    selection = resolve_authors(metadata, load_author_library(source))
    affiliations: dict[str, dict[str, str]] = {}
    for affiliation in selection.affiliations:
        affiliations[affiliation.affiliation_id] = {
            "name_en": affiliation.name_en,
            "name_zh": affiliation.name_zh,
            "address": affiliation.address,
        }
    authors: dict[str, dict[str, object]] = {}
    for author in selection.authors:
        authors[author.author_id] = {
            "name_en": author.name_en,
            "name_zh": author.name_zh,
            "email": author.email,
            "affiliations": list(author.affiliations),
            "bio_en": author.bio_en,
            "bio_zh": author.bio_zh,
            "correspondence_address": author.correspondence_address,
        }
    return {"affiliations": affiliations, "authors": authors}


def _yaml_bytes(values: dict[str, object]) -> bytes:
    return yaml.safe_dump(
        values,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")


def _write_bytes_atomically(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return path


def _snapshot_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _round_state_values(
    config: ProjectConfig,
    round_number: int,
    *,
    author_snapshot_sha256: str | None = None,
) -> dict[str, object]:
    """Return the ancestry-bound identity that becomes immutable for history."""

    version = config.round_dir(round_number)
    metadata = load_meta(version / "meta.yaml")
    bibliography = config.bibliography_snapshot_path(round_number)
    if not bibliography.is_file():
        raise WorkflowError(
            "HISTORICAL_ROUND_STATE_UNAVAILABLE: bibliography snapshot is missing "
            f"for {round_name(round_number)}: {bibliography}"
        )
    author_snapshot = config.author_snapshot_path(round_number)
    if author_snapshot_sha256 is None:
        if not author_snapshot.is_file():
            raise WorkflowError(
                "HISTORICAL_ROUND_STATE_UNAVAILABLE: effective author snapshot is "
                f"missing for {round_name(round_number)}: {author_snapshot}"
            )
        author_snapshot_sha256 = _path_digest(author_snapshot)
    parent_state_sha256: str | None = None
    if metadata.parent_round is not None:
        parent_state = config.round_state_path(metadata.parent_round)
        if not parent_state.is_file():
            raise WorkflowError(
                "HISTORICAL_ROUND_STATE_UNAVAILABLE: parent round state is missing "
                f"for {round_name(round_number)}: {parent_state}"
            )
        parent_state_sha256 = _path_digest(parent_state)
    return {
        "schema": "sci-manuscript-round-state/v2",
        "round": round_name(round_number),
        "parent": (
            None if metadata.parent_round is None else round_name(metadata.parent_round)
        ),
        "parent_round_state_sha256": parent_state_sha256,
        "scientific_source_sha256": source_digest(version, scientific_only=True),
        "metadata_sha256": _path_digest(version / "meta.yaml"),
        "bibliography_snapshot_sha256": _path_digest(bibliography),
        "effective_authors_snapshot_sha256": author_snapshot_sha256,
    }


def _write_round_state(path: Path, values: dict[str, object]) -> Path:
    return _write_bytes_atomically(path, _yaml_bytes(values))


def _validated_snapshot_bytes(config: ProjectConfig, round_number: int) -> bytes:
    """Return an existing valid snapshot or derive one from the current library."""
    from .authors import (
        load_author_library,
        resolve_author_library_path,
        resolve_authors,
    )

    snapshot = config.author_snapshot_path(round_number)
    metadata = load_meta(config.round_dir(round_number) / "meta.yaml")
    if snapshot.is_file():
        resolve_authors(metadata, load_author_library(snapshot))
        return snapshot.read_bytes()
    return _yaml_bytes(
        _effective_author_snapshot_data(
            config,
            round_number,
            resolve_author_library_path(),
        )
    )


def freeze_round_state(config: ProjectConfig, round_number: int) -> Path:
    """Create one immutable scientific-state record without replacing it."""
    target = config.round_state_path(round_number)
    if target.is_file():
        return _ensure_one_historical_round_state(config, round_number)
    metadata = load_meta(config.round_dir(round_number) / "meta.yaml")
    if metadata.parent_round is not None:
        ensure_historical_round_state(config, metadata.parent_round)
    snapshot = config.author_snapshot_path(round_number)
    snapshot_existed = snapshot.is_file()
    content = _validated_snapshot_bytes(config, round_number)
    try:
        if not snapshot_existed:
            _write_bytes_atomically(snapshot, content)
        expected = _round_state_values(
            config,
            round_number,
            author_snapshot_sha256=_snapshot_digest(content),
        )
        return _write_round_state(target, expected)
    except Exception:
        if not snapshot_existed and snapshot.is_file():
            snapshot.unlink()
        raise


def replace_round_state_for_explicit_migration(
    config: ProjectConfig, round_number: int
) -> Path:
    """Replace frozen identity only for an explicitly confirmed state migration."""
    from .authors import resolve_author_library_path

    metadata = load_meta(config.round_dir(round_number) / "meta.yaml")
    if metadata.parent_round is not None:
        ensure_historical_round_state(config, metadata.parent_round)
    snapshot = config.author_snapshot_path(round_number)
    if not snapshot.is_file():
        target = config.round_state_path(round_number)
        try:
            observed = yaml.safe_load(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise WorkflowError(f"HISTORICAL_ROUND_STATE_INVALID: {target}") from exc
        v1_identity = {
            "schema": "sci-manuscript-round-state/v1",
            "round": round_name(round_number),
            "parent": (
                None
                if metadata.parent_round is None
                else round_name(metadata.parent_round)
            ),
            "scientific_source_sha256": source_digest(
                config.round_dir(round_number), scientific_only=True
            ),
            "metadata_sha256": _path_digest(
                config.round_dir(round_number) / "meta.yaml"
            ),
            "effective_authors_sha256": _path_digest(resolve_author_library_path()),
        }
        if not isinstance(observed, dict) or any(
            observed.get(key) != value for key, value in v1_identity.items()
        ):
            raise WorkflowError(
                "HISTORICAL_ROUND_STATE_MISMATCH: the explicit bibliography "
                "migration cannot prove the non-bibliography frozen state."
            )
        _write_bytes_atomically(
            snapshot,
            _validated_snapshot_bytes(config, round_number),
        )
    else:
        _validated_snapshot_bytes(config, round_number)
    return _write_round_state(
        config.round_state_path(round_number),
        _round_state_values(config, round_number),
    )


def _migrate_v1_round_state(
    config: ProjectConfig,
    round_number: int,
    observed: dict[str, object],
) -> Path:
    """Upgrade a v1 hash-only author contract when its live source still proves it."""
    from .authors import resolve_author_library_path

    metadata = load_meta(config.round_dir(round_number) / "meta.yaml")
    expected_v1 = {
        "schema": "sci-manuscript-round-state/v1",
        "round": round_name(round_number),
        "parent": (
            None if metadata.parent_round is None else round_name(metadata.parent_round)
        ),
        "scientific_source_sha256": source_digest(
            config.round_dir(round_number), scientific_only=True
        ),
        "metadata_sha256": _path_digest(config.round_dir(round_number) / "meta.yaml"),
        "bibliography_snapshot_sha256": _path_digest(
            config.bibliography_snapshot_path(round_number)
        ),
        "effective_authors_sha256": _path_digest(resolve_author_library_path()),
    }
    if observed != expected_v1:
        raise WorkflowError(
            "HISTORICAL_ROUND_STATE_MISMATCH: cannot migrate the v1 frozen state "
            f"for {round_name(round_number)} because its live inputs differ."
        )
    if metadata.parent_round is not None:
        ensure_historical_round_state(config, metadata.parent_round)
    snapshot = config.author_snapshot_path(round_number)
    snapshot_existed = snapshot.is_file()
    content = _validated_snapshot_bytes(config, round_number)
    try:
        if not snapshot_existed:
            _write_bytes_atomically(snapshot, content)
        return _write_round_state(
            config.round_state_path(round_number),
            _round_state_values(
                config,
                round_number,
                author_snapshot_sha256=_snapshot_digest(content),
            ),
        )
    except Exception:
        if not snapshot_existed and snapshot.is_file():
            snapshot.unlink()
        raise


def _bootstrap_legacy_round_state(config: ProjectConfig, round_number: int) -> Path:
    """Migrate a legacy history only when its last manifest proves identity."""
    from .authors import resolve_author_library_path

    manifest_path = config.build_manifest_path(round_number)
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkflowError(
            "HISTORICAL_ROUND_STATE_UNAVAILABLE: no valid frozen state or legacy "
            f"build manifest exists for {round_name(round_number)}."
        ) from exc
    metadata = load_meta(config.round_dir(round_number) / "meta.yaml")
    if metadata.parent_round is not None:
        ensure_historical_round_state(config, metadata.parent_round)
    snapshot = config.author_snapshot_path(round_number)
    snapshot_existed = snapshot.is_file()
    snapshot_content = _validated_snapshot_bytes(config, round_number)
    expected = _round_state_values(
        config,
        round_number,
        author_snapshot_sha256=_snapshot_digest(snapshot_content),
    )
    inputs = manifest.get("inputs") if isinstance(manifest, dict) else None
    artifact_inputs = (
        manifest.get("artifact_inputs") if isinstance(manifest, dict) else None
    )
    metadata_digests = (
        {
            value.get("round_metadata_sha256")
            for value in artifact_inputs.values()
            if isinstance(value, dict)
        }
        if isinstance(artifact_inputs, dict)
        else set()
    )
    child_manifest: object = None
    child_path = config.build_manifest_path(round_number + 1)
    if child_path.is_file():
        try:
            child_manifest = yaml.safe_load(child_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            child_manifest = None
    child_inputs = (
        child_manifest.get("inputs") if isinstance(child_manifest, dict) else None
    )
    source_proven = bool(
        isinstance(inputs, dict)
        and inputs.get("scientific_source_sha256")
        == expected["scientific_source_sha256"]
    ) or bool(
        isinstance(child_inputs, dict)
        and child_inputs.get("parent_scientific_source_sha256")
        == expected["scientific_source_sha256"]
    )
    bibliography_proven = bool(
        isinstance(inputs, dict)
        and inputs.get("references_bib_sha256")
        == expected["bibliography_snapshot_sha256"]
    ) or bool(
        isinstance(child_inputs, dict)
        and child_inputs.get("parent_references_bib_sha256")
        == expected["bibliography_snapshot_sha256"]
    )
    authors_proven = bool(
        isinstance(inputs, dict)
        and inputs.get("effective_authors_sha256")
        == _path_digest(resolve_author_library_path())
    ) or bool(
        isinstance(child_inputs, dict)
        and child_inputs.get("effective_authors_sha256")
        == _path_digest(resolve_author_library_path())
    )
    proven = bool(
        isinstance(manifest, dict)
        and manifest.get("schema") == "sci-manuscript-build-manifest/v3"
        and manifest.get("round") == expected["round"]
        and manifest.get("parent") == expected["parent"]
        and source_proven
        and bibliography_proven
        and authors_proven
        and expected["metadata_sha256"] in metadata_digests
    )
    if not proven:
        raise WorkflowError(
            "HISTORICAL_ROUND_STATE_UNAVAILABLE: the legacy build manifest cannot "
            f"prove the current scientific state of {round_name(round_number)}. "
            "Restore the audited historical source, metadata, author metadata, "
            "and bibliography snapshot before rebuilding."
        )
    try:
        if not snapshot_existed:
            _write_bytes_atomically(snapshot, snapshot_content)
        return _write_round_state(config.round_state_path(round_number), expected)
    except Exception:
        if not snapshot_existed and snapshot.is_file():
            snapshot.unlink()
        raise


def _ensure_one_historical_round_state(
    config: ProjectConfig,
    round_number: int,
) -> Path:
    target = config.round_state_path(round_number)
    if not target.is_file():
        _bootstrap_legacy_round_state(config, round_number)
    try:
        observed = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkflowError(f"HISTORICAL_ROUND_STATE_INVALID: {target}") from exc
    if not isinstance(observed, dict):
        raise WorkflowError(f"HISTORICAL_ROUND_STATE_INVALID: {target}")
    if observed.get("schema") == "sci-manuscript-round-state/v1":
        _migrate_v1_round_state(config, round_number, observed)
        observed = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(observed, dict) or observed.get("schema") != (
        "sci-manuscript-round-state/v2"
    ):
        raise WorkflowError(
            "HISTORICAL_ROUND_STATE_MISMATCH: unsupported frozen-state schema "
            f"for {round_name(round_number)}: {target}"
        )
    expected = _round_state_values(config, round_number)
    mismatches = [key for key, value in expected.items() if observed.get(key) != value]
    if mismatches or set(observed) != set(expected):
        detail = ", ".join(mismatches or ("unexpected fields",))
        raise WorkflowError(
            "HISTORICAL_ROUND_STATE_MISMATCH: "
            f"{round_name(round_number)} differs from {target} ({detail}). "
            "Restore the frozen historical source/state before rebuilding."
        )
    _validated_snapshot_bytes(config, round_number)
    return target


def ensure_historical_round_state(config: ProjectConfig, round_number: int) -> Path:
    """Verify one historical round and every ancestor it can consume."""
    rounds = _round_numbers(config.project)
    if round_number == rounds[-1]:
        raise WorkflowError(
            "Historical round-state verification was requested for the active round."
        )
    verified = config.round_state_path(round_number)
    for ancestor in range(round_number + 1):
        verified = _ensure_one_historical_round_state(config, ancestor)
    return verified


def _tool_version(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        return "unknown"
    for option in ("--version", "-v"):
        try:
            result = subprocess.run(
                [executable, option],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        first = next(
            (
                line.strip()
                for line in (result.stdout + result.stderr).splitlines()
                if line.strip()
            ),
            "unknown",
        )
        return first[:200]
    return "unknown"


def _implementation_digest() -> str:
    """Hash the installed production Python implementation deterministically."""
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(package).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _toolchain_identity(
    config: ProjectConfig, engine_override: str | None
) -> dict[str, str]:
    """Return the selected compiler and renderer-tool identity."""
    from .compile import _latex_driver, resolve_engine

    selected_engine = resolve_engine(config, engine_override)
    driver = selected_engine
    if selected_engine == "latex":
        _flag, driver = _latex_driver(config)
    bibliography_tool = "bibtex" if shutil.which("bibtex") else "biber"
    return {
        "engine": selected_engine,
        "engine_version": _tool_version(
            "tectonic" if selected_engine == "tectonic" else "latexmk"
        ),
        "driver": driver,
        "latexdiff": _tool_version("latexdiff"),
        "pdftotext": _tool_version("pdftotext"),
        "pdftoppm": _tool_version("pdftoppm"),
        "bibliography_tool": bibliography_tool,
        "bibliography_tool_version": _tool_version(bibliography_tool),
    }


def _build_input_fingerprints(
    config: ProjectConfig,
    round_number: int,
    engine_override: str | None = None,
) -> dict[str, object]:
    """Return content hashes governing reusable build artifacts."""
    from .templates import publisher_resource

    author_source = author_library_source_for_round(config, round_number)
    bundled = resources_root() / "authors.yaml"
    if author_source == config.author_snapshot_path(round_number):
        author_kind = "frozen"
    else:
        author_kind = (
            "bundled" if author_source.resolve() == bundled.resolve() else "configured"
        )
    version = config.round_dir(round_number)
    values: dict[str, object] = {
        "scientific_source_sha256": source_digest(version, scientific_only=True),
        "protected_user_source_sha256": source_digest(version),
        "references_bib_sha256": _path_digest(
            bibliography_source_for_round(config, round_number)
        ),
        "effective_authors_source": author_kind,
        "effective_authors_sha256": _path_digest(author_source),
        "publisher_resource_sha256": _path_digest(publisher_resource(config)),
        "manuscript_preamble_sha256": _path_digest(
            resources_root() / "manuscript_preamble"
        ),
        "revision_style_sha256": _path_digest(config.references / "revision_style.tex"),
        "revision_runtime_sha256": _path_digest(resources_root() / "revision"),
        "implementation_sha256": _implementation_digest(),
        "toolchain": _toolchain_identity(config, engine_override),
    }
    if round_number > 0:
        parent = config.round_dir(round_number - 1)
        values.update(
            {
                "parent_scientific_source_sha256": source_digest(
                    parent, scientific_only=True
                ),
                "parent_references_bib_sha256": _path_digest(
                    bibliography_source_for_round(config, round_number - 1)
                ),
            }
        )
    return values


def _mapping_digest(values: dict[str, object]) -> str:
    encoded = json.dumps(
        values, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _response_reference_digest(path: Path) -> str:
    """Hash only ReviewReference declarations consumed by marked output."""
    from .review import parse_response_source

    if not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    references = parse_response_source(path).references
    return _mapping_digest(
        {
            "references": [
                {
                    "review_id": item.review_id,
                    "citation_keys": list(item.citation_keys),
                }
                for item in references
            ]
        }
    )


def _artifact_input_fingerprints(
    config: ProjectConfig,
    round_number: int,
    artifact: Path,
    engine_override: str | None = None,
) -> dict[str, object]:
    """Return the exact dependency contract for one publication artifact."""
    base = _build_input_fingerprints(config, round_number, engine_override)
    version = config.round_dir(round_number)
    clean_keys = (
        "scientific_source_sha256",
        "references_bib_sha256",
        "effective_authors_source",
        "effective_authors_sha256",
        "publisher_resource_sha256",
        "manuscript_preamble_sha256",
        "implementation_sha256",
        "toolchain",
    )
    values = {key: base[key] for key in clean_keys}
    values["round_metadata_sha256"] = _path_digest(version / "meta.yaml")
    if artifact.name in {"manuscript.pdf", "manuscript_clean.pdf"}:
        return values
    if round_number == 0:
        return base
    values.update(
        {
            "parent_scientific_source_sha256": base["parent_scientific_source_sha256"],
            "parent_references_bib_sha256": base["parent_references_bib_sha256"],
            "revision_style_sha256": base["revision_style_sha256"],
            "revision_runtime_sha256": base["revision_runtime_sha256"],
            "review_reference_provenance_sha256": _response_reference_digest(
                config.response_dir(round_number) / "responses.tex"
            ),
        }
    )
    if artifact.name == "manuscript_marked.pdf":
        return values
    if artifact.name == "response_letter.pdf":
        response_dir = config.response_dir(round_number)
        response_template = (
            resources_root()
            / "correspondence_templates"
            / "response"
            / f"response_{config.language}.tex"
        )
        location_inputs = dict(values)
        values.update(
            {
                "responses_source_sha256": _path_digest(response_dir / "responses.tex"),
                "reviewer_comments_sha256": _path_digest(
                    response_dir / "reviewer_comments.md"
                ),
                "response_template_sha256": _path_digest(response_template),
                "marked_location_inputs_sha256": _mapping_digest(location_inputs),
                "reference_location_inputs_sha256": _mapping_digest(
                    {
                        "marked": location_inputs,
                        "review_references": values[
                            "review_reference_provenance_sha256"
                        ],
                    }
                ),
            }
        )
        return values
    return base


def artifact_input_digest(
    config: ProjectConfig,
    round_number: int,
    artifact: Path,
    engine_override: str | None = None,
) -> str:
    """Return the stable manifest input digest for one artifact."""
    return _mapping_digest(
        _artifact_input_fingerprints(config, round_number, artifact, engine_override)
    )


def build_artifact_is_current(
    config: ProjectConfig,
    round_number: int,
    artifact: Path,
    engine_override: str | None = None,
) -> bool:
    """Return whether one final artifact matches a current build manifest hash."""
    if not artifact.is_file():
        return False
    try:
        data = yaml.safe_load(
            config.build_manifest_path(round_number).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    if not isinstance(data, dict) or data.get("schema") != (
        "sci-manuscript-build-manifest/v3"
    ):
        return False
    try:
        relative = artifact.resolve().relative_to(config.project.resolve()).as_posix()
    except ValueError:
        return False
    outputs = data.get("outputs", {}) if isinstance(data, dict) else {}
    artifact_inputs = data.get("artifact_inputs", {})
    return bool(
        isinstance(outputs, dict)
        and isinstance(artifact_inputs, dict)
        and outputs.get(relative) == _path_digest(artifact)
        and artifact_inputs.get(relative)
        == _artifact_input_fingerprints(config, round_number, artifact, engine_override)
    )


def write_build_manifest(
    config: ProjectConfig,
    round_number: int,
    operation: str,
    outputs: tuple[Path, ...],
    engine_override: str | None,
    run_dir: Path,
    targets: tuple[str, ...] = (),
) -> Path:
    """Atomically record one successful build without private absolute paths."""
    from .compile import _latex_driver, resolve_engine
    from .templates import publisher_resource

    selected_engine = resolve_engine(config, engine_override)
    driver = selected_engine
    if selected_engine == "latex":
        _flag, driver = _latex_driver(config)
    try:
        skill_version = importlib.metadata.version("sci-manuscript-skill")
    except importlib.metadata.PackageNotFoundError:
        skill_version = "unknown"
    font_paths = sorted(
        {path.resolve() for path in run_dir.rglob("Fandol*.otf") if path.is_file()}
    )
    publisher = publisher_resource(config)
    preamble = resources_root() / "manuscript_preamble"
    output_files = {
        path.resolve()
        for path in outputs
        if path.is_file() and path.resolve().is_relative_to(config.project.resolve())
    }
    if operation == "submission":
        submission = config.submission_dir(round_number)
        submission_outputs = set(GENERATED_SUBMISSION_PATHS) | {
            Path("checklist.md"),
            Path("graphical_abstract/graphical_abstract.pdf"),
        }
        output_files.update(
            (submission / relative).resolve()
            for relative in submission_outputs
            if (submission / relative).is_file()
        )
    inputs = _build_input_fingerprints(config, round_number, engine_override)
    previous_outputs: dict[str, str] = {}
    previous_artifact_inputs: dict[str, dict[str, object]] = {}
    previous_path = config.build_manifest_path(round_number)
    if previous_path.is_file():
        try:
            previous = yaml.safe_load(previous_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            previous = None
        if (
            isinstance(previous, dict)
            and previous.get("schema") == "sci-manuscript-build-manifest/v3"
            and isinstance(previous.get("outputs"), dict)
            and isinstance(previous.get("artifact_inputs"), dict)
        ):
            for relative, digest in previous["outputs"].items():
                candidate = config.project / relative
                current_inputs = _artifact_input_fingerprints(
                    config, round_number, candidate, engine_override
                )
                if (
                    candidate.is_file()
                    and _path_digest(candidate) == digest
                    and previous["artifact_inputs"].get(relative) == current_inputs
                ):
                    previous_outputs[relative] = digest
                    previous_artifact_inputs[relative] = current_inputs
    current_outputs = {
        path.relative_to(config.project.resolve()).as_posix(): _path_digest(path)
        for path in sorted(output_files)
    }
    current_artifact_inputs = {
        path.relative_to(config.project.resolve()).as_posix(): (
            _artifact_input_fingerprints(config, round_number, path, engine_override)
        )
        for path in sorted(output_files)
    }
    artifact_inputs = {**previous_artifact_inputs, **current_artifact_inputs}
    manifest = {
        "schema": "sci-manuscript-build-manifest/v3",
        "operation": operation,
        "targets": list(targets),
        "round": round_name(round_number),
        "parent": None if round_number == 0 else round_name(round_number - 1),
        "skill_version": skill_version,
        "python_version": platform.python_version(),
        "engine": {
            "name": selected_engine,
            "version": _tool_version(
                "tectonic" if selected_engine == "tectonic" else "latexmk"
            ),
            "driver": driver,
        },
        "tools": {
            "latexdiff": _tool_version("latexdiff"),
            "pdftotext": _tool_version("pdftotext"),
            "pdftoppm": _tool_version("pdftoppm"),
            "bibtex_or_biber": _tool_version("bibtex")
            if shutil.which("bibtex")
            else _tool_version("biber"),
        },
        "resources": {
            "publisher": {
                "key": config.metadata.publisher,
                "sha256": _path_digest(publisher),
            },
            "manuscript_preamble_sha256": _path_digest(preamble),
            "revision_style_sha256": _path_digest(
                config.references / "revision_style.tex"
            ),
        },
        "inputs": inputs,
        "artifact_inputs": artifact_inputs,
        "artifact_input_digests": {
            relative: _mapping_digest(values)
            for relative, values in artifact_inputs.items()
        },
        "fonts": [
            {"name": path.name, "sha256": _path_digest(path)} for path in font_paths
        ],
        "outputs": {**previous_outputs, **current_outputs},
    }
    target = config.build_manifest_path(round_number)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".yaml.new")
    try:
        temporary.write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return target


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
    snapshot_bibliography(config, config.current_round)
    staged = staging_root / revision_directory_name(target_round)
    staged.mkdir(parents=True)
    source_manuscript = source / "manuscript.tex"
    if not source_manuscript.is_file():
        raise WorkflowError(f"Parent manuscript source is missing: {source_manuscript}")
    shutil.copy2(source_manuscript, staged / "manuscript.tex")
    for directory in INHERITED_DIRECTORIES:
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
        shutil.copy2(
            resources_root()
            / "reviewer_comments"
            / f"reviewer_comments_{config.language}.md",
            comments,
        )
    else:
        shutil.copy2(reviews, comments)
    child = with_revision(config.metadata, target_round)
    shutil.copy2(source / "meta.yaml", staged / "meta.yaml")
    save_meta(staged / "meta.yaml", child)
    os.replace(staged, target)
    try:
        freeze_round_state(config, config.current_round)
    except Exception:
        if target.is_dir():
            shutil.rmtree(target)
        raise
    return ProjectConfig(config.project, child, config.engine)


def finalize_revision_creation(config: ProjectConfig) -> Path:
    """Record the protected post-creation source digest."""
    version = config.round_dir(config.current_round)
    path = config.creation_record_path(config.current_round)
    data = {
        "round": round_name(config.current_round),
        "parent": round_name(config.current_round - 1),
        "created_from": revision_directory_name(config.current_round - 1),
        "protected_source_digest": source_digest(version),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


def _load_creation(config: ProjectConfig, round_number: int) -> dict[str, str]:
    path = config.creation_record_path(round_number)
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
    record = _load_creation(latest, latest.current_round)
    if source_digest(version) != record["protected_source_digest"]:
        raise WorkflowError(
            "Rollback refused: protected user or scientific source has changed."
        )
    previous_round = latest.current_round - 1
    previous_bibliography = latest.bibliography_snapshot_path(previous_round)
    if not previous_bibliography.is_file():
        raise WorkflowError(
            "Rollback refused: the previous round's bibliography snapshot is "
            f"missing for {round_name(previous_round)}."
        )
    shared_bibliography = latest.references / "references.bib"
    current_snapshot = latest.bibliography_snapshot_path(latest.current_round)
    snapshot_existed = current_snapshot.is_file()
    snapshot_backup = current_snapshot.read_bytes() if snapshot_existed else None
    snapshot_bibliography(latest, latest.current_round)
    archive = _archive_directory(latest.project, "rollback")
    archived = archive / version.name
    state = latest.state_dir(latest.current_round)
    archived_state = archive / "state" / version.name
    try:
        os.replace(version, archived)
        if state.exists():
            archived_state.parent.mkdir()
            os.replace(state, archived_state)
        _copy_file_atomically(previous_bibliography, shared_bibliography)
        load_project(latest.project)
    except Exception:
        archived_bibliography = archived_state / "bibliography.bib"
        if archived_bibliography.is_file():
            _copy_file_atomically(archived_bibliography, shared_bibliography)
        if archived_state.exists() and not state.exists():
            state.parent.mkdir(exist_ok=True)
            os.replace(archived_state, state)
        if archived.exists() and not version.exists():
            os.replace(archived, version)
        if snapshot_existed and snapshot_backup is not None:
            current_snapshot.write_bytes(snapshot_backup)
        elif current_snapshot.is_file():
            current_snapshot.unlink()
        raise
    previous_round_state = latest.round_state_path(previous_round)
    if previous_round_state.is_file():
        previous_round_state.unlink()
    previous_authors = latest.author_snapshot_path(previous_round)
    if previous_authors.is_file():
        previous_authors.unlink()
    return archived, latest.current_round - 1


def _clear_generated(
    version: Path, *, additional_generated: set[Path] | None = None
) -> None:
    output = version / "output"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    submission = version / "submission"
    submission.mkdir(exist_ok=True)
    for relative in GENERATED_SUBMISSION_PATHS:
        generated = submission / relative
        if generated.is_file() or generated.is_symlink():
            generated.unlink()
    dynamic = _generated_submission_paths(version) | (additional_generated or set())
    for relative in dynamic:
        generated = submission / relative
        if generated.is_file() or generated.is_symlink():
            generated.unlink()
    checklist = submission / "checklist.md"
    if checklist.is_file():
        checklist.write_bytes(REVIEW_COMPLETENESS_LINE.sub(b"", checklist.read_bytes()))


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
    state_root = root / "state"
    if state_root.is_dir():
        shutil.copytree(state_root, archive / "state")
    stage = run_dir / "reindex_stage"
    state_stage = run_dir / "reindex_state"
    originals = run_dir / "reindex_originals"
    stage.mkdir()
    state_stage.mkdir()
    originals.mkdir()
    if state_root.is_dir():
        for path in state_root.iterdir():
            if REVISION_DIRECTORY_PATTERN.fullmatch(path.name):
                continue
            target = state_stage / path.name
            if path.is_dir():
                shutil.copytree(path, target)
            else:
                shutil.copy2(path, target)
    scientific_before: dict[int, str] = {}
    for new_number, old_number in enumerate(revisions, 1):
        source = root / f"revision_{old_number:02d}"
        scientific_before[new_number] = source_digest(source, scientific_only=True)
        target = stage / f"revision_{new_number:02d}"
        shutil.copytree(source, target)
        metadata = load_meta(target / "meta.yaml")
        save_meta(target / "meta.yaml", with_revision(metadata, new_number))
        _clear_generated(
            target,
            additional_generated=_generated_submission_paths(source),
        )
        state_target = state_stage / revision_directory_name(new_number)
        state_source = state_root / revision_directory_name(old_number)
        if state_source.is_dir():
            shutil.copytree(state_source, state_target)
        else:
            state_target.mkdir()
        canonical_creation = state_target / "creation.yaml"
        if canonical_creation.exists():
            canonical_creation.unlink()
        data = {
            "round": round_name(new_number),
            "parent": round_name(new_number - 1),
            "created_from": revision_directory_name(new_number - 1),
            "protected_source_digest": source_digest(target),
        }
        canonical_creation.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        canonical_round_state = state_target / "round_state.yaml"
        if canonical_round_state.is_file():
            canonical_round_state.unlink()
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
        if state_root.exists():
            state_backup = originals / "state"
            os.replace(state_root, state_backup)
            moved.append((state_backup, state_root))
        if fail_after_swap:
            raise WorkflowError("Injected reindex failure after source swap.")
        for path in sorted(stage.iterdir()):
            target = root / path.name
            os.replace(path, target)
            installed.append(target)
        os.replace(state_stage, state_root)
        installed.append(state_root)
        load_project(root)
        for number in range(1, len(revisions)):
            freeze_round_state(load_project(root, number), number)
    except Exception:
        for target in installed:
            if target.exists():
                shutil.rmtree(target)
        for backup, source in reversed(moved):
            if backup.exists():
                os.replace(backup, source)
        raise
    return mapping


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
