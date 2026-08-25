"""Stable high-level Python API for the manuscript lifecycle."""

from __future__ import annotations

import importlib.metadata
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .authors import load_author_library, resolve_author_library_path, resolve_authors
from .bibliography import sync_bibliography
from .compile import (
    SUPPORTED_ENGINES,
    CjkProbeResult,
    build_clean_manuscript,
    ensure_cjk_environment,
    probe_cjk_environment,
    publish_file_atomically,
    select_engine,
    validate_revision_layout,
)
from .diff import build_marked_manuscript
from .errors import WorkflowError
from .metadata import (
    PUBLISHERS,
    ManuscriptMetadata,
    SubmissionSettings,
    validate_publisher_language,
)
from .response import build_response, ensure_response_source, init_response
from .review import (
    ReviewAuditResult,
    audit_reviews,
    parse_reviews,
    review_ids_from_sources,
)
from .submission import prepare_submission_artifacts
from .templates import ensure_manuscript_sources
from .workspace import (
    GENERATED_SUBMISSION_PATHS,
    ProjectConfig,
    finalize_revision_creation,
    initialize_draft_project,
    initialize_project,
    is_initialized,
    load_project,
    normalize_project,
    parse_round,
    reindex_revisions,
    revision_directory_name,
    rollback_revision,
    round_name,
    snapshot_bibliography,
    start_revision,
    temporary_run,
    write_build_manifest,
)

OUTPUT_PDF_NAMES = (
    "manuscript.pdf",
    "manuscript_clean.pdf",
    "manuscript_marked.pdf",
    "response_letter.pdf",
)


@dataclass(frozen=True)
class Artifact:
    """One user-facing workflow artifact."""

    label: str
    path: Path


@dataclass(frozen=True)
class LifecycleResult:
    """Structured result for a lifecycle mutation or build."""

    operation: str
    version: str
    artifacts: tuple[Artifact, ...]
    review_audit: ReviewAuditResult | None = None


@dataclass(frozen=True)
class StatusResult:
    """Structured current project state."""

    project: Path
    version: str
    round: str
    parent: str | None
    journal: str
    publisher: str
    authors: tuple[str, ...]
    artifacts: tuple[Path, ...]


def _snapshot_files(
    paths: tuple[Path, ...], backup_root: Path
) -> dict[Path, Path | None]:
    """Copy an exact final-artifact set before a multi-file publication."""
    backup_root.mkdir(parents=True, exist_ok=True)
    snapshot: dict[Path, Path | None] = {}
    for index, path in enumerate(dict.fromkeys(paths)):
        if path.is_file():
            backup = backup_root / f"{index:03d}"
            shutil.copy2(path, backup)
            snapshot[path] = backup
        else:
            snapshot[path] = None
    return snapshot


def _restore_files(snapshot: dict[Path, Path | None]) -> None:
    """Restore an artifact snapshot without touching any unlisted user source."""
    for target, backup in snapshot.items():
        if backup is None:
            if target.is_file() or target.is_symlink():
                target.unlink()
            continue
        publish_file_atomically(backup, target)


def _output_pdf_paths(config: ProjectConfig, round_number: int) -> tuple[Path, ...]:
    output = config.output_dir(round_number)
    return tuple(output / name for name in OUTPUT_PDF_NAMES)


def _submission_publication_paths(
    config: ProjectConfig, round_number: int
) -> tuple[Path, ...]:
    submission = config.submission_dir(round_number)
    return (
        *(submission / relative for relative in GENERATED_SUBMISSION_PATHS),
        submission / "graphical_abstract" / "graphical_abstract.pdf",
        submission / "checklist.md",
        config.generated_artifacts_path(round_number),
    )


@dataclass(frozen=True)
class DoctorCheck:
    """One environment dependency result."""

    name: str
    available: bool
    detail: str
    required: bool


@dataclass(frozen=True)
class DoctorResult:
    """Read-only environment inspection result."""

    ready: bool
    checks: tuple[DoctorCheck, ...]


def _tool_detail(name: str) -> tuple[bool, str]:
    executable = shutil.which(name)
    if executable is None:
        return False, "not found"
    return True, executable


def doctor(
    *,
    language: str | None = None,
    publisher: str | None = None,
    engine: str = "auto",
) -> DoctorResult:
    """Inspect required manuscript tooling without changing the environment."""
    if engine not in SUPPORTED_ENGINES:
        raise WorkflowError(f"Unsupported engine: {engine}")
    engine_error = ""
    try:
        yaml_version = importlib.metadata.version("PyYAML")
        yaml_ok = True
    except importlib.metadata.PackageNotFoundError:
        yaml_version = "not installed"
        yaml_ok = False
    tectonic = _tool_detail("tectonic")
    latexmk = _tool_detail("latexmk")
    xelatex = _tool_detail("xelatex")
    pdflatex = _tool_detail("pdflatex")
    bibtex = _tool_detail("bibtex")
    biber = _tool_detail("biber")
    pdftotext = _tool_detail("pdftotext")
    pdftoppm = _tool_detail("pdftoppm")
    latexdiff = _tool_detail("latexdiff")
    try:
        selected = select_engine(engine)
    except WorkflowError as exc:
        selected = None
        engine_error = str(exc)
    if selected == "tectonic":
        engine_check = DoctorCheck("Tectonic", tectonic[0], tectonic[1], True)
        bibliography_check = DoctorCheck(
            "BibTeX/Biber backend",
            tectonic[0],
            "Tectonic integrated" if tectonic[0] else "Tectonic is unavailable",
            True,
        )
    elif selected == "latex":
        chinese = language == "zh" or publisher == "chinese"
        driver_ok = xelatex[0] if chinese else pdflatex[0] or xelatex[0]
        driver_detail = (
            f"xelatex={xelatex[1]}"
            if chinese
            else f"pdflatex={pdflatex[1]}; xelatex={xelatex[1]}"
        )
        engine_check = DoctorCheck(
            "latexmk and driver",
            latexmk[0] and driver_ok,
            f"latexmk={latexmk[1]}; {driver_detail}",
            True,
        )
        bibliography_check = DoctorCheck(
            "BibTeX/Biber backend",
            bibtex[0] or biber[0],
            f"bibtex={bibtex[1]}; biber={biber[1]}",
            True,
        )
    else:
        engine_check = DoctorCheck("LaTeX engine", False, engine_error, True)
        bibliography_check = DoctorCheck(
            "BibTeX/Biber backend", False, "No engine was selected", True
        )
    checks: tuple[DoctorCheck, ...] = (
        DoctorCheck(
            "Python >= 3.11",
            sys.version_info >= (3, 11),
            sys.version.split()[0],
            True,
        ),
        DoctorCheck("PyYAML", yaml_ok, yaml_version, True),
        engine_check,
        DoctorCheck("latexdiff", latexdiff[0], latexdiff[1], True),
        DoctorCheck(
            "Poppler PDF tools",
            pdftotext[0] and pdftoppm[0],
            f"pdftotext={pdftotext[1]}; pdftoppm={pdftoppm[1]}",
            True,
        ),
        bibliography_check,
        DoctorCheck("Ruff", _tool_detail("ruff")[0], _tool_detail("ruff")[1], False),
        DoctorCheck("Mypy", _tool_detail("mypy")[0], _tool_detail("mypy")[1], False),
    )
    if language == "zh" or publisher == "chinese":
        cjk = (
            probe_cjk_environment(selected)
            if selected is not None
            else CjkProbeResult(False, engine_error)
        )
        checks = (
            *checks,
            DoctorCheck("CJK compilation probe", cjk.ready, cjk.detail, True),
        )
    return DoctorResult(
        all(check.available for check in checks if check.required), checks
    )


def initialize_manuscript(
    path: str | Path,
    *,
    title: str,
    journal: str,
    publisher: str,
    language: str,
    article_type: str,
    first_authors: tuple[str, ...],
    corresponding_authors: tuple[str, ...],
    other_authors: tuple[str, ...] = (),
    bibliography_path: str | Path | None = None,
    custom_template: str | Path | None = None,
    engine: str = "auto",
) -> LifecycleResult:
    """Initialize and compile ``path/manuscript/initial_submission``."""
    if publisher not in PUBLISHERS:
        raise WorkflowError(f"Unsupported publisher: {publisher}")
    validate_publisher_language(publisher, language)
    author_source = resolve_author_library_path()
    library = load_author_library(author_source)
    metadata = ManuscriptMetadata(
        title=title,
        article_type=article_type,
        language=language,
        journal_name=journal,
        publisher=publisher,
        round_number=0,
        parent_round=None,
        first_authors=first_authors,
        corresponding_authors=corresponding_authors,
        other_authors=other_authors,
        submission=SubmissionSettings(),
    )
    resolve_authors(metadata, library)
    manuscript_root = normalize_project(path, initialize=True)
    config = ProjectConfig(manuscript_root, metadata, engine)
    ensure_cjk_environment(config, engine)
    initialize_project(
        config,
        (Path(bibliography_path).expanduser().resolve() if bibliography_path else None),
        (
            Path(custom_template).expanduser().resolve()
            if custom_template is not None
            else None
        ),
    )
    with temporary_run(manuscript_root) as run_dir:
        manuscript = build_clean_manuscript(config, 0, run_dir, engine)
    return LifecycleResult(
        "init",
        revision_directory_name(0),
        (Artifact("Initial manuscript", manuscript),),
    )


def initialize_manuscript_draft(path: str | Path) -> LifecycleResult:
    """Create a metadata-first workspace without compiling or inventing content."""
    metadata_path = initialize_draft_project(path)
    return LifecycleResult(
        "init",
        revision_directory_name(0),
        (Artifact("Metadata template", metadata_path),),
    )


class ManuscriptProject:
    """High-level lifecycle operations for one project/manuscript workspace."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if not is_initialized(self.path):
            raise WorkflowError(
                f"Project is not initialized: {self.path}. Run sci-manuscript init."
            )
        self.root = normalize_project(self.path)

    def doctor(self) -> DoctorResult:
        """Return the current read-only environment report."""
        return doctor()

    def status(self) -> StatusResult:
        """Return current ancestry, metadata, and final artifacts."""
        latest = load_project(self.root)
        artifacts: list[Path] = []
        for number in range(latest.current_round + 1):
            version = latest.round_dir(number)
            artifacts.extend(sorted((version / "output").glob("*.pdf")))
            submission = latest.submission_dir(number)
            for name in (
                "manuscript.pdf",
                "marked_manuscript.pdf",
                "response_letter.pdf",
                "cover_letter.pdf",
                "highlights.pdf",
                "checklist.md",
            ):
                path = submission / name
                if path.is_file():
                    artifacts.append(path)
            graphical = submission / "graphical_abstract" / "graphical_abstract.pdf"
            if graphical.is_file():
                artifacts.append(graphical)
        return StatusResult(
            self.root,
            revision_directory_name(latest.current_round),
            round_name(latest.current_round),
            (
                None
                if latest.metadata.parent_round is None
                else round_name(latest.metadata.parent_round)
            ),
            latest.journal,
            latest.metadata.publisher,
            latest.metadata.author_ids,
            tuple(artifacts),
        )

    def build(
        self,
        round: str | int | None = None,
        *,
        engine: str | None = None,
        keep_temp: bool = False,
    ) -> LifecycleResult:
        """Compile clean and marked outputs and audit revision completeness."""
        latest = load_project(self.root)
        selected = parse_round(round, latest.current_round)
        config = load_project(self.root, selected)
        ensure_manuscript_sources(config, selected)
        audit: ReviewAuditResult | None = None
        response_output = config.output_dir(selected) / "response_letter.pdf"
        if selected > 0:
            review_ids_from_sources(config, selected)
        with temporary_run(self.root, keep_temp) as run_dir:
            publication_paths = _output_pdf_paths(config, selected)
            if selected == latest.current_round:
                publication_paths = (
                    *publication_paths,
                    config.bibliography_snapshot_path(selected),
                )
            snapshot = _snapshot_files(publication_paths, run_dir / "output_rollback")
            try:
                clean = build_clean_manuscript(config, selected, run_dir, engine)
                artifacts = [Artifact("Clean manuscript", clean)]
                if selected > 0:
                    marked = build_marked_manuscript(config, selected, run_dir, engine)
                    artifacts.append(Artifact("Marked manuscript", marked.pdf))
                    validate_revision_layout(
                        (run_dir / "clean_build" / "manuscript.compiler.log").read_text(
                            encoding="utf-8"
                        ),
                        (
                            run_dir / "marked_build" / "manuscript_marked.compiler.log"
                        ).read_text(encoding="utf-8"),
                        run_dir / "revision_layout_qa.txt",
                    )
                    ensure_response_source(config, selected)
                    audit = audit_reviews(config, selected, record_index=True)
                    malformed = any(
                        issue.code in {"COMMENTS_INVALID", "RESPONSES_INVALID"}
                        for issue in audit.issues
                    )
                    if audit.total and not malformed:
                        response = build_response(
                            config,
                            selected,
                            marked.locations,
                            run_dir,
                            engine,
                        )
                        artifacts.append(Artifact("Response letter", response))
                    elif response_output.exists():
                        response_output.unlink()
                if selected == latest.current_round:
                    snapshot_bibliography(config, selected)
                write_build_manifest(
                    config,
                    selected,
                    "build",
                    tuple(item.path for item in artifacts),
                    engine,
                    run_dir,
                )
            except Exception:
                _restore_files(snapshot)
                raise
        return LifecycleResult(
            "build",
            revision_directory_name(selected),
            tuple(artifacts),
            audit,
        )

    def start_revision(
        self,
        *,
        reviews: str | Path | None = None,
        confirmed: bool = False,
        keep_temp: bool = False,
    ) -> LifecycleResult:
        """Create the next adjacent revision after explicit confirmation."""
        if not confirmed:
            raise WorkflowError("Revision creation requires explicit confirmation.")
        reviews_path = Path(reviews).expanduser().resolve() if reviews else None
        if reviews_path is not None:
            parse_reviews(reviews_path)
        latest = load_project(self.root)
        target_round = latest.current_round + 1
        target = latest.round_dir(target_round)
        with temporary_run(self.root, keep_temp) as run_dir:
            try:
                child = start_revision(latest, target_round, run_dir, reviews_path)
                comment_path = target / "response" / "reviewer_comments.md"
                response_source = init_response(child, target_round)
                creation = finalize_revision_creation(child)
            except Exception:
                if target.exists():
                    shutil.rmtree(target)
                state = latest.state_dir(target_round)
                if state.exists():
                    shutil.rmtree(state)
                if run_dir.exists():
                    shutil.rmtree(run_dir)
                tmp_root = latest.tmp_root()
                if tmp_root.is_dir() and not any(tmp_root.iterdir()):
                    tmp_root.rmdir()
                raise
        artifacts = [
            Artifact("Reviewer comments", comment_path),
        ]
        if response_source is not None:
            artifacts.append(Artifact("Response source", response_source))
        artifacts.append(Artifact("Revision creation record", creation))
        return LifecycleResult(
            "revision",
            revision_directory_name(target_round),
            tuple(artifacts),
        )

    def rollback(self, *, confirmed: bool = False) -> LifecycleResult:
        """Archive an untouched latest revision after explicit confirmation."""
        if not confirmed:
            raise WorkflowError("Rollback requires explicit confirmation.")
        latest = load_project(self.root)
        archived, new_latest = rollback_revision(latest)
        return LifecycleResult(
            "rollback",
            revision_directory_name(new_latest),
            (Artifact("Archived revision", archived),),
        )

    def reindex(self, *, confirmed: bool = False) -> LifecycleResult:
        """Transactionally close revision-number gaps after confirmation."""
        if not confirmed:
            raise WorkflowError("Reindex requires explicit confirmation.")
        with temporary_run(self.root) as run_dir:
            mapping = reindex_revisions(self.root, run_dir)
        latest = load_project(self.root)
        artifacts = tuple(
            Artifact(f"Reindexed {old}", self.root / new) for old, new in mapping
        )
        return LifecycleResult(
            "reindex", revision_directory_name(latest.current_round), artifacts
        )

    def sync_bib(self, bibliography: str | Path) -> LifecycleResult:
        """Replace the single shared bibliography from an explicit export."""
        target = sync_bibliography(self.root, Path(bibliography))
        return LifecycleResult(
            "sync-bib",
            revision_directory_name(load_project(self.root).current_round),
            (Artifact("Bibliography", target),),
        )

    def prepare_submission(
        self,
        round: str | int | None = None,
        *,
        engine: str | None = None,
        keep_temp: bool = False,
    ) -> LifecycleResult:
        """Build final artifacts only after a complete revision review audit."""
        latest = load_project(self.root)
        selected = parse_round(round, latest.current_round)
        config = load_project(self.root, selected)
        ensure_manuscript_sources(config, selected)
        if selected > 0:
            ensure_response_source(config, selected)
            audit = audit_reviews(config, selected, record_index=True)
            if not audit.is_complete:
                unresolved = sorted(
                    {
                        issue.review_id
                        for issue in audit.issues
                        if issue.review_id is not None
                    }
                )
                detail = (
                    f" Unresolved IDs: {', '.join(unresolved)}." if unresolved else ""
                )
                raise WorkflowError(
                    "Review responses are incomplete; formal submission is blocked."
                    + detail
                )
        else:
            audit = None
        with temporary_run(self.root, keep_temp) as run_dir:
            publication_paths = (
                *_output_pdf_paths(config, selected),
                *_submission_publication_paths(config, selected),
            )
            if selected == latest.current_round:
                publication_paths = (
                    *publication_paths,
                    config.bibliography_snapshot_path(selected),
                )
            snapshot = _snapshot_files(
                publication_paths, run_dir / "publication_rollback"
            )
            try:
                submission_artifacts = prepare_submission_artifacts(
                    config,
                    selected,
                    run_dir,
                    engine,
                    audit,
                )
                if selected == latest.current_round:
                    snapshot_bibliography(config, selected)
                write_build_manifest(
                    config,
                    selected,
                    "submission",
                    tuple(item.path for item in submission_artifacts),
                    engine,
                    run_dir,
                )
            except Exception:
                _restore_files(snapshot)
                raise
        artifacts = [Artifact(item.label, item.path) for item in submission_artifacts]
        return LifecycleResult(
            "submission",
            revision_directory_name(selected),
            tuple(artifacts),
            audit,
        )
