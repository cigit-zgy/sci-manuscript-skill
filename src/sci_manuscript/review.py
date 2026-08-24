"""Review comments, responses, triad audit, and persistent review state."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import WorkflowError
from .review_ids import is_review_id, validate_review_id_list
from .tex import extract_braced, skip_tex_space
from .workspace import ProjectConfig

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
REVIEW_MACRO = re.compile(r"\\review\s*\{([^}]+)\}")
RESPONSE_COMMAND = r"\Response"
REVIEW_INDEX_NAME = "review_index.yaml"


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


def _extract_braced_response_field(text: str, start: int) -> tuple[str, int]:
    try:
        return extract_braced(text, start)
    except ValueError as exc:
        raise WorkflowError("Unbalanced braces in responses.tex.") from exc


def parse_response_entries(path: Path) -> dict[str, str]:
    r"""Parse observed ``\Response{ID}{body}`` entries without completeness checks."""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read response content: {path}") from exc
    responses: dict[str, str] = {}
    cursor = skip_tex_space(text, 0)
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
        cursor = skip_tex_space(text, cursor)
        raw_id, cursor = _extract_braced_response_field(text, cursor)
        review_id = raw_id.strip()
        if not is_review_id(review_id):
            raise WorkflowError(f"Invalid response ID {review_id!r}: {path}")
        if review_id in responses:
            raise WorkflowError(f"Duplicate response ID {review_id}: {path}")
        cursor = skip_tex_space(text, cursor)
        body, cursor = _extract_braced_response_field(text, cursor)
        responses[review_id] = body.strip()
        cursor = skip_tex_space(text, cursor)
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


def review_ids_from_sources(config: ProjectConfig, round_number: int) -> set[str]:
    """Return all review provenance IDs in one manuscript round."""
    return set(_review_ids_with_paths(config.round_dir(round_number)))


def validate_response_links(config: ProjectConfig, round_number: int) -> None:
    """Compatibility validator; review linkage is now reported by audit."""
    audit_reviews(config, round_number)


def _comment_fingerprint(comment: ReviewComment) -> str:
    normalized = " ".join(comment.text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_review_index(config: ProjectConfig, round_number: int) -> dict[str, str]:
    path = config.review_index_path(round_number)
    if not path.is_file():
        path = config.output_dir(round_number) / REVIEW_INDEX_NAME
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


def _write_review_index(
    config: ProjectConfig,
    round_number: int,
    comments: dict[str, ReviewComment],
) -> None:
    if not comments:
        return
    path = config.review_index_path(round_number)
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
    legacy = config.output_dir(round_number) / REVIEW_INDEX_NAME
    if legacy.is_file():
        legacy.unlink()


def audit_reviews(
    config: ProjectConfig,
    round_number: int,
    *,
    record_index: bool = False,
) -> ReviewAuditResult:
    """Cross-check comments, responses, and manuscript provenance without blocking."""
    version = config.round_dir(round_number)
    response_dir = config.response_dir(round_number)
    comment_path = (response_dir / "reviewer_comments.md").resolve()
    response_path = (response_dir / "responses.tex").resolve()
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
        pending = set(pending_response_ids(responses))
    except WorkflowError as exc:
        responses = {}
        pending = set()
        issues.append(
            ReviewAuditIssue(
                "RESPONSES_INVALID",
                None,
                str(exc),
                (response_path,),
            )
        )
    provenance = _review_ids_with_paths(version)
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

    previous = _load_review_index(config, round_number)
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
                    (comment_path, config.review_index_path(round_number).resolve()),
                )
            )
    if record_index and comments and not drift:
        _write_review_index(config, round_number, comments)

    return ReviewAuditResult(
        comment_path,
        response_path,
        tuple(entries),
        tuple(issues),
    )
