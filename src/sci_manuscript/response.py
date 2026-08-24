"""Editable response initialization and response-letter PDF compilation."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .compile import compile_tex, stage_cjk_fonts
from .errors import WorkflowError
from .metadata import generate_metadata
from .review import (
    ReviewAuditResult,
    ReviewBlock,
    ReviewComment,
    audit_reviews,
    parse_response_entries,
    parse_responses,
    parse_reviews,
    pending_response_ids,
    review_ids_from_sources,
    validate_response_links,
)
from .review_ids import is_review_id, validate_review_id_list
from .templates import resources_root
from .workspace import ProjectConfig

LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")

__all__ = [
    "ReviewAuditResult",
    "ReviewBlock",
    "ReviewComment",
    "audit_reviews",
    "build_response",
    "init_response",
    "is_review_id",
    "parse_response_entries",
    "parse_responses",
    "parse_reviews",
    "pending_response_ids",
    "validate_response_links",
    "validate_review_id_list",
]


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


def init_response(config: ProjectConfig, round_number: int) -> Path:
    """Create the editable response source with language-specific comments."""
    if round_number < 1:
        raise WorkflowError("r00 does not have a reviewer response.")
    response_dir = config.response_dir(round_number)
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
    if config.language == "zh":
        instructions = """% 回复审稿意见文件。
%
% 使用说明：
% 1. 每条回复应对应 reviewer_comments.md 中的一条审稿意见。
% 2. review ID 由系统管理，请勿随意修改。
% 3. manuscript 中的 \\review{} 用于关联审稿意见与实际修改。
% 4. 修改位置由系统自动计算。
% 5. 未完成回复请保留系统规定的 \\ResponsePending{} 状态。
% 6. 这些 LaTeX 注释不会出现在最终 PDF 中。
"""  # noqa: RUF001
    else:
        instructions = """% Reviewer-response source.
%
% Instructions:
% 1. Match every response to one review comment in reviewer_comments.md.
% 2. Review IDs are managed by the system; do not change them arbitrarily.
% 3. Use \\review{} in the manuscript to link a comment to the actual revision.
% 4. Revision locations are calculated automatically.
% 5. Keep the required \\ResponsePending{} state for unfinished responses.
% 6. These LaTeX comments are not rendered in the final PDF.
"""
    target.write_text(
        instructions
        + (("\n".join(("", "\n\n".join(entries))) + "\n") if entries else ""),
        encoding="utf-8",
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
            title = {"E": "编辑", "AE": "副编辑"}.get(
                block.prefix, f"审稿人 #{block.prefix}"
            )
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
    response_dir = config.response_dir(round_number)
    blocks = parse_reviews(response_dir / "reviewer_comments.md")
    expected_ids = tuple(
        comment.review_id for block in blocks for comment in block.comments
    )
    if not expected_ids:
        raise WorkflowError(
            f"No reviewer comments are available: {response_dir / 'reviewer_comments.md'}"
        )
    observed = parse_response_entries(response_dir / "responses.tex")
    responses = {
        review_id: observed.get(review_id, f"\\ResponsePending{{{review_id}}}")
        for review_id in expected_ids
    }
    pending = pending_response_ids(responses)
    if pending and not allow_placeholders:
        raise WorkflowError(
            "Response source still contains unfinished responses: " + ", ".join(pending)
        )
    revised_ids = review_ids_from_sources(config, round_number).intersection(
        expected_ids
    )
    missing_locations = sorted(
        review_id
        for review_id in revised_ids
        if review_id not in locations
        or locations[review_id] in {"Location unavailable", "位置不可用"}
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
        unavailable = (
            "位置不可用" if config.language == "zh" else "Location unavailable"
        )
        return locations.get(review_id, unavailable)

    staged_source = stage / "response_letter.tex"
    staged_source.write_text(LOCATION_USE.sub(replace_location, text), encoding="utf-8")
    generate_metadata(config.project, config.round_dir(round_number), stage)
    compiled = compile_tex(
        staged_source,
        run_dir / "response_build",
        config,
        engine_override,
    )
    output = config.output_dir(round_number) / "response_letter.pdf"
    output.parent.mkdir(exist_ok=True)
    shutil.copy2(compiled.pdf, output)
    return output
