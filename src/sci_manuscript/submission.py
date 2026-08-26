"""Submission source initialization, compilation, and final package assembly."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .authors import (
    load_author_library,
    resolve_authors,
    resolve_signing_author,
)
from .compile import (
    build_clean_manuscript,
    compile_tex,
    stage_cjk_fonts,
    validate_revision_layout,
)
from .diff import MarkedResult, build_marked_manuscript
from .errors import WorkflowError
from .metadata import generate_metadata
from .response import build_response
from .review import ReviewAuditResult, parse_reviews
from .templates import render_template, resources_root, template_values
from .workspace import (
    GENERATED_SUBMISSION_PATHS,
    ProjectConfig,
    _generated_submission_paths,
    author_library_source_for_round,
    revision_directory_name,
)

GUIDANCE_USE = re.compile(r"\\guidance\s*\{")
TEMPLATE_TOKEN = re.compile(r"%%[A-Z0-9_]+%%")
PENDING_MARKER = "SCI_MANUSCRIPT_PENDING:"
REVIEW_COMPLETENESS_LINE = re.compile(
    r"(?m)^- Review completeness: \*\*(?:COMPLETE|INCOMPLETE)\*\*\.\n?"
)


@dataclass(frozen=True)
class SubmissionArtifact:
    """One user-facing artifact returned to the public API façade."""

    label: str
    path: Path


def ensure_submission_workspace(config: ProjectConfig, round_number: int) -> Path:
    """Create editable submission sources once within one revision round."""
    if round_number != config.current_round:
        raise WorkflowError("Submission config must match the selected version.")
    target = config.submission_dir(round_number)
    target.mkdir(parents=True, exist_ok=True)
    values = template_values(config)
    values["AUTHOR_METADATA_PATH"] = "author_metadata.tex"
    settings = config.metadata.submission
    resources = resources_root() / "submission"
    cover_source = target / "cover_letter_body.tex"
    legacy_cover = target / "cover_letter.tex"
    if legacy_cover.exists():
        if cover_source.exists():
            raise WorkflowError(
                "Detected a v1 cover-letter workspace with both cover_letter.tex "
                "and cover_letter_body.tex. Archive the workspace and resolve the "
                "duplicate before using the 2.0 runtime."
            )
        archive = (
            config.archive_root()
            / "migrations"
            / dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            / revision_directory_name(round_number)
            / "submission"
        )
        archive.mkdir(parents=True, exist_ok=False)
        shutil.copy2(legacy_cover, archive / legacy_cover.name)
        os.replace(legacy_cover, cover_source)
    if settings.cover_letter and not cover_source.exists():
        render_template(
            resources / f"cover_letter_body_{config.language}.tex",
            cover_source,
            values,
        )
    if settings.highlights and not (target / "highlights.tex").exists():
        render_template(resources / "highlights.tex", target / "highlights.tex", values)
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


def _compile_submission_source(
    source: Path,
    name: str,
    config: ProjectConfig,
    run_dir: Path,
    engine: str | None,
    author_library_path: Path,
) -> Path:
    stage = run_dir / f"submission_source_{name}"
    stage.mkdir(parents=True)
    if config.language == "zh":
        stage_cjk_fonts(stage)
    staged_source = stage / source.name
    shutil.copy2(source, staged_source)
    for sibling in source.parent.iterdir():
        if (
            sibling.is_file()
            and sibling != source
            and sibling.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}
        ):
            shutil.copy2(sibling, stage / sibling.name)
    generate_metadata(
        config.round_dir(config.current_round),
        stage,
        author_library_path,
    )
    result = compile_tex(
        staged_source, run_dir / f"submission_build_{name}", config, engine
    )
    target = run_dir / "package_stage" / f"{name}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result.pdf, target)
    return target


def _compile_cover_letter(
    body_source: Path,
    config: ProjectConfig,
    run_dir: Path,
    engine: str | None,
    author_library_path: Path,
) -> Path:
    """Assemble the package cover template with user-owned body content."""
    stage = run_dir / "cover_source"
    stage.mkdir(parents=True)
    if config.language == "zh":
        stage_cjk_fonts(stage)
    template_path = (
        resources_root()
        / "correspondence_templates"
        / "cover_letter"
        / f"cover_letter_{config.language}.tex"
    )
    try:
        template = template_path.read_text(encoding="utf-8")
        body = body_source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(
            f"Cannot read cover-letter template or body: {body_source}"
        ) from exc
    if template.count("%%COVER_BODY%%") != 1:
        raise WorkflowError(
            "Cover-letter template must contain one %%COVER_BODY%% token: "
            f"{template_path}"
        )
    staged_source = stage / "cover_letter.tex"
    staged_source.write_text(template.replace("%%COVER_BODY%%", body), encoding="utf-8")
    for sibling in body_source.parent.iterdir():
        if sibling.is_file() and sibling.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".pdf",
        }:
            shutil.copy2(sibling, stage / sibling.name)
    generate_metadata(
        config.round_dir(config.current_round),
        stage,
        author_library_path,
    )
    result = compile_tex(staged_source, run_dir / "cover_build", config, engine)
    target = run_dir / "package_stage" / "cover_letter.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result.pdf, target)
    return target


def _review_comments_available(config: ProjectConfig, round_number: int) -> bool:
    path = config.response_dir(round_number) / "reviewer_comments.md"
    try:
        return any(block.comments for block in parse_reviews(path))
    except WorkflowError:
        return False


def _unresolved_tokens(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read submission source: {path}") from exc
    return tuple(sorted(set(TEMPLATE_TOKEN.findall(text))))


def prepare_submission_artifacts(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str | None,
    audit: ReviewAuditResult | None,
) -> list[SubmissionArtifact]:
    """Build trusted submission artifacts and assemble the final package."""
    submission = ensure_submission_workspace(config, round_number)
    author_library_path = author_library_source_for_round(config, round_number)
    selection = resolve_authors(
        config.metadata,
        load_author_library(author_library_path),
    )
    needs_response = round_number > 0 and _review_comments_available(
        config, round_number
    )
    if config.metadata.submission.cover_letter or needs_response:
        resolve_signing_author(
            config.metadata,
            selection,
            require_explicit_multiple=True,
        )
    if config.metadata.submission.cover_letter:
        cover_source = submission / "cover_letter_body.tex"
        try:
            cover_text = cover_source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise WorkflowError(f"Cannot read cover letter: {cover_source}") from exc
        if GUIDANCE_USE.search(cover_text):
            raise WorkflowError(
                "Cover letter still contains \\guidance{...} blocks; "
                "replace or remove them before submission."
            )
        cover_unresolved = sorted(set(TEMPLATE_TOKEN.findall(cover_text)))
        if cover_unresolved:
            raise WorkflowError(
                "Cover letter still contains unresolved template placeholders: "
                + ", ".join(cover_unresolved)
            )
    settings = config.metadata.submission
    if settings.highlights:
        highlights = submission / "highlights.tex"
        highlights_text = highlights.read_text(encoding="utf-8")
        if PENDING_MARKER in highlights_text:
            raise WorkflowError(
                f"Highlights are still pending; remove the marker after editing: {highlights}"
            )
        highlights_unresolved = _unresolved_tokens(highlights)
        if highlights_unresolved:
            raise WorkflowError(
                "Highlights contain unresolved placeholders: "
                + ", ".join(highlights_unresolved)
            )
    if settings.graphical_abstract:
        graphical = submission / "graphical_abstract"
        final_pdf = graphical / "graphical_abstract.pdf"
        source = graphical / "graphical_abstract.tex"
        if not final_pdf.is_file() and (
            not source.is_file() or PENDING_MARKER in source.read_text(encoding="utf-8")
        ):
            raise WorkflowError(
                "Graphical abstract is still pending; provide a final PDF or remove "
                f"the marker after editing: {source}"
            )
        if not final_pdf.is_file():
            graphical_unresolved = _unresolved_tokens(source)
            if graphical_unresolved:
                raise WorkflowError(
                    "Graphical abstract contains unresolved placeholders: "
                    + ", ".join(graphical_unresolved)
                )
    clean = build_clean_manuscript(config, round_number, run_dir, engine)
    marked: MarkedResult | None = None
    response_pdf: Path | None = None
    layout_report: Path | None = None
    if round_number > 0:
        marked = build_marked_manuscript(config, round_number, run_dir, engine)
        layout_report = validate_revision_layout(
            (run_dir / "clean_build" / "manuscript.compiler.log").read_text(
                encoding="utf-8"
            ),
            (run_dir / "marked_build" / "manuscript_marked.compiler.log").read_text(
                encoding="utf-8"
            ),
            run_dir / "revision_layout_qa.txt",
        )
        responses_trusted = audit is None or not any(
            issue.code == "RESPONSES_INVALID" for issue in audit.issues
        )
        if _review_comments_available(config, round_number) and responses_trusted:
            response_pdf = build_response(
                config,
                round_number,
                marked.locations,
                run_dir,
                engine,
            )
    stage = run_dir / "package_stage"
    stage.mkdir(parents=True, exist_ok=True)
    if settings.cover_letter:
        _compile_cover_letter(
            submission / "cover_letter_body.tex",
            config,
            run_dir,
            engine,
            author_library_path,
        )
    if settings.highlights:
        _compile_submission_source(
            submission / "highlights.tex",
            "highlights",
            config,
            run_dir,
            engine,
            author_library_path,
        )
    if settings.graphical_abstract:
        graphical_dir = submission / "graphical_abstract"
        supplied = graphical_dir / "graphical_abstract.pdf"
        staged_graphical = stage / "graphical_abstract" / "graphical_abstract.pdf"
        staged_graphical.parent.mkdir(parents=True, exist_ok=True)
        registered_generated = _generated_submission_paths(
            config.round_dir(round_number)
        )
        supplied_is_user_source = (
            supplied.is_file()
            and Path("graphical_abstract/graphical_abstract.pdf")
            not in registered_generated
        )
        if supplied_is_user_source:
            shutil.copy2(supplied, staged_graphical)
        else:
            compiled_graphical = _compile_submission_source(
                graphical_dir / "graphical_abstract.tex",
                "graphical_abstract",
                config,
                run_dir,
                engine,
                author_library_path,
            )
            shutil.move(compiled_graphical, staged_graphical)
    shutil.copy2(clean, stage / "manuscript.pdf")
    if marked is not None:
        shutil.copy2(marked.pdf, stage / "marked_manuscript.pdf")
    if response_pdf is not None:
        shutil.copy2(response_pdf, stage / "response_letter.pdf")
    checklist = stage / "checklist.md"
    checklist_text = (submission / "checklist.md").read_text(encoding="utf-8")
    checklist_text = REVIEW_COMPLETENESS_LINE.sub("", checklist_text).rstrip()
    if audit is not None:
        state = "COMPLETE" if audit.is_complete else "INCOMPLETE"
        checklist_text += f"\n\n- Review completeness: **{state}**."
    checklist.write_text(checklist_text + "\n", encoding="utf-8")
    generated_paths = set(GENERATED_SUBMISSION_PATHS)
    if settings.graphical_abstract and not supplied_is_user_source:
        generated_paths.add(Path("graphical_abstract/graphical_abstract.pdf"))
    _publish_submission_stage(
        config,
        round_number,
        stage,
        generated_paths,
        run_dir,
    )
    artifacts = [SubmissionArtifact("Clean manuscript", clean)]
    if marked is not None:
        if layout_report is None:
            raise WorkflowError("Revision layout QA report was not generated.")
        artifacts.append(SubmissionArtifact("Marked manuscript", marked.pdf))
    if response_pdf is not None:
        artifacts.append(SubmissionArtifact("Response letter", response_pdf))
    for label, name in (
        ("Cover letter", "cover_letter.pdf"),
        ("Highlights", "highlights.pdf"),
        ("Submission checklist", "checklist.md"),
    ):
        path = submission / name
        if path.exists():
            artifacts.append(SubmissionArtifact(label, path))
    graphical_pdf = submission / "graphical_abstract" / "graphical_abstract.pdf"
    if graphical_pdf.is_file():
        artifacts.append(SubmissionArtifact("Graphical abstract", graphical_pdf))
    artifacts.append(SubmissionArtifact("Submission files", submission))
    return artifacts


def _publish_submission_stage(
    config: ProjectConfig,
    round_number: int,
    stage: Path,
    generated_paths: set[Path],
    run_dir: Path,
) -> None:
    """Atomically install generated files and restore every old file on failure."""
    submission = config.submission_dir(round_number)
    rollback = run_dir / "publication_rollback"
    rollback.mkdir(parents=True, exist_ok=True)
    old_registry = config.generated_artifacts_path(round_number)
    registry_backup = rollback / "generated_artifacts.yaml"
    if old_registry.is_file():
        shutil.copy2(old_registry, registry_backup)
    backups: dict[Path, Path] = {}
    installed: list[Path] = []
    removed: list[Path] = []
    temporary_paths: set[Path] = set()
    try:
        old_generated = _generated_submission_paths(config.round_dir(round_number))
        staged_paths = sorted(
            (path.relative_to(stage) for path in stage.rglob("*") if path.is_file()),
            key=lambda item: item.as_posix(),
        )
        for relative in staged_paths:
            staged = stage / relative
            target = submission / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file():
                backup = rollback / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                backups[target] = backup
            temporary = target.with_name(f".{target.name}.new")
            temporary_paths.add(temporary)
            shutil.copy2(staged, temporary)
            os.replace(temporary, target)
            temporary_paths.discard(temporary)
            installed.append(target)
        managed = set(GENERATED_SUBMISSION_PATHS) | old_generated | generated_paths
        for relative in sorted(
            managed - set(staged_paths), key=lambda item: item.as_posix()
        ):
            target = submission / relative
            if not target.is_file():
                continue
            backup = rollback / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            backups[target] = backup
            target.unlink()
            removed.append(target)
        owned = {
            relative.as_posix(): hashlib.sha256(
                (submission / relative).read_bytes()
            ).hexdigest()
            for relative in sorted(generated_paths, key=lambda item: item.as_posix())
            if (submission / relative).is_file()
        }
        registry = old_registry.with_suffix(".yaml.new")
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(
            yaml.safe_dump(
                {
                    "schema": "sci-manuscript-generated-artifacts/v1",
                    "paths": list(owned),
                    "sha256": owned,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        os.replace(registry, old_registry)
    except Exception:
        for temporary in temporary_paths:
            if temporary.is_file():
                temporary.unlink()
        registry_temporary = old_registry.with_suffix(".yaml.new")
        if registry_temporary.is_file():
            registry_temporary.unlink()
        for target in reversed(installed):
            target_backup = backups.get(target)
            if target_backup is not None:
                shutil.copy2(target_backup, target)
            elif target.exists():
                target.unlink()
        for target in removed:
            backup = backups[target]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        if registry_backup.is_file():
            old_registry.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(registry_backup, old_registry)
        elif old_registry.exists():
            old_registry.unlink()
        raise
