"""Reviewer comment parsing, provenance validation, and response compilation."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .compile import compile_tex
from .metadata import generate_metadata, round_name
from .workspace import ProjectConfig, WorkflowError, resources_root

REVIEW_ID = re.compile(r"^(?:E|[1-9]\d*)-[1-9]\d*$")
REVIEWER_HEADING = re.compile(r"^#\s*Reviewer\s*#?\s*([1-9]\d*)\s*$", re.I)
EDITOR_HEADING = re.compile(r"^#\s*Editor\s*$", re.I)
EXPLICIT_COMMENT = re.compile(
    r"^##\s*((?:E|[1-9]\d*)-[1-9]\d*)\s*"
    r"(?:\|\s*|\[)(response_only|manuscript_revised)\]?\s*$",
    re.I,
)
LEGACY_COMMENT = re.compile(r"^\s*([1-9]\d*)\.?\s+(.*)$")
PENDING_RESPONSE = re.compile(r"\\ResponsePending\{([^}]+)\}")
LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")
REVIEW_MACRO = re.compile(r"\\review\s*\{([^}]+)\}")


def is_review_id(value: str) -> bool:
    """Return whether a single reviewer/editor ID is valid."""
    return REVIEW_ID.fullmatch(value.strip()) is not None


def validate_review_id_list(value: str) -> tuple[str, ...]:
    """Validate a comma-separated review provenance list."""
    ids = tuple(item.strip() for item in value.split(","))
    if not ids or any(not is_review_id(item) for item in ids):
        raise WorkflowError(
            f"Invalid review ID list {value!r}; use E-1, 1-1, or comma-separated IDs."
        )
    if len(ids) != len(set(ids)):
        raise WorkflowError(f"Review ID list contains duplicates: {value!r}")
    return ids


@dataclass(frozen=True)
class ReviewComment:
    """One explicitly identified reviewer or editor comment."""

    review_id: str
    status: str
    paragraphs: tuple[str, ...]

    @property
    def text(self) -> str:
        """Return paragraph-preserving plain text."""
        return "\n\n".join(self.paragraphs)


@dataclass(frozen=True)
class ReviewBlock:
    """One Editor or Reviewer block."""

    title: str
    prefix: str
    general_paragraphs: tuple[str, ...]
    comments: tuple[ReviewComment, ...]


def _paragraphs(lines: list[str]) -> tuple[str, ...]:
    paragraphs: list[str] = []
    current: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return tuple(paragraphs)


def parse_reviews(path: Path) -> tuple[ReviewBlock, ...]:
    """Parse explicit IDs/statuses and the v3 numbered-reviewer format."""
    if not path.is_file():
        raise WorkflowError(f"Reviewer comments are missing: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read reviewer comments: {path}") from exc
    blocks: list[ReviewBlock] = []
    block_title: str | None = None
    prefix: str | None = None
    general: list[str] = []
    comments: list[ReviewComment] = []
    comment_lines: list[str] = []
    current_id: str | None = None
    current_status: str | None = None

    def finish_comment() -> None:
        nonlocal comment_lines, current_id, current_status
        if current_id is None or current_status is None:
            return
        paragraphs = _paragraphs(comment_lines)
        if not paragraphs:
            raise WorkflowError(f"Comment {current_id} has no text.")
        comments.append(ReviewComment(current_id, current_status, paragraphs))
        comment_lines = []
        current_id = None
        current_status = None

    def finish_block() -> None:
        nonlocal general, comments
        if block_title is None or prefix is None:
            return
        finish_comment()
        if not comments:
            raise WorkflowError(f"{block_title} has no identified comments.")
        expected = [f"{prefix}-{index}" for index in range(1, len(comments) + 1)]
        observed = [comment.review_id for comment in comments]
        if observed != expected:
            raise WorkflowError(
                f"{block_title} IDs must be consecutive; observed {observed}."
            )
        blocks.append(
            ReviewBlock(block_title, prefix, _paragraphs(general), tuple(comments))
        )
        general = []
        comments = []

    for raw in lines:
        editor = EDITOR_HEADING.fullmatch(raw.strip())
        reviewer = REVIEWER_HEADING.fullmatch(raw.strip())
        if editor or reviewer:
            finish_block()
            if editor:
                block_title, prefix = "Editor", "E"
            else:
                assert reviewer is not None
                prefix = reviewer.group(1)
                block_title = f"Reviewer #{prefix}"
            continue
        if block_title is None or prefix is None:
            if raw.strip():
                raise WorkflowError("Text appears before the first review heading.")
            continue
        explicit = EXPLICIT_COMMENT.fullmatch(raw.strip())
        legacy = LEGACY_COMMENT.fullmatch(raw) if not raw.startswith("#") else None
        if explicit:
            finish_comment()
            current_id = explicit.group(1).upper()
            current_status = explicit.group(2).lower()
            if current_id.split("-", 1)[0] != prefix:
                raise WorkflowError(
                    f"Comment {current_id} does not belong under {block_title}."
                )
            continue
        if legacy and prefix != "E":
            finish_comment()
            current_id = f"{prefix}-{int(legacy.group(1))}"
            current_status = "manuscript_revised"
            comment_lines = [legacy.group(2)]
            continue
        if current_id is None:
            general.append(raw)
        else:
            comment_lines.append(raw)
    finish_block()
    if not blocks:
        raise WorkflowError("No Editor or Reviewer blocks were found.")
    all_ids = [comment.review_id for block in blocks for comment in block.comments]
    if len(all_ids) != len(set(all_ids)):
        raise WorkflowError("Reviewer comments contain duplicate IDs.")
    return tuple(blocks)


def _escape_latex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _comment_tex(paragraphs: tuple[str, ...]) -> list[str]:
    return [f"\\ReviewerComment{{{_escape_latex(item)}}}" for item in paragraphs]


def _body_tex(blocks: tuple[ReviewBlock, ...], language: str) -> str:
    lines: list[str] = []
    for block in blocks:
        title = "编辑" if language == "zh" and block.prefix == "E" else block.title
        general_title = "总体意见" if language == "zh" else "General comment"
        comment_title = "意见" if language == "zh" else "Comment"
        response_title = "回复" if language == "zh" else "Response"
        location_title = "位置" if language == "zh" else "Location"
        lines.extend([f"\\section*{{{_escape_latex(title)}}}", ""])
        if block.general_paragraphs:
            lines.extend([f"\\subsection*{{{general_title}}}", ""])
            lines.extend(_comment_tex(block.general_paragraphs))
            lines.append("")
        for comment in block.comments:
            lines.extend(
                [
                    f"\\subsection*{{{comment_title} {_escape_latex(comment.review_id)}}}",
                    "",
                    *_comment_tex(comment.paragraphs),
                    "",
                    f"\\textbf{{{response_title}.}}",
                    "",
                    f"\\ResponsePending{{{comment.review_id}}}",
                    "",
                    f"\\textbf{{{location_title}:}} "
                    f"\\ReviewLocation{{{comment.review_id}}}.",
                    "",
                ]
            )
    return "\n".join(lines)


def init_response(config: ProjectConfig, round_number: int) -> Path:
    """Create one editable response source from the version comment file."""
    if round_number < 1:
        raise WorkflowError("r00 does not have a reviewer response.")
    response_dir = config.round_dir(round_number) / "response"
    reviews = response_dir / "reviewer_comments.md"
    blocks = parse_reviews(reviews)
    target = response_dir / "response_letter.tex"
    if target.exists():
        raise WorkflowError(f"Response source already exists: {target}")
    template = (
        resources_root() / "response" / f"response_{config.language}.tex"
    ).read_text(encoding="utf-8")
    target.write_text(
        template.replace("%%ROUND%%", round_name(round_number).upper())
        .replace("%%BODY%%", _body_tex(blocks, config.language))
        .replace("%%AUTHOR_METADATA_PATH%%", "author_metadata.tex"),
        encoding="utf-8",
    )
    return target


def _ids_from_sources(version: Path) -> set[str]:
    ids: set[str] = set()
    paths = [version / "manuscript.tex", *sorted((version / "sections").rglob("*.tex"))]
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for raw_ids in REVIEW_MACRO.findall(text):
            ids.update(validate_review_id_list(raw_ids))
    return ids


def validate_response_links(config: ProjectConfig, round_number: int) -> None:
    """Require manuscript_revised IDs to appear in at least one review macro."""
    version = config.round_dir(round_number)
    blocks = parse_reviews(version / "response" / "reviewer_comments.md")
    revised = {
        comment.review_id
        for block in blocks
        for comment in block.comments
        if comment.status == "manuscript_revised"
    }
    present = _ids_from_sources(version)
    missing = sorted(revised - present)
    if missing:
        raise WorkflowError(
            "manuscript_revised comments lack manuscript provenance: "
            + ", ".join(missing)
        )


def pending_response_ids(source: Path) -> tuple[str, ...]:
    """Return valid unfinished IDs while ignoring the macro definition."""
    text = source.read_text(encoding="utf-8")
    values = tuple(PENDING_RESPONSE.findall(text))
    for value in values:
        if not is_review_id(value):
            raise WorkflowError(f"Invalid pending response ID: {value}")
    return values


def build_response(
    config: ProjectConfig,
    round_number: int,
    locations: dict[str, str],
    run_dir: Path,
    engine_override: str | None = None,
    allow_placeholders: bool = False,
) -> Path:
    """Compile a response copy with temporary line-location substitutions."""
    validate_response_links(config, round_number)
    source = config.round_dir(round_number) / "response" / "response_letter.tex"
    if not source.is_file():
        raise WorkflowError(f"Response source is missing: {source}")
    pending = pending_response_ids(source)
    if pending and not allow_placeholders:
        raise WorkflowError(
            "Response source still contains unfinished responses: " + ", ".join(pending)
        )
    stage = run_dir / "response_source"
    stage.mkdir(parents=True)
    text = source.read_text(encoding="utf-8")

    def replace_location(match: re.Match[str]) -> str:
        review_id = match.group(1)
        if not is_review_id(review_id):
            raise WorkflowError(f"Invalid response location ID: {review_id}")
        return locations.get(review_id, "Location unavailable")

    staged_source = stage / "response_letter.tex"
    staged_source.write_text(LOCATION_USE.sub(replace_location, text), encoding="utf-8")
    generate_metadata(config.project, config.round_dir(round_number), stage)
    compiled = compile_tex(
        staged_source,
        run_dir / "response_build",
        config,
        engine_override,
    )
    output = config.round_dir(round_number) / "output" / "response_letter.pdf"
    output.parent.mkdir(exist_ok=True)
    shutil.copy2(compiled.pdf, output)
    return output
