"""Reviewer comment parsing, review audit, and response compilation."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .compile import compile_tex, stage_cjk_fonts
from .metadata import generate_metadata
from .workspace import ProjectConfig, WorkflowError, resources_root

REVIEW_ID = re.compile(r"^(?:E|AE|[1-9]\d*)-[1-9]\d*$")
REVIEWER_HEADING = re.compile(r"^#\s*(?:Reviewer|审稿人)\s*#?\s*([1-9]\d*)\s*$", re.I)
EDITOR_HEADING = re.compile(r"^#\s*(?:Editor|编辑)\s*$", re.I)
ASSOCIATE_EDITOR_HEADING = re.compile(r"^#\s*(?:Associate\s+Editor|副编辑)\s*$", re.I)
EXPLICIT_COMMENT = re.compile(
    r"^##\s*((?:E|AE|[1-9]\d*)-[1-9]\d*)\s*"
    r"(?:\|\s*|\[)(response_only|manuscript_revised)\]?\s*$",
    re.I,
)
NUMBERED_COMMENT = re.compile(r"^\s*([1-9]\d*)[.)]\s*(.*)$")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
PENDING_RESPONSE = re.compile(r"\\ResponsePending\{([^}]+)\}")
LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")
REVIEW_MACRO = re.compile(r"\\review\s*\{([^}]+)\}")
RESPONSE_COMMAND = r"\Response"
REVIEW_INDEX_NAME = "review_index.yaml"


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
    """One reviewer or editor comment with an internally assigned ID."""

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


@dataclass(frozen=True)
class ReviewAuditEntry:
    """Computed state for one comment in the current revision."""

    review_id: str
    state: str


@dataclass(frozen=True)
class ReviewAuditIssue:
    """One non-blocking review-completeness issue with source paths."""

    code: str
    review_id: str | None
    message: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class ReviewAuditResult:
    """Cross-check of comments, responses, and manuscript provenance."""

    comment_path: Path
    response_path: Path
    entries: tuple[ReviewAuditEntry, ...]
    issues: tuple[ReviewAuditIssue, ...]

    @property
    def total(self) -> int:
        """Return the number of parsed review comments."""
        return len(self.entries)

    @property
    def complete(self) -> int:
        """Return the number of comments with a completed response."""
        return sum(
            entry.state in {"manuscript_revised", "response_only"}
            for entry in self.entries
        )

    @property
    def is_complete(self) -> bool:
        """Return whether the review audit has no warnings."""
        return not self.issues


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
    """Parse the user-facing numbered-list format and legacy explicit headings."""
    if not path.is_file():
        raise WorkflowError(f"Reviewer comments are missing: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read reviewer comments: {path}") from exc
    lines = HTML_COMMENT.sub("", raw_text).splitlines()
    blocks: list[ReviewBlock] = []
    block_title: str | None = None
    prefix: str | None = None
    general: list[str] = []
    comments: list[ReviewComment] = []
    comment_lines: list[str] = []
    current_id: str | None = None
    current_status = "auto"

    def finish_comment() -> None:
        nonlocal comment_lines, current_id, current_status
        if current_id is None:
            return
        paragraphs = _paragraphs(comment_lines)
        if paragraphs:
            comments.append(ReviewComment(current_id, current_status, paragraphs))
        comment_lines = []
        current_id = None
        current_status = "auto"

    def finish_block() -> None:
        nonlocal general, comments
        if block_title is None or prefix is None:
            return
        finish_comment()
        blocks.append(
            ReviewBlock(block_title, prefix, _paragraphs(general), tuple(comments))
        )
        general = []
        comments = []

    for raw in lines:
        stripped = raw.strip()
        editor = EDITOR_HEADING.fullmatch(stripped)
        associate_editor = ASSOCIATE_EDITOR_HEADING.fullmatch(stripped)
        reviewer = REVIEWER_HEADING.fullmatch(stripped)
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
            if stripped:
                raise WorkflowError(
                    f"Text appears before the first review heading: {path}"
                )
            continue
        explicit = EXPLICIT_COMMENT.fullmatch(stripped)
        numbered = NUMBERED_COMMENT.fullmatch(raw) if not raw.startswith("#") else None
        if explicit:
            finish_comment()
            current_id = explicit.group(1).upper()
            current_status = explicit.group(2).lower()
            if current_id.split("-", 1)[0] != prefix:
                raise WorkflowError(
                    f"Comment {current_id} does not belong under {block_title}: {path}"
                )
            continue
        if numbered:
            finish_comment()
            current_id = f"{prefix}-{len(comments) + 1}"
            current_status = "auto"
            body = numbered.group(2).strip()
            comment_lines = [body] if body else []
            continue
        if current_id is None:
            general.append(raw)
        else:
            comment_lines.append(raw)
    finish_block()
    all_ids = [comment.review_id for block in blocks for comment in block.comments]
    if len(all_ids) != len(set(all_ids)):
        raise WorkflowError(f"Reviewer comments contain duplicate IDs: {path}")
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


def parse_response_entries(path: Path) -> dict[str, str]:
    r"""Parse observed ``\Response{ID}{body}`` entries without completeness checks."""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read response content: {path}") from exc
    responses: dict[str, str] = {}
    cursor = _skip_tex_space(text, 0)
    while cursor < len(text):
        if not text.startswith(RESPONSE_COMMAND, cursor):
            raise WorkflowError(
                f"Unexpected content in {path} at character {cursor + 1}; "
                "expected \\Response{ID}{...}."
            )
        cursor += len(RESPONSE_COMMAND)
        if cursor < len(text) and (text[cursor].isalnum() or text[cursor] == "@"):
            raise WorkflowError(
                f"Unexpected command in {path} at character {cursor + 1}."
            )
        cursor = _skip_tex_space(text, cursor)
        raw_id, cursor = _extract_braced_response_field(text, cursor)
        review_id = raw_id.strip()
        if not is_review_id(review_id):
            raise WorkflowError(f"Invalid response ID {review_id!r}: {path}")
        if review_id in responses:
            raise WorkflowError(f"Duplicate response ID {review_id}: {path}")
        cursor = _skip_tex_space(text, cursor)
        body, cursor = _extract_braced_response_field(text, cursor)
        responses[review_id] = body.strip()
        cursor = _skip_tex_space(text, cursor)
    return responses


def parse_responses(path: Path, expected_ids: tuple[str, ...]) -> dict[str, str]:
    r"""Parse strict ``\Response{ID}{body}`` entries with nested TeX braces."""
    if not path.is_file():
        raise WorkflowError(f"Response content is missing: {path}")
    responses = parse_response_entries(path)
    expected = set(expected_ids)
    observed = set(responses)
    unknown = sorted(observed - expected)
    if unknown:
        raise WorkflowError("Unknown response IDs: " + ", ".join(unknown))
    missing = sorted(expected - observed)
    if missing:
        raise WorkflowError("Missing response IDs: " + ", ".join(missing))
    return responses


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


def _review_ids_with_paths(version: Path) -> dict[str, set[Path]]:
    result: dict[str, set[Path]] = {}
    paths = [version / "manuscript.tex", *sorted((version / "sections").rglob("*.tex"))]
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for raw_ids in REVIEW_MACRO.findall(text):
            for review_id in validate_review_id_list(raw_ids):
                result.setdefault(review_id, set()).add(path.resolve())
    return result


def _ids_from_sources(version: Path) -> set[str]:
    """Return all review provenance IDs in the manuscript source."""
    return set(_review_ids_with_paths(version))


def validate_response_links(config: ProjectConfig, round_number: int) -> None:
    """Compatibility validator; review linkage is now reported by audit."""
    audit_reviews(config, round_number)


def _comment_fingerprint(comment: ReviewComment) -> str:
    normalized = " ".join(comment.text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _review_index_path(version: Path) -> Path:
    return version / "output" / REVIEW_INDEX_NAME


def _load_review_index(version: Path) -> dict[str, str]:
    path = _review_index_path(version)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    comments = data.get("comments")
    if not isinstance(comments, dict):
        return {}
    return {
        str(review_id): str(fingerprint)
        for review_id, fingerprint in comments.items()
        if is_review_id(str(review_id))
    }


def _write_review_index(version: Path, comments: dict[str, ReviewComment]) -> None:
    if not comments:
        return
    path = _review_index_path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "comments": {
            review_id: _comment_fingerprint(comment)
            for review_id, comment in comments.items()
        }
    }
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def audit_reviews(
    config: ProjectConfig,
    round_number: int,
    *,
    record_index: bool = False,
) -> ReviewAuditResult:
    """Cross-check comments, responses, and manuscript provenance without blocking."""
    version = config.round_dir(round_number)
    comment_path = (version / "response" / "reviewer_comments.md").resolve()
    response_path = (version / "response" / "responses.tex").resolve()
    issues: list[ReviewAuditIssue] = []
    try:
        blocks = parse_reviews(comment_path)
    except WorkflowError as exc:
        blocks = ()
        issues.append(
            ReviewAuditIssue(
                "COMMENTS_INVALID",
                None,
                str(exc),
                (comment_path,),
            )
        )
    comments = {
        comment.review_id: comment for block in blocks for comment in block.comments
    }
    try:
        responses = parse_response_entries(response_path)
    except WorkflowError as exc:
        responses = {}
        issues.append(
            ReviewAuditIssue(
                "RESPONSES_INVALID",
                None,
                str(exc),
                (response_path,),
            )
        )
    provenance = _review_ids_with_paths(version)
    pending = set(pending_response_ids(responses)) if responses else set()
    entries: list[ReviewAuditEntry] = []

    if not comments and not any(issue.code == "COMMENTS_INVALID" for issue in issues):
        issues.append(
            ReviewAuditIssue(
                "COMMENTS_EMPTY",
                None,
                "Reviewer comments have not been entered.",
                (comment_path,),
            )
        )

    for review_id in comments:
        body = responses.get(review_id, "").strip()
        has_response = bool(body) and review_id not in pending
        has_revision = review_id in provenance
        if has_response and has_revision:
            state = "manuscript_revised"
        elif has_response:
            state = "response_only"
        elif has_revision:
            state = "manuscript_changed_but_unanswered"
            issues.append(
                ReviewAuditIssue(
                    "MISSING_RESPONSE",
                    review_id,
                    "The manuscript cites this review ID, but its response is unfinished.",
                    (comment_path, response_path, *sorted(provenance[review_id])),
                )
            )
        else:
            state = "unanswered"
            issues.append(
                ReviewAuditIssue(
                    "MISSING_RESPONSE",
                    review_id,
                    "This reviewer comment has no completed response.",
                    (comment_path, response_path),
                )
            )
        entries.append(ReviewAuditEntry(review_id, state))

    for review_id in sorted(set(responses) - set(comments)):
        issues.append(
            ReviewAuditIssue(
                "ORPHAN_RESPONSE",
                review_id,
                "A response exists without a matching reviewer comment.",
                (response_path, comment_path),
            )
        )
    for review_id in sorted(set(provenance) - set(comments)):
        issues.append(
            ReviewAuditIssue(
                "ORPHAN_REVIEW_REFERENCE",
                review_id,
                "A \\review reference exists without a matching reviewer comment.",
                (*sorted(provenance[review_id]), comment_path),
            )
        )

    previous = _load_review_index(version)
    current = {
        review_id: _comment_fingerprint(comment)
        for review_id, comment in comments.items()
    }
    previous_by_fingerprint = {value: key for key, value in previous.items()}
    drift = False
    for review_id, fingerprint in current.items():
        previous_id = previous_by_fingerprint.get(fingerprint)
        if previous_id is not None and previous_id != review_id:
            drift = True
            issues.append(
                ReviewAuditIssue(
                    "REVIEW_ID_DRIFT",
                    review_id,
                    f"This comment previously mapped to {previous_id} and now maps to {review_id}.",
                    (comment_path, _review_index_path(version).resolve()),
                )
            )
    if record_index and comments and not drift:
        _write_review_index(version, comments)

    return ReviewAuditResult(
        comment_path,
        response_path,
        tuple(entries),
        tuple(issues),
    )


def init_response(config: ProjectConfig, round_number: int) -> Path:
    """Create the editable response source; empty review templates yield an empty file."""
    if round_number < 1:
        raise WorkflowError("r00 does not have a reviewer response.")
    response_dir = config.round_dir(round_number) / "response"
    blocks = parse_reviews(response_dir / "reviewer_comments.md")
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
    target.write_text(
        ("\n\n".join(entries) + "\n") if entries else "", encoding="utf-8"
    )
    return target


def _body_tex(
    blocks: tuple[ReviewBlock, ...],
    language: str,
    responses: dict[str, str],
    revised_ids: set[str],
) -> str:
    lines: list[str] = []
    for block in blocks:
        if not block.comments and not block.general_paragraphs:
            continue
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
            if comment.review_id in revised_ids:
                lines.extend(
                    [
                        f"\\reviewlocation{{\\ReviewLocation{{{comment.review_id}}}}}",
                        "",
                    ]
                )
    return "\n".join(lines)


def build_response(
    config: ProjectConfig,
    round_number: int,
    locations: dict[str, str],
    run_dir: Path,
    engine_override: str | None = None,
    allow_placeholders: bool = False,
) -> Path:
    """Compile a response copy with strict low-level validation by default."""
    version = config.round_dir(round_number)
    blocks = parse_reviews(version / "response" / "reviewer_comments.md")
    expected_ids = tuple(
        comment.review_id for block in blocks for comment in block.comments
    )
    if not expected_ids:
        raise WorkflowError(
            f"No reviewer comments are available: {version / 'response' / 'reviewer_comments.md'}"
        )
    observed = parse_response_entries(version / "response" / "responses.tex")
    responses = {
        review_id: observed.get(review_id, f"\\ResponsePending{{{review_id}}}")
        for review_id in expected_ids
    }
    pending = pending_response_ids(responses)
    if pending and not allow_placeholders:
        raise WorkflowError(
            "Response source still contains unfinished responses: " + ", ".join(pending)
        )
    revised_ids = _ids_from_sources(version).intersection(expected_ids)
    missing_locations = sorted(
        review_id
        for review_id in revised_ids
        if review_id not in locations or locations[review_id] == "Location unavailable"
    )
    if missing_locations and not allow_placeholders:
        raise WorkflowError(
            "Marked manuscript locations are missing for: "
            + ", ".join(missing_locations)
        )
    stage = run_dir / "response_source"
    stage.mkdir(parents=True)
    if config.language == "zh":
        stage_cjk_fonts(stage)
    text = _response_template(config.language).replace(
        "%%RESPONSE_BODY%%",
        _body_tex(blocks, config.language, responses, revised_ids),
    )

    def replace_location(match: re.Match[str]) -> str:
        review_id = match.group(1)
        if not is_review_id(review_id):
            raise WorkflowError(f"Invalid response location ID: {review_id}")
        location = locations.get(review_id, "Location unavailable")
        if config.language != "zh":
            return location
        if location.startswith("Lines "):
            return "第 " + location.removeprefix("Lines ") + " 行"
        if location.startswith("Line "):
            return "第 " + location.removeprefix("Line ") + " 行"
        if location == "Location unavailable":
            return "位置不可用"
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
