"""Internal reviewer-comment parsing and response-letter rendering."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from compile import compile_tex
from workspace import TEMPLATES, ProjectConfig, WorkflowError, round_name

REVIEWER_HEADING = re.compile(r"^\s*#\s*Reviewer\s*#?\s*(\d+)\s*$", re.IGNORECASE)
COMMENT_START = re.compile(r"^\s*(\d+)\\?\.\s*(.*)$")
PENDING_RESPONSE = re.compile(r"\\ResponsePending\{([^}]+)\}")
LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")


@dataclass(frozen=True)
class ReviewComment:
    """One numbered reviewer comment with its stable per-round ID."""

    reviewer: int
    number: int
    text: str

    @property
    def review_id(self) -> str:
        """Return the ``reviewer-comment`` ID used in manuscript markup."""
        return f"{self.reviewer}-{self.number}"


@dataclass(frozen=True)
class ReviewBlock:
    """One reviewer's general assessment and numbered comments."""

    reviewer: int
    general_comment: str
    comments: tuple[ReviewComment, ...]


def _collapse(lines: list[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip())


def parse_reviews(path: Path) -> tuple[ReviewBlock, ...]:
    """Parse explicitly designated reviewer Markdown without silent renumbering."""
    if not path.exists():
        raise WorkflowError(f"Reviewer-comments file is missing: {path}")
    blocks: list[ReviewBlock] = []
    reviewer: int | None = None
    general: list[str] = []
    comment_lines: list[str] = []
    comments: list[ReviewComment] = []
    current_number: int | None = None

    def finish_comment() -> None:
        nonlocal comment_lines, current_number
        if reviewer is None or current_number is None:
            return
        comments.append(
            ReviewComment(reviewer, current_number, _collapse(comment_lines))
        )
        comment_lines = []
        current_number = None

    def finish_reviewer() -> None:
        nonlocal general, comments
        if reviewer is None:
            return
        finish_comment()
        expected = list(range(1, len(comments) + 1))
        observed = [comment.number for comment in comments]
        if observed != expected:
            raise WorkflowError(
                f"Reviewer {reviewer} comments must be consecutive from 1; "
                f"observed {observed}."
            )
        if not comments:
            raise WorkflowError(f"Reviewer {reviewer} has no numbered comments.")
        blocks.append(ReviewBlock(reviewer, _collapse(general), tuple(comments)))
        general = []
        comments = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        heading = REVIEWER_HEADING.fullmatch(raw)
        if heading:
            finish_reviewer()
            reviewer = int(heading.group(1))
            continue
        if reviewer is None:
            if raw.strip():
                raise WorkflowError("Text appears before the first reviewer heading.")
            continue
        numbered = COMMENT_START.match(raw)
        if numbered:
            finish_comment()
            current_number = int(numbered.group(1))
            comment_lines = [numbered.group(2)]
        elif current_number is None:
            general.append(raw)
        else:
            comment_lines.append(raw)
    finish_reviewer()
    if not blocks:
        raise WorkflowError("No reviewer blocks were found.")
    return tuple(blocks)


def _escape_latex(value: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in value)


def _body_tex(blocks: tuple[ReviewBlock, ...], language: str) -> str:
    lines: list[str] = []
    for block in blocks:
        reviewer_title = "审稿人" if language == "zh" else "Reviewer"
        general_title = "总体意见" if language == "zh" else "General comment"
        comment_title = "意见" if language == "zh" else "Comment"
        response_title = "回复" if language == "zh" else "Response"
        location_title = "位置" if language == "zh" else "Location"
        lines.extend([f"\\section*{{{reviewer_title} \\#{block.reviewer}}}", ""])
        if block.general_comment:
            lines.extend(
                [
                    f"\\subsection*{{{general_title}}}",
                    f"\\ReviewerComment{{{_escape_latex(block.general_comment)}}}",
                    "",
                ]
            )
        for comment in block.comments:
            lines.extend(
                [
                    f"\\subsection*{{{comment_title} {comment.number}}}",
                    f"\\ReviewerComment{{{_escape_latex(comment.text)}}}",
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
    template = TEMPLATES / "response" / f"response_{response_language}.tex"
    text = template.read_text(encoding="utf-8")
    text = text.replace("%%ROUND%%", round_name(round_number).upper())
    text = text.replace("%%BODY%%", _body_tex(blocks, response_language))
    text = text.replace(
        "%%AUTHOR_METADATA_PATH%%",
        "../references/author_metadata.tex",
    )
    target.write_text(text, encoding="utf-8")
    local_reviews = response_dir / "reviewer_comments.md"
    if reviews.resolve() != local_reviews.resolve():
        shutil.copy2(reviews, local_reviews)
    return target


def pending_response_ids(source: Path) -> tuple[str, ...]:
    """Return unfinished response IDs without matching the macro definition."""
    text = source.read_text(encoding="utf-8")
    return tuple(PENDING_RESPONSE.findall(text))


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

    def replace_location(match: re.Match[str]) -> str:
        return locations.get(match.group(1), "Location unavailable")

    rendered = LOCATION_USE.sub(replace_location, text)
    rendered = rendered.replace(
        r"\input{../references/author_metadata.tex}",
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
