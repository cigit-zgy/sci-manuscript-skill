"""Stable high-level Python API for the manuscript lifecycle."""

from __future__ import annotations

import importlib.metadata
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .compile import build_clean_manuscript, compile_tex
from .diff import MarkedResult, build_marked_manuscript
from .metadata import (
    PUBLISHERS,
    ManuscriptMetadata,
    SubmissionSettings,
    load_author_library,
    resolve_authors,
)
from .response import build_response, init_response, parse_reviews
from .workspace import (
    ProjectConfig,
    WorkflowError,
    ensure_submission_workspace,
    finalize_revision_creation,
    initialize_project,
    is_initialized,
    load_project,
    normalize_project,
    parse_round,
    reindex_revisions,
    revision_directory_name,
    rollback_revision,
    round_name,
    start_revision,
    sync_bibliography,
    temporary_run,
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


def doctor() -> DoctorResult:
    """Inspect required manuscript tooling without changing the environment."""
    try:
        yaml_version = importlib.metadata.version("PyYAML")
        yaml_ok = True
    except importlib.metadata.PackageNotFoundError:
        yaml_version = "not installed"
        yaml_ok = False
    tectonic = _tool_detail("tectonic")
    latexmk = _tool_detail("latexmk")
    pdftotext = _tool_detail("pdftotext")
    pdftoppm = _tool_detail("pdftoppm")
    latexdiff = _tool_detail("latexdiff")
    bibliography = tectonic[0] or _tool_detail("bibtex")[0] or _tool_detail("biber")[0]
    checks = (
        DoctorCheck(
            "Python >= 3.11",
            sys.version_info >= (3, 11),
            sys.version.split()[0],
            True,
        ),
        DoctorCheck("PyYAML", yaml_ok, yaml_version, True),
        DoctorCheck(
            "LaTeX engine",
            tectonic[0] or latexmk[0],
            tectonic[1] if tectonic[0] else latexmk[1],
            True,
        ),
        DoctorCheck("latexdiff", latexdiff[0], latexdiff[1], True),
        DoctorCheck(
            "Poppler PDF tools",
            pdftotext[0] and pdftoppm[0],
            f"pdftotext={pdftotext[1]}; pdftoppm={pdftoppm[1]}",
            True,
        ),
        DoctorCheck(
            "BibTeX/Biber backend",
            bibliography,
            "Tectonic integrated" if tectonic[0] else "external backend",
            True,
        ),
        DoctorCheck("Ruff", _tool_detail("ruff")[0], _tool_detail("ruff")[1], False),
        DoctorCheck("Mypy", _tool_detail("mypy")[0], _tool_detail("mypy")[1], False),
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
    authors_path: str | Path | None = None,
    bibliography_path: str | Path | None = None,
    custom_template: str | Path | None = None,
    engine: str = "auto",
) -> LifecycleResult:
    """Initialize and compile ``path/manuscript/initial_submission``."""
    if publisher not in PUBLISHERS:
        raise WorkflowError(f"Unsupported publisher: {publisher}")
    author_source = Path(authors_path).expanduser().resolve() if authors_path else None
    from .workspace import resources_root

    library = load_author_library(author_source or resources_root() / "authors.yaml")
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
    initialize_project(
        config,
        author_source,
        (Path(bibliography_path).expanduser().resolve() if bibliography_path else None),
        Path(custom_template).expanduser().resolve() if custom_template else None,
    )
    with temporary_run(manuscript_root) as run_dir:
        manuscript = build_clean_manuscript(config, 0, run_dir, engine)
    return LifecycleResult(
        "init",
        revision_directory_name(0),
        (Artifact("Initial manuscript", manuscript),),
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
            artifacts.extend(sorted((version / "submission" / "package").glob("*")))
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
        """Compile one clean manuscript without changing its source."""
        latest = load_project(self.root)
        selected = parse_round(round, latest.current_round)
        config = load_project(self.root, selected)
        with temporary_run(self.root, keep_temp) as run_dir:
            clean = build_clean_manuscript(config, selected, run_dir, engine)
        return LifecycleResult(
            "build",
            revision_directory_name(selected),
            (Artifact("Clean manuscript", clean),),
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
            child = start_revision(latest, target_round, run_dir, reviews_path)
            try:
                response_source = init_response(child, target_round)
                creation = finalize_revision_creation(child)
            except Exception:
                if target.exists():
                    shutil.rmtree(target)
                raise
        return LifecycleResult(
            "revision",
            revision_directory_name(target_round),
            (
                Artifact("Response source", response_source),
                Artifact("Revision creation record", creation),
            ),
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
        allow_placeholders: bool = False,
        keep_temp: bool = False,
    ) -> LifecycleResult:
        """Build all final artifacts and the version-local submission package."""
        latest = load_project(self.root)
        selected = parse_round(round, latest.current_round)
        config = load_project(self.root, selected)
        with temporary_run(self.root, keep_temp) as run_dir:
            artifacts = _prepare_submission(
                config,
                selected,
                run_dir,
                engine,
                allow_placeholders,
            )
        return LifecycleResult(
            "submission", revision_directory_name(selected), tuple(artifacts)
        )

    def build_all(
        self,
        round: str | int | None = None,
        *,
        engine: str | None = None,
        allow_placeholders: bool = False,
        keep_temp: bool = False,
    ) -> LifecycleResult:
        """Compatibility alias for :meth:`prepare_submission`."""
        return self.prepare_submission(
            round,
            engine=engine,
            allow_placeholders=allow_placeholders,
            keep_temp=keep_temp,
        )


def _compile_submission_source(
    source: Path,
    name: str,
    config: ProjectConfig,
    run_dir: Path,
    engine: str | None,
) -> Path:
    stage = run_dir / f"submission_source_{name}"
    stage.mkdir(parents=True)
    staged_source = stage / source.name
    shutil.copy2(source, staged_source)
    for sibling in source.parent.iterdir():
        if (
            sibling.is_file()
            and sibling != source
            and sibling.suffix.lower()
            in {
                ".png",
                ".jpg",
                ".jpeg",
                ".pdf",
            }
        ):
            shutil.copy2(sibling, stage / sibling.name)
    from .metadata import generate_metadata

    generate_metadata(config.project, config.round_dir(config.current_round), stage)
    result = compile_tex(
        staged_source, run_dir / f"submission_build_{name}", config, engine
    )
    target = run_dir / "package_stage" / f"{name}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result.pdf, target)
    return target


def _prepare_submission(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str | None,
    allow_placeholders: bool,
) -> list[Artifact]:
    clean = build_clean_manuscript(config, round_number, run_dir, engine)
    marked: MarkedResult | None = None
    response_pdf: Path | None = None
    if round_number > 0:
        marked = build_marked_manuscript(config, round_number, run_dir, engine)
        response_pdf = build_response(
            config,
            round_number,
            marked.locations,
            run_dir,
            engine,
            allow_placeholders,
        )
    submission = ensure_submission_workspace(config, round_number)
    stage = run_dir / "package_stage"
    stage.mkdir(parents=True, exist_ok=True)
    settings = config.metadata.submission
    if settings.cover_letter:
        _compile_submission_source(
            submission / "cover_letter.tex", "cover_letter", config, run_dir, engine
        )
    if settings.highlights:
        _compile_submission_source(
            submission / "highlights.tex", "highlights", config, run_dir, engine
        )
    if settings.graphical_abstract:
        graphical_dir = submission / "graphical_abstract"
        supplied = graphical_dir / "graphical_abstract.pdf"
        if supplied.is_file():
            shutil.copy2(supplied, stage / supplied.name)
        else:
            _compile_submission_source(
                graphical_dir / "graphical_abstract.tex",
                "graphical_abstract",
                config,
                run_dir,
                engine,
            )
    shutil.copy2(clean, stage / "manuscript.pdf")
    if marked is not None and response_pdf is not None:
        shutil.copy2(marked.pdf, stage / "marked_manuscript.pdf")
        shutil.copy2(response_pdf, stage / "response_letter.pdf")
    shutil.copy2(submission / "checklist.md", stage / "checklist.md")
    package = submission / "package"
    if package.exists():
        shutil.rmtree(package)
    shutil.copytree(stage, package)
    artifacts = [Artifact("Clean manuscript", clean)]
    if marked is not None and response_pdf is not None:
        artifacts.extend(
            [
                Artifact("Marked manuscript", marked.pdf),
                Artifact("Response letter", response_pdf),
            ]
        )
    for label, name in (
        ("Cover letter", "cover_letter.pdf"),
        ("Highlights", "highlights.pdf"),
        ("Graphical abstract", "graphical_abstract.pdf"),
        ("Submission checklist", "checklist.md"),
    ):
        path = package / name
        if path.exists():
            artifacts.append(Artifact(label, path))
    artifacts.append(Artifact("Submission package", package))
    return artifacts
