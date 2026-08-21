"""Single internal orchestration layer shared by the public API and CLI."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _SKILL_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import workspace as runtime_workspace  # noqa: E402
from compile import build_clean_manuscript, compile_tex  # noqa: E402
from diff import MarkedResult, build_marked_manuscript  # noqa: E402
from metadata import (  # noqa: E402
    PUBLISHER_TEMPLATES,
    ManuscriptMetadata,
    MetadataError,
    SubmissionSettings,
    generate_author_metadata,
    load_author_library,
)
from response import build_response, init_response, parse_reviews  # noqa: E402
from workspace import (  # noqa: E402
    ProjectConfig,
    WorkflowError,
    check_citations,
    ensure_submission_workspace,
    initialize_project,
    is_initialized,
    load_project,
    normalize_project,
    parse_round,
    round_directory_name,
    sync_bibliography,
    temporary_run,
)

from .results import (  # noqa: E402
    Artifact,
    BibliographySyncResult,
    BuildResult,
    CheckResult,
    InitializationResult,
    RevisionResult,
    StatusResult,
    SubmissionResult,
    ZoteroSetupResult,
)


def _require_project(project: Path) -> None:
    if not is_initialized(project):
        raise WorkflowError(
            f"Project is not initialized: {project}. Run the init command first."
        )


def _selected_project(
    project: str | Path,
    selected_round: str | int | None,
) -> tuple[Path, ProjectConfig, int]:
    root = normalize_project(project)
    _require_project(root)
    latest = load_project(root)
    round_number = parse_round(selected_round, latest.current_round)
    return root, load_project(root, round_number), round_number


def _new_config(
    project: Path,
    title: str,
    journal: str,
    publisher: str,
    language: str,
    authors: str | Path | None,
    selected_authors: Sequence[str] | None,
    article_type: str,
    engine: str,
) -> ProjectConfig:
    if publisher not in PUBLISHER_TEMPLATES:
        raise MetadataError(f"Unsupported publisher: {publisher}")
    if language not in {"en", "zh"}:
        raise MetadataError("Language must be en or zh.")
    author_source = (
        Path(authors).expanduser().resolve()
        if authors is not None
        else _SKILL_ROOT / "assets" / "authors.yaml"
    )
    author_library = load_author_library(author_source)
    selected = (
        tuple(selected_authors)
        if selected_authors is not None
        else tuple(author_library.authors)
    )
    missing = [name for name in selected if name not in author_library.authors]
    if missing:
        raise MetadataError(
            "Selected authors are missing from authors.yaml: " + ", ".join(missing)
        )
    first_authors = (
        tuple(
            name
            for name in selected
            if author_library.authors[name].role == "first_author"
        )
        or selected[:1]
    )
    corresponding_authors = tuple(
        name
        for name in selected
        if author_library.authors[name].role == "corresponding_author"
    )
    if not corresponding_authors:
        raise MetadataError(
            "Selected authors must include at least one corresponding_author."
        )
    ordinary_authors = tuple(
        name
        for name in selected
        if name not in {*first_authors, *corresponding_authors}
    )
    manuscript = ManuscriptMetadata(
        title=title,
        article_type=article_type,
        language=language,
        journal_name=journal,
        publisher=publisher,
        journal_template=PUBLISHER_TEMPLATES[publisher],
        round_number=0,
        parent_round=None,
        submission=SubmissionSettings(True, True, True),
        first_authors=first_authors,
        corresponding_authors=corresponding_authors,
        authors=ordinary_authors,
    )
    return ProjectConfig(project, manuscript, engine)


def initialize_manuscript(
    *,
    path: str | Path,
    title: str,
    journal: str,
    publisher: str,
    language: str,
    authors: str | Path | None,
    bib: str | Path | None,
    selected_authors: Sequence[str] | None,
    article_type: str,
    engine: str,
    keep_temp: bool,
) -> InitializationResult:
    """Initialize one project and compile its initial clean manuscript."""
    project = normalize_project(path)
    authors_source = Path(authors).expanduser().resolve() if authors else None
    bibliography_source = Path(bib).expanduser().resolve() if bib else None
    config = initialize_project(
        _new_config(
            project,
            title,
            journal,
            publisher,
            language,
            authors,
            selected_authors,
            article_type,
            engine,
        ),
        authors_source,
        bibliography_source,
    )
    with temporary_run(project, keep_temp) as run_dir:
        generate_author_metadata(config.project, config.round_dir(0))
        manuscript = build_clean_manuscript(config, 0, run_dir, engine)
    return InitializationResult(
        project=project,
        version=round_directory_name(0),
        artifacts=(Artifact("Initial manuscript", manuscript),),
        authors_need_review=authors is None,
        bibliography_needs_configuration=bib is None,
    )


def build(
    project: str | Path,
    selected_round: str | int | None,
    engine: str,
    keep_temp: bool,
) -> BuildResult:
    """Compile one clean manuscript through the deterministic runtime."""
    root, config, round_number = _selected_project(project, selected_round)
    with temporary_run(root, keep_temp) as run_dir:
        generate_author_metadata(root, config.round_dir(round_number))
        clean = build_clean_manuscript(config, round_number, run_dir, engine)
    return BuildResult(
        project=root,
        version=round_directory_name(round_number),
        artifacts=(Artifact("Clean manuscript", clean),),
    )


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


def start_revision(
    project: str | Path,
    reviews: str | Path | None,
    selected_round: str | int | None,
    keep_temp: bool,
) -> RevisionResult:
    """Create only the next adjacent workspace and response infrastructure."""
    root = normalize_project(project)
    _require_project(root)
    latest = load_project(root)
    target = parse_round(selected_round, latest.current_round + 1)
    review_source = Path(reviews).expanduser().resolve() if reviews else None
    if review_source is not None:
        parse_reviews(review_source)
    with temporary_run(root, keep_temp) as run_dir:
        config = runtime_workspace.start_revision(latest, target, run_dir)
        local_reviews = config.round_dir(target) / "response" / "reviewer_comments.md"
        response_source = init_response(
            config,
            target,
            review_source or local_reviews,
        )
    return RevisionResult(
        project=root,
        version=round_directory_name(target),
        parent=round_directory_name(target - 1),
        artifacts=(Artifact("Response source", response_source),),
    )


def _build_lifecycle(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str,
    allow_placeholders: bool,
) -> tuple[Path, MarkedResult | None, Path | None]:
    if round_number != config.current_round:
        raise WorkflowError("Build config must match the selected version.")
    generate_author_metadata(config.project, config.round_dir(round_number))
    clean = build_clean_manuscript(config, round_number, run_dir, engine)
    if round_number == 0:
        return clean, None, None
    marked = build_marked_manuscript(config, round_number, run_dir, engine)
    response_source = (
        config.round_dir(round_number) / "response" / "response_letter.tex"
    )
    if not response_source.exists():
        raise WorkflowError(f"Response source is missing: {response_source}")
    response_pdf = build_response(
        config,
        round_number,
        marked.locations,
        run_dir,
        engine,
        allow_placeholders,
    )
    return clean, marked, response_pdf


def _compile_submission_source(
    source: Path,
    name: str,
    config: ProjectConfig,
    run_dir: Path,
    engine: str,
) -> Path:
    result = compile_tex(source, run_dir / f"submission_{name}", config, engine)
    target = run_dir / "package_stage" / f"{name}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result.pdf, target)
    return target


def _prepare_submission(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str,
    allow_placeholders: bool,
) -> tuple[Artifact, ...]:
    clean, marked, response_pdf = _build_lifecycle(
        config,
        round_number,
        run_dir,
        engine,
        allow_placeholders,
    )
    submission = ensure_submission_workspace(config, round_number)
    stage = run_dir / "package_stage"
    stage.mkdir(parents=True, exist_ok=True)
    settings = config.metadata.submission
    optional_artifacts: list[Path] = []
    if settings.cover_letter:
        optional_artifacts.append(
            _compile_submission_source(
                submission / "cover_letter.tex",
                "cover_letter",
                config,
                run_dir,
                engine,
            )
        )
    if settings.highlights:
        optional_artifacts.append(
            _compile_submission_source(
                submission / "highlights.tex",
                "highlights",
                config,
                run_dir,
                engine,
            )
        )
    if settings.graphical_abstract:
        graphical_directory = submission / "graphical_abstract"
        supplied_graphical = graphical_directory / "graphical_abstract.pdf"
        if supplied_graphical.exists():
            graphical = stage / "graphical_abstract.pdf"
            shutil.copy2(supplied_graphical, graphical)
        else:
            graphical = _compile_submission_source(
                graphical_directory / "graphical_abstract.tex",
                "graphical_abstract",
                config,
                run_dir,
                engine,
            )
        optional_artifacts.append(graphical)
    shutil.copy2(clean, stage / "manuscript.pdf")
    if marked is not None:
        shutil.copy2(marked.pdf, stage / "marked_manuscript.pdf")
        if response_pdf is None:
            raise WorkflowError("A revision package requires response_letter.pdf.")
        shutil.copy2(response_pdf, stage / "response_letter.pdf")
    shutil.copy2(submission / "checklist.md", stage / "checklist.md")
    for artifact in optional_artifacts:
        if not artifact.exists():
            raise WorkflowError(f"Submission artifact is missing: {artifact}")
    package = submission / "package"
    package.mkdir(exist_ok=True)
    known = {
        "manuscript.pdf",
        "marked_manuscript.pdf",
        "response_letter.pdf",
        "cover_letter.pdf",
        "highlights.pdf",
        "graphical_abstract.pdf",
        "checklist.md",
    }
    for name in known:
        path = package / name
        if path.exists():
            path.unlink()
    for artifact in stage.iterdir():
        shutil.copy2(artifact, package / artifact.name)
    generated = [Artifact("Clean manuscript", clean)]
    if marked is not None and response_pdf is not None:
        generated.extend(
            (
                Artifact("Marked manuscript", marked.pdf),
                Artifact("Response letter", response_pdf),
            )
        )
    package_labels = {
        "manuscript.pdf": "Packaged manuscript",
        "marked_manuscript.pdf": "Packaged marked manuscript",
        "response_letter.pdf": "Packaged response letter",
        "cover_letter.pdf": "Cover letter",
        "highlights.pdf": "Highlights",
        "graphical_abstract.pdf": "Graphical abstract",
        "checklist.md": "Submission checklist",
    }
    for name, label in package_labels.items():
        artifact = package / name
        if artifact.exists():
            generated.append(Artifact(label, artifact))
    generated.append(Artifact("Submission package", package))
    return tuple(generated)


def prepare_submission(
    project: str | Path,
    selected_round: str | int | None,
    engine: str,
    allow_placeholders: bool,
    keep_temp: bool,
) -> SubmissionResult:
    """Build the version lifecycle and publish a complete submission package."""
    root, config, round_number = _selected_project(project, selected_round)
    with temporary_run(root, keep_temp) as run_dir:
        artifacts = _prepare_submission(
            config,
            round_number,
            run_dir,
            engine,
            allow_placeholders,
        )
    return SubmissionResult(
        project=root,
        version=round_directory_name(round_number),
        artifacts=artifacts,
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
        version=round_directory_name(latest.current_round),
        round_number=latest.current_round,
        parent=round_directory_name(parent) if parent is not None else None,
        authors=latest.metadata.author_names,
        publisher=latest.metadata.publisher,
        journal=latest.journal,
        artifacts=tuple(artifacts),
    )


def setup_zotero(project: str | Path) -> ZoteroSetupResult:
    """Prepare the shared bibliography target and non-invasive setup guide."""
    root = normalize_project(project)
    _require_project(root)
    bibliography, guide = runtime_workspace.setup_zotero(root)
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
