"""Submission source initialization, compilation, and final package assembly."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .authors import (
    load_author_library,
    resolve_authors,
    resolve_signing_author,
    resolve_workspace_author_library_path,
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
from .workspace import ProjectConfig

GUIDANCE_USE = re.compile(r"\\guidance\s*\{")
TEMPLATE_TOKEN = re.compile(r"%%[A-Z0-9_]+%%")
REVIEW_COMPLETENESS_LINE = re.compile(
    r"(?m)^- Review completeness: \*\*(?:COMPLETE|INCOMPLETE)\*\*\.\n?"
)
GENERATED_SUBMISSION_FILES = (
    "manuscript.pdf",
    "marked_manuscript.pdf",
    "response_letter.pdf",
    "cover_letter.pdf",
    "highlights.pdf",
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
    cover_source = target / "cover_letter.tex"
    legacy_cover_source = target / "cover_letter_body.tex"
    if settings.cover_letter and not cover_source.exists():
        if legacy_cover_source.is_file():
            shutil.copy2(legacy_cover_source, cover_source)
        else:
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
    generate_metadata(config.project, config.round_dir(config.current_round), stage)
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
    generate_metadata(config.project, config.round_dir(config.current_round), stage)
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


def prepare_submission_artifacts(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str | None,
    allow_placeholders: bool,
    audit: ReviewAuditResult | None,
) -> list[SubmissionArtifact]:
    """Build trusted submission artifacts and assemble the final package."""
    del allow_placeholders  # Retained for the released public API compatibility.
    submission = ensure_submission_workspace(config, round_number)
    selection = resolve_authors(
        config.metadata,
        load_author_library(resolve_workspace_author_library_path(config.project)),
    )
    resolve_signing_author(
        config.metadata,
        selection,
        require_explicit_multiple=True,
    )
    if config.metadata.submission.cover_letter:
        cover_source = submission / "cover_letter.tex"
        try:
            cover_text = cover_source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise WorkflowError(f"Cannot read cover letter: {cover_source}") from exc
        if GUIDANCE_USE.search(cover_text):
            raise WorkflowError(
                "Cover letter still contains \\guidance{...} blocks; "
                "replace or remove them before submission."
            )
        unresolved = sorted(set(TEMPLATE_TOKEN.findall(cover_text)))
        if unresolved:
            raise WorkflowError(
                "Cover letter still contains unresolved template placeholders: "
                + ", ".join(unresolved)
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
                True,
            )
    stage = run_dir / "package_stage"
    stage.mkdir(parents=True, exist_ok=True)
    settings = config.metadata.submission
    if settings.cover_letter:
        _compile_cover_letter(submission / "cover_letter.tex", config, run_dir, engine)
    if settings.highlights:
        _compile_submission_source(
            submission / "highlights.tex", "highlights", config, run_dir, engine
        )
    if settings.graphical_abstract:
        graphical_dir = submission / "graphical_abstract"
        supplied = graphical_dir / "graphical_abstract.pdf"
        staged_graphical = stage / "graphical_abstract" / "graphical_abstract.pdf"
        staged_graphical.parent.mkdir(parents=True, exist_ok=True)
        if supplied.is_file():
            shutil.copy2(supplied, staged_graphical)
        else:
            compiled_graphical = _compile_submission_source(
                graphical_dir / "graphical_abstract.tex",
                "graphical_abstract",
                config,
                run_dir,
                engine,
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
    legacy_package = submission / "package"
    if legacy_package.exists():
        shutil.rmtree(legacy_package)
    for name in GENERATED_SUBMISSION_FILES:
        generated = submission / name
        if generated.is_file():
            generated.unlink()
    for generated in stage.iterdir():
        target = submission / generated.name
        if generated.is_dir():
            shutil.copytree(generated, target, dirs_exist_ok=True)
        else:
            shutil.copy2(generated, target)
    artifacts = [SubmissionArtifact("Clean manuscript", clean)]
    if marked is not None:
        if layout_report is None:
            raise WorkflowError("Revision layout QA report was not generated.")
        legacy_layout_report = (
            config.output_dir(round_number) / "revision_layout_qa.txt"
        )
        if legacy_layout_report.is_file():
            legacy_layout_report.unlink()
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
