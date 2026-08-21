"""Version-local submission packaging."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..exceptions import WorkflowError
from ..latex.compile import compile_tex
from ..results import SubmissionResult
from .build import _build_lifecycle, _compile_submission_source
from .project import ProjectConfig, ensure_submission_workspace

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


def rollback_inspect(project: str | Path) -> RollbackResult:
    """Compare the latest revision against its parent at the user-source layer."""
    root = normalize_project(project)
    _require_project(root)
    latest = load_project(root)
    if latest.current_round == 0:
        raise WorkflowError("initial_submission (r00) cannot be rolled back.")
    parent = latest.metadata.parent_round
    assert parent is not None
    version_dir = actual_round_directory(root, latest.current_round)
    parent_dir = actual_round_directory(root, parent)
    latest_sources = runtime_workspace.user_source_hashes(
        version_dir, normalize_tex=True
    )
    parent_sources = runtime_workspace.user_source_hashes(
        parent_dir, normalize_tex=True
    )
    changed: list[str] = []
    for relative, digest in latest_sources.items():
        if relative == "manuscript.yaml":
            continue  # revision identity is rewritten automatically
        if relative.startswith("response/"):
            if relative.endswith("response_letter.tex"):
                # An untouched scaffold still contains pending placeholders,
                # whether or not the parent already carries a filled letter.
                path = version_dir / relative
                if "\\ResponsePending" not in path.read_text(encoding="utf-8"):
                    changed.append(relative)
            continue  # reviewer-comments copies are generated input, not edits
        if relative in parent_sources:
            if parent_sources[relative] != digest:
                changed.append(relative)
            continue
        changed.append(relative)
    missing = [
        relative
        for relative in parent_sources
        if relative not in latest_sources and relative != "manuscript.yaml"
    ]
    changed.extend(missing)
    return RollbackResult(
        project=root,
        version=round_directory_name(latest.current_round),
        parent=round_directory_name(parent),
        changed_files=tuple(sorted(changed)),
    )


def remove_revision(project: str | Path) -> None:
    """Delete the latest revision directory (caller must have confirmed)."""
    root = normalize_project(project)
    inspection = rollback_inspect(root)
    if inspection.changed_files:
        raise WorkflowError("Rollback refused; user source modifications detected.")
    latest = load_project(root)
    target = actual_round_directory(root, latest.current_round)
    if target.name == "initial_submission":
        raise WorkflowError("initial_submission (r00) cannot be rolled back.")
    shutil.rmtree(target)


def _rewrite_revision_identity(
    target: Path,
    round_number: int,
    parent_round: int | None,
) -> None:
    """Rewrite name/parent/round inside the revision section, preserving prose."""
    lines = target.read_text(encoding="utf-8").split("\n")
    in_revision = False
    for index, line in enumerate(lines):
        if line.rstrip().startswith("revision:"):
            in_revision = True
            continue
        if in_revision:
            if line and not line.startswith("  "):
                break  # left the revision section
            if line.startswith("  name:"):
                lines[index] = f"  name: {round_directory_name(round_number)}"
            elif line.startswith("  parent:"):
                parent_value = (
                    "null"
                    if parent_round is None
                    else round_directory_name(parent_round)
                )
                lines[index] = f"  parent: {parent_value}"
            elif line.startswith("  round:"):
                lines[index] = f"  round: {round_name(round_number)}"
    target.write_text("\n".join(lines), encoding="utf-8")
    loaded = load_manuscript(target)
    if loaded.round_number != round_number:
        raise WorkflowError(
            f"Revision identity rewrite failed for {target}; refusing to continue."
        )


def reindex_plan(project: str | Path) -> ReindexResult:
    """Plan renumbering of a broken or legacy round sequence (read-only)."""
    root = normalize_project(project)
    _require_project(root)
    numbers = runtime_workspace.scan_round_directories(root)
    renames: list[tuple[str, str]] = []
    parent_updates: list[tuple[str, str, str]] = []
    for index, number in enumerate(numbers):
        source = actual_round_directory(root, number).name
        target = round_directory_name(index)
        if source != target:
            renames.append((source, target))
        if number > 0:
            parent_updates.append((source, round_name(number), round_name(index)))
    return ReindexResult(
        project=root,
        applied=False,
        renames=tuple(renames),
        parent_updates=tuple(parent_updates),
        invalidated=(),
    )


def _invalidated_artifacts(root: Path) -> list[str]:
    """Return generated artifact paths invalidated by a reindex (relative names)."""
    invalidated: list[str] = []
    for number in runtime_workspace.scan_round_directories(root):
        version = actual_round_directory(root, number)
        for pattern in ("output/*.pdf", "submission/package/*"):
            for path in sorted(version.glob(pattern)):
                if path.is_file():
                    invalidated.append(path.relative_to(root).as_posix())
        package = version / "submission" / "package"
        if package.is_dir():
            invalidated.append(package.relative_to(root).as_posix())
    staging = root / "tmp"
    if staging.is_dir():
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                invalidated.append(path.relative_to(root).as_posix())
    return invalidated


def reindex_execute(project: str | Path) -> ReindexResult:
    """Transactionally renumber the round sequence and invalidate generated PDFs."""
    root = normalize_project(project)
    plan = reindex_plan(root)
    if not plan.renames:
        return ReindexResult(
            project=root,
            applied=False,
            renames=(),
            parent_updates=plan.parent_updates,
            invalidated=(),
            status="already_ordered",
        )
    numbers = runtime_workspace.scan_round_directories(root)
    staging = root / "tmp" / f"reindex_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True)
    moved: list[tuple[Path, Path]] = []
    placed: list[tuple[Path, Path]] = []
    original_metadata: dict[str, str] = {}
    source_dirs = [actual_round_directory(root, number) for number in numbers]
    try:
        for index, source_dir in enumerate(source_dirs):
            staged = staging / f"{index:02d}_{source_dir.name}"
            shutil.move(str(source_dir), staged)
            moved.append((staged, source_dir))
        for index, source_dir in enumerate(source_dirs):
            staged = staging / f"{index:02d}_{source_dir.name}"
            target = root / round_directory_name(index)
            shutil.move(str(staged), target)
            placed.append((target, source_dir))
        for index, _ in enumerate(numbers):
            if index == 0:
                continue
            target = root / round_directory_name(index)
            yaml_path = target / "manuscript.yaml"
            relative = yaml_path.relative_to(root).as_posix()
            original_metadata[relative] = yaml_path.read_text(encoding="utf-8")
            _rewrite_revision_identity(yaml_path, index, index - 1)
    except (OSError, WorkflowError):
        for relative, original_text in original_metadata.items():
            (root / relative).write_text(original_text, encoding="utf-8")
        for target, original in reversed(placed):
            if target.exists():
                shutil.move(str(target), original)
        for staged, original in reversed(moved):
            if staged.exists():
                shutil.move(str(staged), original)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    invalidated = _invalidated_artifacts(root)
    for name in invalidated:
        path = root / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)
    return ReindexResult(
        project=root,
        applied=True,
        renames=plan.renames,
        parent_updates=plan.parent_updates,
        invalidated=tuple(invalidated),
        status="reindexed",
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


def _legacy_wrapper_hash(text: str) -> str:
    normalized = _LEGACY_ROOT_LINE.sub(
        '_SKILL_ROOT_HINT = Path("<GENERATED_SKILL_ROOT>")',
        text,
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def _atomic_infrastructure_replace(
    changes: tuple[tuple[Path, str, int], ...],
    stage: Path,
    project: Path,
    expected_source_hashes: dict[str, str],
) -> None:
    staged: list[tuple[Path, Path, Path]] = []
    for index, (target, text, mode) in enumerate(changes):
        replacement = stage / "new" / f"{index}_{target.name}"
        backup = stage / "original" / f"{index}_{target.name}"
        replacement.parent.mkdir(parents=True, exist_ok=True)
        backup.parent.mkdir(parents=True, exist_ok=True)
        replacement.write_text(text, encoding="utf-8")
        replacement.chmod(mode)
        shutil.copy2(target, backup)
        staged.append((target, replacement, backup))
    replaced: list[tuple[Path, Path]] = []
    try:
        for target, replacement, backup in staged:
            os.replace(replacement, target)
            replaced.append((target, backup))
        if scientific_source_hashes(project) != expected_source_hashes:
            raise WorkflowError(
                "Scientific manuscript source changed during upgrade; migration failed."
            )
    except Exception:
        for target, backup in reversed(replaced):
            rollback = stage / "rollback" / target.name
            rollback.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, rollback)
            os.replace(rollback, target)
        raise


def upgrade_project(project: str | Path) -> UpgradeResult:
    """Safely migrate recognized generated infrastructure to format version 1."""
    root = normalize_project(project)
    _require_project(root)
    latest = load_project(root)
    configs = tuple(
        load_project(root, number) for number in range(latest.current_round + 1)
    )
    formats = {config.metadata.format_version for config in configs}
    if len(formats) != 1:
        raise WorkflowError(
            "Project versions declare inconsistent format versions; refusing migration."
        )
    from_format = formats.pop()
    if from_format > CURRENT_PROJECT_FORMAT:
        raise WorkflowError(
            f"Project format {from_format} is newer than supported format "
            f"{CURRENT_PROJECT_FORMAT}; refusing to downgrade."
        )

    wrapper = root / "run.py"
    if not wrapper.is_file():
        raise WorkflowError(f"Project entry point is missing: {wrapper}")
    current_wrapper = read_resource_text("project_run.py")
    wrapper_text = wrapper.read_text(encoding="utf-8")
    wrapper_current = wrapper_text == current_wrapper
    if (
        not wrapper_current
        and _legacy_wrapper_hash(wrapper_text) not in _LEGACY_WRAPPER_HASHES
    ):
        raise WorkflowError(
            "Existing run.py is not a recognized generated wrapper; refusing to "
            "overwrite."
        )

    style_target = root / "references" / "revision_style.tex"
    current_style = read_resource_text("revision_style.tex")
    style_text = (
        style_target.read_text(encoding="utf-8") if style_target.is_file() else None
    )
    style_current = style_text == current_style
    style_legacy = (
        style_text is not None
        and hashlib.sha256(style_target.read_bytes()).hexdigest()
        in _LEGACY_REVISION_STYLE_HASHES
    )
    if style_text is not None and not style_current and not style_legacy:
        raise WorkflowError(
            "Existing references/revision_style.tex is user-customized; refusing "
            "to overwrite it. Copy the packaged style manually to adopt the "
            "current appearance."
        )

    numbering = reindex_plan(root)
    numbering_renamed = bool(numbering.renames)
    if numbering_renamed:
        reindex_execute(root)  # transactional legacy-directory renumbering

    if from_format == CURRENT_PROJECT_FORMAT and wrapper_current and style_current:
        if not numbering_renamed:
            return UpgradeResult(
                project=root,
                status="already_current",
                from_format=from_format,
                to_format=CURRENT_PROJECT_FORMAT,
                artifacts=(),
            )
        return UpgradeResult(
            project=root,
            status="upgraded",
            from_format=from_format,
            to_format=CURRENT_PROJECT_FORMAT,
            artifacts=(),
        )

    before = scientific_source_hashes(root)
    version = package_version()
    changes: list[tuple[Path, str, int]] = []
    if not wrapper_current:
        changes.append((wrapper, current_wrapper, 0o755))
    if not style_current:
        changes.append(
            (style_target, current_style, style_target.stat().st_mode & 0o777)
        )
    for config in configs:
        target = config.round_dir(config.current_round) / "manuscript.yaml"
        if config.metadata.format_version == CURRENT_PROJECT_FORMAT:
            continue
        metadata = replace(
            config.metadata,
            format_version=CURRENT_PROJECT_FORMAT,
            created_with=version,
        )
        rendered = render_manuscript(metadata)
        marker = "# =====================================\n# Manuscript"
        workflow_header, separator, _ = rendered.partition(marker)
        if not separator:
            raise WorkflowError("Cannot render the workflow format metadata.")
        original = target.read_text(encoding="utf-8")
        updated = workflow_header + original.lstrip("\n")
        changes.append((target, updated, target.stat().st_mode & 0o777))

    with temporary_run(root, keep=False) as run_dir:
        _atomic_infrastructure_replace(
            tuple(changes),
            run_dir / "upgrade",
            root,
            before,
        )
    return UpgradeResult(
        project=root,
        status="upgraded",
        from_format=from_format,
        to_format=CURRENT_PROJECT_FORMAT,
        artifacts=tuple(
            Artifact("Upgraded infrastructure", item[0]) for item in changes
        ),
    )


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
