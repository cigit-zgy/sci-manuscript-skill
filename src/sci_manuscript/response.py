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
    if (
        template.count("%%RESPONSE_LETTER%%") != 1
        or template.count("%%RESPONSE_BODY%%") != 1
    ):
        raise WorkflowError(
            "Response template must contain one response-letter token and one "
            f"response-body token: {path}"
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
        instructions = r"""% 回复审稿意见文件。
%
% 使用说明：
% 1. 在 \ResponseLetter{} 中编辑整封致编辑信。
% 2. 在每个 \Response{} 中填写对应意见的回复内容。
% 3. 正文用 \review{}；参考文献 provenance 用 \ReviewReference{}。
% 4. 修改位置由系统自动计算，无需手动填写行号。
% 5. 这些以 % 开头的阅读辅助不会显示在最终 PDF 中。
%
\ResponseLetter{
尊敬的编辑：

感谢您给予我们修改稿件《\ManuscriptTitle》的机会，并考虑将其发表于\JournalName。衷心感谢编辑和审稿人对本稿件的认真评阅以及富有建设性的建议。

以下按照编辑和审稿人的意见列出相应回复；涉及正文修改的意见，其修改位置也在相应回复里标注。

此致

敬礼！
}
"""  # noqa: RUF001
    else:
        instructions = r"""% Reviewer-response source.
%
% Instructions:
% 1. Edit the complete editor letter in \ResponseLetter{}.
% 2. Enter each point-by-point reply in its \Response{} entry.
% 3. Use \review{} for prose and \ReviewReference{} for bibliography provenance.
% 4. Revision locations are calculated automatically; do not enter line numbers.
% 5. Reading aids beginning with % are not rendered in the final PDF.
%
\ResponseLetter{
Dear Editor,

Thank you for the opportunity to revise our manuscript entitled ``\ManuscriptTitle'' and for considering it for publication in \JournalName. We sincerely appreciate the careful evaluation and constructive comments provided by the Editor and Reviewers.

Our point-by-point responses are provided below. For comments involving revisions to the manuscript, the corresponding locations are also indicated in the respective responses.

Sincerely,
}
"""
    sections: list[str] = []
    saw_editor = False
    for block in blocks:
        review_ids = [comment.review_id for comment in block.comments]
        if not review_ids:
            continue
        saw_editor = saw_editor or block.prefix == "E"
        if config.language == "zh":
            if block.prefix == "E":
                title = "编辑"
            elif block.prefix == "AE":
                title = "副编辑"
            else:
                title = f"审稿人 #{block.prefix}"
        else:
            title = block.title
        aid = ["% " + "=" * 60, f"% {title}", "% " + "=" * 60, "%"]
        if block.summary:
            general = "总体意见" if config.language == "zh" else "General comment"
            aid.append(f"% {general}:")
            aid.extend(f"% {paragraph}" for paragraph in block.summary)
            aid.append("%")
        for comment in block.comments:
            aid.append(f"% [{comment.review_id}]")
            aid.extend(f"% {paragraph}" for paragraph in comment.paragraphs)
            aid.extend(["%", f"\\Response{{{comment.review_id}}}{{", "}", ""])
        sections.append("\n".join(aid).rstrip())
    if not saw_editor:
        if config.language == "zh":
            editor_example = r"""% ============================================================
% 编辑
% ============================================================
%
% 如果后续需要回复编辑意见，请先在 reviewer_comments.md 中填写。
%
% 示例：
% [E-1]
% 编辑的具体意见……
% \Response{E-1}{
% 感谢编辑的意见。……
% }
"""  # noqa: RUF001
        else:
            editor_example = r"""% ============================================================
% Editor
% ============================================================
%
% If an editor response is later required, first enter the comment in reviewer_comments.md.
%
% Example:
% [E-1]
% The editor's specific comment...
% \Response{E-1}{
% Thank you for the editor's comment...
% }
"""
        sections.insert(0, editor_example.rstrip())
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
    observed = review.parse_response_source(response_dir / "responses.tex")
    responses = {
        review_id: observed.responses.get(review_id, "") for review_id in expected_ids
    }
    revised_ids = set(locations).intersection(expected_ids)
    stage = run_dir / "response_source"
    stage.mkdir(parents=True)
    if config.language == "zh":
        stage_cjk_fonts(stage)
    text = _response_template(config.language)
    text = text.replace("%%RESPONSE_LETTER%%", observed.letter)
    text = text.replace(
        "%%RESPONSE_BODY%%", _body_tex(blocks, config.language, responses, revised_ids)
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
