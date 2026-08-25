"""Workspace structure, revision transactions, bibliography, and temporary runs."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.metadata
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

    def tmp_root(self) -> Path:
        """Return the lazy reproducible run-diagnostics root."""
        return self.project / "tmp"

    def archive_root(self) -> Path:
        """Return the manuscript-lifecycle transaction archive."""
        return self.project / "00_archive"


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
        raise WorkflowError(f"Round {round_name(selected)} does not exist.")
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


def write_build_manifest(
    config: ProjectConfig,
    round_number: int,
    operation: str,
    outputs: tuple[Path, ...],
    engine_override: str | None,
    run_dir: Path,
) -> Path:
    """Atomically record one successful build without private absolute paths."""
    from .authors import resolve_author_library_path
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
    author_source = resolve_author_library_path()
    bundled = resources_root() / "authors.yaml"
    author_kind = (
        "bundled" if author_source.resolve() == bundled.resolve() else "configured"
    )
    font_paths = sorted(
        {path.resolve() for path in run_dir.rglob("Fandol*.otf") if path.is_file()}
    )
    publisher = publisher_resource(config)
    preamble = resources_root() / "manuscript_preamble"
    version = config.round_dir(round_number)
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
    manifest = {
        "schema": "sci-manuscript-build-manifest/v1",
        "operation": operation,
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
        "inputs": {
            "scientific_source_sha256": source_digest(version, scientific_only=True),
            "protected_user_source_sha256": source_digest(version),
            "references_bib_sha256": _path_digest(config.references / "references.bib"),
            "effective_authors_source": author_kind,
            "effective_authors_sha256": _path_digest(author_source),
        },
        "fonts": [
            {"name": path.name, "sha256": _path_digest(path)} for path in font_paths
        ],
        "outputs": {
            path.relative_to(config.project.resolve()).as_posix(): _path_digest(path)
            for path in sorted(output_files)
        },
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
    archive = _archive_directory(latest.project, "rollback")
    archived = archive / version.name
    state = latest.state_dir(latest.current_round)
    archived_state = archive / "state" / version.name
    try:
        os.replace(version, archived)
        if state.exists():
            archived_state.parent.mkdir()
            os.replace(state, archived_state)
        load_project(latest.project)
    except Exception:
        if archived_state.exists() and not state.exists():
            state.parent.mkdir(exist_ok=True)
            os.replace(archived_state, state)
        if archived.exists() and not version.exists():
            os.replace(archived, version)
        raise
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
