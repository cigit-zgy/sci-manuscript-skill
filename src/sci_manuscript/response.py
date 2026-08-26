"""Editable response initialization and response-letter PDF compilation."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from . import review
from .compile import compile_tex, publish_file_atomically, stage_cjk_fonts
from .errors import WorkflowError
from .metadata import generate_metadata
from .review_ids import is_review_id
from .templates import resources_root
from .timing import BuildTelemetry
from .workspace import ProjectConfig, artifact_input_digest

LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")
RESPONSE_LATIN_FONT = "Times New Roman"


def ensure_response_latin_font() -> None:
    """Fail closed unless fontconfig resolves the exact response Latin font."""
    matcher = shutil.which("fc-match")
    if matcher is None:
        raise WorkflowError(
            "RESPONSE_FONT_UNAVAILABLE_TIMES_NEW_ROMAN: cannot verify the required "
            "system font because fc-match is unavailable. Install Times New Roman "
            "as a system font and ensure fontconfig can see it."
        )
    result = subprocess.run(
        [matcher, "--format=%{family}\\n", RESPONSE_LATIN_FONT],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    families = {
        family.strip()
        for line in result.stdout.splitlines()
        for family in line.split(",")
        if family.strip()
    }
    if result.returncode != 0 or RESPONSE_LATIN_FONT not in families:
        raise WorkflowError(
            "RESPONSE_FONT_UNAVAILABLE_TIMES_NEW_ROMAN: install Times New Roman "
            "as a system font and ensure fontconfig can see it."
        )


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
            f"Response template must contain one response-body token: {path}"
        )
    if "%%RESPONSE_LETTER%%" in template:
        raise WorkflowError(
            f"Response template must not contain a free response-letter token: {path}"
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
        instructions = r"""% ============================================================
% 逐条回复
% ============================================================
%
% response_letter.pdf 第一页由 package-owned fixed template 唯一生成。
% 本文件只保存逐条回复和可选的 \ReviewReference 声明。
%
"""
    else:
        instructions = r"""% ============================================================
% Point-by-point responses
% ============================================================
%
% The first page of response_letter.pdf is generated only from the
% package-owned fixed template. This file stores point-by-point responses
% and optional \ReviewReference declarations only.
%
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
% 如果后续需要回复编辑的具体意见，请先在 reviewer_comments.md 中填写。
%
% 示例：
%
% [E-1]
% 编辑的具体意见……
%
% \Response{E-1}{
%     编辑回复……
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
        for index, comment in enumerate(block.comments):
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
            if index < len(block.comments) - 1:
                lines.extend(["\\ResponseEntryEnd", ""])
    return "\n".join(lines)


def build_response(
    config: ProjectConfig,
    round_number: int,
    locations: dict[str, str],
    run_dir: Path,
    engine_override: str | None = None,
    telemetry: BuildTelemetry | None = None,
) -> Path:
    """Compile a response copy with automatic marked-manuscript locations."""

    ensure_response_latin_font()

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

    render_stage = (
        telemetry.measure("response_render") if telemetry else contextlib.nullcontext()
    )
    with render_stage:
        response_dir = config.response_dir(round_number)
        blocks = review.parse_reviews(response_dir / "reviewer_comments.md")
        expected_ids = tuple(
            comment.review_id for block in blocks for comment in block.comments
        )
        if not expected_ids:
            raise WorkflowError(
                "No reviewer comments are available: "
                f"{response_dir / 'reviewer_comments.md'}"
            )
        observed = review.parse_response_source(response_dir / "responses.tex")
        responses = {
            review_id: observed.responses.get(review_id, "")
            for review_id in expected_ids
        }
        revised_ids = set(locations).intersection(expected_ids)
        stage = run_dir / "response_source"
        stage.mkdir(parents=True)
        if config.language == "zh":
            stage_cjk_fonts(stage)
        text = _response_template(config.language)
        text = text.replace(
            "%%RESPONSE_BODY%%",
            _body_tex(blocks, config.language, responses, revised_ids),
        )
        staged_source = stage / "response_letter.tex"
        staged_source.write_text(
            LOCATION_USE.sub(replace_location, text), encoding="utf-8"
        )
        generate_metadata(config.round_dir(round_number), stage)
    compile_stage = (
        telemetry.measure("response_compile") if telemetry else contextlib.nullcontext()
    )
    with compile_stage:
        if telemetry is None:
            compiled = compile_tex(
                staged_source,
                run_dir / "response_build",
                config,
                engine_override,
            )
        else:
            compiled = compile_tex(
                staged_source,
                run_dir / "response_build",
                config,
                engine_override,
                telemetry=telemetry,
            )
    output = config.output_dir(round_number) / "response_letter.pdf"
    publish_stage = (
        telemetry.measure("artifact_publish") if telemetry else contextlib.nullcontext()
    )
    with publish_stage:
        published = publish_file_atomically(compiled.pdf, output)
    staged_text = staged_source.read_text(encoding="utf-8")
    response_consistency = bool(
        all(body in staged_text for body in responses.values() if body)
        and not LOCATION_USE.search(staged_text)
        and [
            match.group(1)
            for match in re.finditer(
                r"\\begin\{reviewcomment\}\{([^}]+)\}", staged_text
            )
        ]
        == list(expected_ids)
    )
    audit = {
        "response_source_pdf_consistency": response_consistency,
        "responses_source_sha256": hashlib.sha256(
            (response_dir / "responses.tex").read_bytes()
        ).hexdigest(),
        "reviewer_comments_sha256": hashlib.sha256(
            (response_dir / "reviewer_comments.md").read_bytes()
        ).hexdigest(),
        "response_template_sha256": hashlib.sha256(
            _response_template(config.language).encode("utf-8")
        ).hexdigest(),
        "response_staged_source_sha256": hashlib.sha256(
            staged_source.read_bytes()
        ).hexdigest(),
        "response_build_input_digest": artifact_input_digest(
            config, round_number, published
        ),
        "response_letter_pdf_sha256": hashlib.sha256(
            published.read_bytes()
        ).hexdigest(),
    }
    (run_dir / "response_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not response_consistency:
        raise WorkflowError("RESPONSE_SOURCE_PDF_CONSISTENCY_FAILED")
    return published
