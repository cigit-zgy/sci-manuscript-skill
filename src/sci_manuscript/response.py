"""Editable response initialization and response-letter PDF compilation."""

from __future__ import annotations

import re
from pathlib import Path

from . import review
from .compile import compile_tex, publish_file_atomically, stage_cjk_fonts
from .errors import WorkflowError
from .metadata import generate_metadata
from .review_ids import is_review_id
from .templates import resources_root
from .workspace import ProjectConfig

LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")


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


def init_response(config: ProjectConfig, round_number: int) -> Path | None:
    """Create the editable response source with language-specific comments."""
    if round_number < 1:
        raise WorkflowError("r00 does not have a reviewer response.")
    response_dir = config.response_dir(round_number)
    blocks = review.parse_reviews(response_dir / "reviewer_comments.md")
    target = response_dir / "responses.tex"
    if target.exists():
        raise WorkflowError(f"Response source already exists: {target}")
    if config.language == "zh":
        instructions = """% 回复审稿意见文件。
%
% 使用说明：
% 1. 请在每个 \\Response{} 中填写对应意见的回复内容。
% 2. manuscript 中使用 \\review{} 标记与该意见对应的实际修改内容。
% 3. 修改位置由系统自动计算，无需手动填写行号。
% 4. 如果某条意见只需回复而不修改正文，可仅填写回复内容。
% 5. 这些 LaTeX 注释不会显示在最终 PDF 中。
%
% 示例：
% \\Response{1-1}{
% 感谢审稿人的意见。我们已根据建议进行了修改。
% }
"""  # noqa: RUF001
    else:
        instructions = """% Reviewer-response source.
%
% Instructions:
% 1. Enter the reply body in each \\Response{} entry.
% 2. Use \\review{} in the manuscript for the corresponding revision content.
% 3. Revision line numbers are calculated automatically; do not enter them here.
% 4. For a response-only comment, enter the reply without adding \\review{}.
% 5. These LaTeX comments are not rendered in the final PDF.
%
% Example:
% \\Response{1-1}{
% Thank you for the comment. We revised the manuscript accordingly.
% }
"""
    sections: list[str] = []
    for block in blocks:
        review_ids = [comment.review_id for comment in block.comments]
        if not review_ids:
            continue
        if config.language == "zh":
            if block.prefix == "E":
                title = "编辑"
            elif block.prefix == "AE":
                title = "副编辑"
            else:
                title = f"审稿人 #{block.prefix}"
        else:
            title = block.title
        entries = "\n\n".join(
            f"\\Response{{{review_id}}}{{\n}}" for review_id in review_ids
        )
        sections.append(f"% {title}\n\n{entries}")
    body = "\n\n".join(sections)
    if not body:
        return None
    target.write_text(
        instructions + (("\n" + body + "\n") if body else ""), encoding="utf-8"
    )
    return target


def ensure_response_source(config: ProjectConfig, round_number: int) -> Path | None:
    """Create responses.tex once actual detailed comments are available."""
    target = config.response_dir(round_number) / "responses.tex"
    if target.is_file():
        return target
    return init_response(config, round_number)


def _body_tex(
    blocks: tuple[review.ReviewBlock, ...],
    language: str,
    responses: dict[str, str],
    revised_ids: set[str],
) -> str:
    lines: list[str] = []
    for block in blocks:
        if not block.comments and not block.summary:
            continue
        title = block.title
        if language == "zh":
            if block.prefix == "E":
                title = "编辑"
            elif block.prefix == "AE":
                title = "副编辑"
            else:
                title = f"审稿人 #{block.prefix}"
        general_title = "总体意见" if language == "zh" else "General comment"
        lines.extend([f"\\ResponseSection{{{_escape_latex(title)}}}", ""])
        if block.summary:
            lines.extend([f"\\begin{{generalcomment}}[{general_title}]"])
            lines.extend(_comment_tex(block.summary))
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
) -> Path:
    """Compile a response copy with automatic marked-manuscript locations."""
    response_dir = config.response_dir(round_number)
    blocks = review.parse_reviews(response_dir / "reviewer_comments.md")
    expected_ids = tuple(
        comment.review_id for block in blocks for comment in block.comments
    )
    if not expected_ids:
        raise WorkflowError(
            f"No reviewer comments are available: {response_dir / 'reviewer_comments.md'}"
        )
    observed = review.parse_response_entries(response_dir / "responses.tex")
    responses = {review_id: observed.get(review_id, "") for review_id in expected_ids}
    revised_ids = review.review_ids_from_sources(config, round_number).intersection(
        expected_ids
    )
    missing_locations = sorted(
        review_id for review_id in revised_ids if review_id not in locations
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
        "%%RESPONSE_BODY%%",
        _body_tex(blocks, config.language, responses, revised_ids),
    )

    def replace_location(match: re.Match[str]) -> str:
        review_id = match.group(1)
        if not is_review_id(review_id):
            raise WorkflowError(f"Invalid response location ID: {review_id}")
        try:
            return locations[review_id]
        except KeyError as exc:
            raise WorkflowError(
                f"Marked manuscript location is missing for: {review_id}"
            ) from exc

    staged_source = stage / "response_letter.tex"
    staged_source.write_text(LOCATION_USE.sub(replace_location, text), encoding="utf-8")
    generate_metadata(config.round_dir(round_number), stage)
    compiled = compile_tex(
        staged_source,
        run_dir / "response_build",
        config,
        engine_override,
    )
    output = config.output_dir(round_number) / "response_letter.pdf"
    return publish_file_atomically(compiled.pdf, output)
