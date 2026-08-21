"""Internal reviewer-comment parsing and response-letter rendering."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .compile import compile_tex
from .resources import read_resource_text
from .review_ids import is_review_id
from .workspace import ProjectConfig, WorkflowError, round_name

EDITOR_HEADING = re.compile(r"^\s*#\s*Editor\s*$", re.IGNORECASE)
ASSOCIATE_EDITOR_HEADING = re.compile(
    r"^\s*#\s*Associate\s+Editor\s*$",
    re.IGNORECASE,
)
REVIEWER_HEADING = re.compile(
    r"^\s*#\s*Reviewer\s*#?\s*([^\s#]+)\s*$",
    re.IGNORECASE,
)
COMMENT_START = re.compile(r"^\s*(\d+)\\?\.\s*(.*)$")
PENDING_RESPONSE = re.compile(r"\\ResponsePending\{([^}]+)\}")
LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")


@dataclass(frozen=True)
class ReviewComment:
    """One numbered external comment with its stable per-round ID."""

    owner: str
    number: int
    text: str

    @property
    def review_id(self) -> str:
        """Return the stable ID used in manuscript provenance markup."""
        return f"{self.owner}-{self.number}"


@dataclass(frozen=True)
class ReviewBlock:
    """One editor or reviewer block and its numbered comments."""

    owner: str
    role: str
    general_comment: str
    comments: tuple[ReviewComment, ...]


def _paragraph_text(lines: list[str]) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            if line[:1].isspace() and current:
                paragraphs.append(" ".join(current))
                current = []
            current.append(stripped)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def _parse_heading(raw: str) -> tuple[str, str] | None:
    if EDITOR_HEADING.fullmatch(raw):
        return "E", "editor"
    if ASSOCIATE_EDITOR_HEADING.fullmatch(raw):
        return "AE", "associate_editor"
    match = REVIEWER_HEADING.fullmatch(raw)
    if match is None:
        return None
    raw_number = match.group(1)
    if not re.fullmatch(r"[1-9]\d*", raw_number):
        raise WorkflowError(
            f"Reviewer number must be a positive integer without leading zeros: "
            f"{raw_number!r}."
        )
    return raw_number, "reviewer"


def parse_reviews(path: Path) -> tuple[ReviewBlock, ...]:
    """Parse explicitly designated reviewer Markdown without silent renumbering."""
    if not path.exists():
        raise WorkflowError(f"Reviewer-comments file is missing: {path}")
    blocks: list[ReviewBlock] = []
    owner: str | None = None
    role: str | None = None
    observed_owners: set[str] = set()
    general: list[str] = []
    comment_lines: list[str] = []
    comments: list[ReviewComment] = []
    current_number: int | None = None

    def finish_comment() -> None:
        nonlocal comment_lines, current_number
        if owner is None or current_number is None:
            return
        text = _paragraph_text(comment_lines)
        if not text:
            raise WorkflowError(f"Review comment {owner}-{current_number} is empty.")
        comments.append(ReviewComment(owner, current_number, text))
        comment_lines = []
        current_number = None

    def finish_block() -> None:
        nonlocal general, comments
        if owner is None or role is None:
            return
        finish_comment()
        expected = list(range(1, len(comments) + 1))
        observed = [comment.number for comment in comments]
        if observed != expected:
            raise WorkflowError(
                f"Review block {owner} comments must be consecutive from 1; "
                f"observed {observed}."
            )
        if not comments:
            raise WorkflowError(f"Review block {owner} has no numbered comments.")
        blocks.append(
            ReviewBlock(owner, role, _paragraph_text(general), tuple(comments))
        )
        general = []
        comments = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        heading = _parse_heading(raw)
        if heading is not None:
            finish_block()
            owner, role = heading
            if owner in observed_owners:
                raise WorkflowError(f"Duplicate review block: {owner}.")
            observed_owners.add(owner)
            continue
        if owner is None:
            if raw.strip():
                raise WorkflowError("Text appears before the first reviewer heading.")
            continue
        numbered = COMMENT_START.match(raw)
        if numbered:
            finish_comment()
            raw_number = numbered.group(1)
            if not re.fullmatch(r"[1-9]\d*", raw_number):
                raise WorkflowError(
                    "Comment numbers must be positive integers without leading zeros."
                )
            current_number = int(raw_number)
            comment_lines = [numbered.group(2)]
        elif current_number is None:
            general.append(raw)
        else:
            comment_lines.append(raw)
    finish_block()
    if not blocks:
        raise WorkflowError("No reviewer blocks were found.")
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
    return "".join(replacements.get(char, char) for char in value)


def _comment_tex(value: str) -> list[str]:
    return [
        f"\\ReviewerComment{{{_escape_latex(paragraph)}}}"
        for paragraph in value.split("\n\n")
        if paragraph
    ]


def _body_tex(blocks: tuple[ReviewBlock, ...], language: str) -> str:
    lines: list[str] = []
    for block in blocks:
        if block.role == "editor":
            block_title = "编辑" if language == "zh" else "Editor"
        elif block.role == "associate_editor":
            block_title = "副编辑" if language == "zh" else "Associate Editor"
        else:
            reviewer_title = "审稿人" if language == "zh" else "Reviewer"
            block_title = f"{reviewer_title} \\#{block.owner}"
        general_title = "总体意见" if language == "zh" else "General comment"
        comment_title = "意见" if language == "zh" else "Comment"
        response_title = "回复" if language == "zh" else "Response"
        location_title = "位置" if language == "zh" else "Location"
        lines.extend([f"\\section*{{{block_title}}}", ""])
        if block.general_comment:
            lines.extend([f"\\subsection*{{{general_title}}}"])
            lines.extend(_comment_tex(block.general_comment))
            lines.append("")
        for comment in block.comments:
            lines.append(f"\\subsection*{{{comment_title} {comment.number}}}")
            lines.extend(_comment_tex(comment.text))
            lines.extend(
                [
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


def init_response(
    config: ProjectConfig,
    round_number: int,
    reviews: Path,
    language: str | None = None,
) -> Path:
    """Create one editable response source from an explicit Markdown file."""
    if round_number < 1:
        raise WorkflowError("R0 does not have a reviewer response.")
    response_language = language or config.response_language
    if response_language not in {"en", "zh"}:
        raise WorkflowError("Response language must be en or zh.")
    blocks = parse_reviews(reviews)
    response_dir = config.round_dir(round_number) / "response"
    response_dir.mkdir(exist_ok=True)
    target = response_dir / "response_letter.tex"
    if target.exists():
        raise WorkflowError(f"Response source already exists: {target}")
    text = read_resource_text("response", f"response_{response_language}.tex")
    text = text.replace("%%ROUND%%", round_name(round_number).upper())
    text = text.replace("%%BODY%%", _body_tex(blocks, response_language))
    text = text.replace(
        "%%AUTHOR_METADATA_PATH%%",
        "../../references/author_metadata.tex",
    )
    target.write_text(text, encoding="utf-8")
    local_reviews = response_dir / "reviewer_comments.md"
    if reviews.resolve() != local_reviews.resolve():
        shutil.copy2(reviews, local_reviews)
    return target


def pending_response_ids(source: Path) -> tuple[str, ...]:
    """Return unfinished response IDs without matching the macro definition."""
    text = source.read_text(encoding="utf-8")
    identifiers = tuple(PENDING_RESPONSE.findall(text))
    invalid = [identifier for identifier in identifiers if not is_review_id(identifier)]
    if invalid:
        raise WorkflowError("Invalid pending response IDs: " + ", ".join(invalid))
    return identifiers


def build_response(
    config: ProjectConfig,
    round_number: int,
    locations: dict[str, str],
    run_dir: Path,
    engine_override: str | None = None,
    allow_placeholders: bool = False,
) -> Path:
    """Render temporary line locations, compile, and publish a response PDF."""
    source = config.round_dir(round_number) / "response" / "response_letter.tex"
    if not source.exists():
        raise WorkflowError(
            f"Response source is missing; run init-response first: {source}"
        )
    pending = pending_response_ids(source)
    if pending and not allow_placeholders:
        raise WorkflowError(
            "Response source still contains unfinished responses: " + ", ".join(pending)
        )
    text = source.read_text(encoding="utf-8")
    location_ids = tuple(LOCATION_USE.findall(text))
    invalid_locations = [
        identifier for identifier in location_ids if not is_review_id(identifier)
    ]
    if invalid_locations:
        raise WorkflowError(
            "Invalid review location IDs: " + ", ".join(invalid_locations)
        )

    def replace_location(match: re.Match[str]) -> str:
        return locations.get(match.group(1), "Location unavailable")

    rendered = LOCATION_USE.sub(replace_location, text)
    rendered = rendered.replace(
        r"\input{../../references/author_metadata.tex}",
        r"\input{author_metadata.tex}",
    )
    source_dir = run_dir / "response_source"
    source_dir.mkdir(parents=True)
    rendered_source = source_dir / "response_letter.tex"
    rendered_source.write_text(rendered, encoding="utf-8")
    generated_source = config.references / "author_metadata.tex"
    if not generated_source.exists():
        raise WorkflowError(f"Generated author metadata is missing: {generated_source}")
    generated_target = source_dir / "author_metadata.tex"
    shutil.copy2(generated_source, generated_target)
    result = compile_tex(
        rendered_source,
        run_dir / "response_build",
        config,
        engine_override,
    )
    output = config.round_dir(round_number) / "output" / "response_letter.pdf"
    output.parent.mkdir(exist_ok=True)
    shutil.copy2(result.pdf, output)
    return output
