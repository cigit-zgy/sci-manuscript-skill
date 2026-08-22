"""Reviewer comment parsing, provenance validation, and response compilation."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .compile import compile_tex, stage_cjk_fonts
from .metadata import generate_metadata
from .workspace import ProjectConfig, WorkflowError, resources_root

REVIEW_ID = re.compile(r"^(?:E|AE|[1-9]\d*)-[1-9]\d*$")
REVIEWER_HEADING = re.compile(r"^#\s*Reviewer\s*#?\s*([1-9]\d*)\s*$", re.I)
EDITOR_HEADING = re.compile(r"^#\s*Editor\s*$", re.I)
ASSOCIATE_EDITOR_HEADING = re.compile(r"^#\s*Associate\s+Editor\s*$", re.I)
EXPLICIT_COMMENT = re.compile(
    r"^##\s*((?:E|AE|[1-9]\d*)-[1-9]\d*)\s*"
    r"(?:\|\s*|\[)(response_only|manuscript_revised)\]?\s*$",
    re.I,
)
LEGACY_COMMENT = re.compile(r"^\s*([1-9]\d*)\.?\s+(.*)$")
PENDING_RESPONSE = re.compile(r"\\ResponsePending\{([^}]+)\}")
LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")
REVIEW_MACRO = re.compile(r"\\review\s*\{([^}]+)\}")
RESPONSE_COMMAND = r"\Response"


def is_review_id(value: str) -> bool:
    """Return whether a single reviewer/editor ID is valid."""
    return REVIEW_ID.fullmatch(value.strip()) is not None


def validate_review_id_list(value: str) -> tuple[str, ...]:
    """Validate a comma-separated review provenance list."""
    ids = tuple(item.strip() for item in value.split(","))
    if not ids or any(not is_review_id(item) for item in ids):
        raise WorkflowError(
            f"Invalid review ID list {value!r}; use E-1, AE-1, 1-1, "
            "or comma-separated IDs."
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
        associate_editor = ASSOCIATE_EDITOR_HEADING.fullmatch(raw.strip())
        reviewer = REVIEWER_HEADING.fullmatch(raw.strip())
        if editor or associate_editor or reviewer:
            finish_block()
            if editor:
                block_title, prefix = "Editor", "E"
            elif associate_editor:
                block_title, prefix = "Associate Editor", "AE"
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
        if legacy and prefix not in {"E", "AE"}:
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


def _is_escaped(text: str, index: int) -> bool:
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def _skip_tex_space(text: str, start: int) -> int:
    cursor = start
    while cursor < len(text):
        if text[cursor].isspace():
            cursor += 1
            continue
        if text[cursor] == "%" and not _is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        break
    return cursor


def _extract_braced_response_field(text: str, start: int) -> tuple[str, int]:
    if start >= len(text) or text[start] != "{":
        raise WorkflowError("Response parser expected an opening brace.")
    depth = 0
    cursor = start
    while cursor < len(text):
        char = text[cursor]
        if char == "%" and not _is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        if char == "{" and not _is_escaped(text, cursor):
            depth += 1
        elif char == "}" and not _is_escaped(text, cursor):
            depth -= 1
            if depth == 0:
                return text[start + 1 : cursor], cursor + 1
        cursor += 1
    raise WorkflowError("Unbalanced braces in responses.tex.")


def parse_responses(path: Path, expected_ids: tuple[str, ...]) -> dict[str, str]:
    r"""Parse strict ``\Response{ID}{body}`` entries with nested TeX braces."""
    if not path.is_file():
        raise WorkflowError(f"Response content is missing: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read response content: {path}") from exc
    responses: dict[str, str] = {}
    cursor = _skip_tex_space(text, 0)
    while cursor < len(text):
        if not text.startswith(RESPONSE_COMMAND, cursor):
            raise WorkflowError(
                f"Unexpected content in responses.tex at character {cursor + 1}; "
                "expected \\Response{ID}{...}."
            )
        cursor += len(RESPONSE_COMMAND)
        if cursor < len(text) and (text[cursor].isalnum() or text[cursor] == "@"):
            raise WorkflowError(
                f"Unexpected command in responses.tex at character {cursor + 1}."
            )
        cursor = _skip_tex_space(text, cursor)
        raw_id, cursor = _extract_braced_response_field(text, cursor)
        review_id = raw_id.strip()
        if not is_review_id(review_id):
            raise WorkflowError(f"Invalid response ID: {review_id!r}")
        if review_id in responses:
            raise WorkflowError(f"Duplicate response ID: {review_id}")
        cursor = _skip_tex_space(text, cursor)
        body, cursor = _extract_braced_response_field(text, cursor)
        responses[review_id] = body.strip()
        cursor = _skip_tex_space(text, cursor)
    expected = set(expected_ids)
    observed = set(responses)
    unknown = sorted(observed - expected)
    if unknown:
        raise WorkflowError("Unknown response IDs: " + ", ".join(unknown))
    missing = sorted(expected - observed)
    if missing:
        raise WorkflowError("Missing response IDs: " + ", ".join(missing))
    return responses


def _body_tex(
    blocks: tuple[ReviewBlock, ...],
    language: str,
    responses: dict[str, str],
) -> str:
    lines: list[str] = []
    for block in blocks:
        title = block.title
        if language == "zh":
            title = {
                "E": "编辑",
                "AE": "副编辑",
            }.get(block.prefix, f"审稿人 #{block.prefix}")
        general_title = "总体意见" if language == "zh" else "General comment"
        lines.extend([f"\\ResponseSection{{{_escape_latex(title)}}}", ""])
        if block.general_paragraphs:
            lines.extend([f"\\begin{{generalcomment}}[{general_title}]"])
            lines.extend(_comment_tex(block.general_paragraphs))
            lines.extend(["\\end{generalcomment}", ""])
        for comment in block.comments:
            lines.extend(
                [
                    f"\\begin{{reviewcomment}}{{{_escape_latex(comment.review_id)}}}",
                    *_comment_tex(comment.paragraphs),
                    "\\end{reviewcomment}",
                    "\\begin{response}",
                    responses[comment.review_id],
                    "\\end{response}",
                    "",
                ]
            )
            if comment.status == "manuscript_revised":
                lines.extend(
                    [
                        f"\\reviewlocation{{\\ReviewLocation{{{comment.review_id}}}}}",
                        "",
                    ]
                )
    return "\n".join(lines)


def init_response(config: ProjectConfig, round_number: int) -> Path:
    """Create one thin, editable response-content source for a revision."""
    if round_number < 1:
        raise WorkflowError("r00 does not have a reviewer response.")
    response_dir = config.round_dir(round_number) / "response"
    reviews = response_dir / "reviewer_comments.md"
    blocks = parse_reviews(reviews)
    target = response_dir / "responses.tex"
    if target.exists():
        raise WorkflowError(f"Response source already exists: {target}")
    entries = [
        f"\\Response{{{comment.review_id}}}{{\n"
        f"\\ResponsePending{{{comment.review_id}}}\n"
        "}"
        for block in blocks
        for comment in block.comments
    ]
    target.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    return target


def _response_template(language: str) -> str:
    path = (
        resources_root()
        / "correspondence_templates"
        / "response"
        / f"response_{language}.tex"
    )
    try:
        template = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read response template: {path}") from exc
    if template.count("%%RESPONSE_BODY%%") != 1:
        raise WorkflowError(
            f"Response template must contain one %%RESPONSE_BODY%% token: {path}"
        )
    return template


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


def pending_response_ids(responses: dict[str, str]) -> tuple[str, ...]:
    """Return unfinished response IDs after validating their pending markers."""
    pending: list[str] = []
    for review_id, body in responses.items():
        for value in PENDING_RESPONSE.findall(body):
            if not is_review_id(value):
                raise WorkflowError(f"Invalid pending response ID: {value}")
            if value != review_id:
                raise WorkflowError(
                    f"Response {review_id} contains pending marker for {value}."
                )
            pending.append(review_id)
    return tuple(pending)


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
    version = config.round_dir(round_number)
    blocks = parse_reviews(version / "response" / "reviewer_comments.md")
    expected_ids = tuple(
        comment.review_id for block in blocks for comment in block.comments
    )
    responses = parse_responses(version / "response" / "responses.tex", expected_ids)
    pending = pending_response_ids(responses)
    if pending and not allow_placeholders:
        raise WorkflowError(
            "Response source still contains unfinished responses: " + ", ".join(pending)
        )
    revised_ids = {
        comment.review_id
        for block in blocks
        for comment in block.comments
        if comment.status == "manuscript_revised"
    }
    missing_locations = sorted(
        review_id
        for review_id in revised_ids
        if review_id not in locations or locations[review_id] == "Location unavailable"
    )
    if missing_locations:
        raise WorkflowError(
            "Marked manuscript locations are missing for: "
            + ", ".join(missing_locations)
        )
    stage = run_dir / "response_source"
    stage.mkdir(parents=True)
    if config.language == "zh":
        stage_cjk_fonts(stage)
    text = _response_template(config.language).replace(
        "%%RESPONSE_BODY%%", _body_tex(blocks, config.language, responses)
    )

    def replace_location(match: re.Match[str]) -> str:
        review_id = match.group(1)
        if not is_review_id(review_id):
            raise WorkflowError(f"Invalid response location ID: {review_id}")
        location = locations[review_id]
        if config.language != "zh":
            return location
        if location.startswith("Lines "):
            return "第 " + location.removeprefix("Lines ") + " 行"
        if location.startswith("Line "):
            return "第 " + location.removeprefix("Line ") + " 行"
        return location

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
