"""Editable response initialization and response-letter PDF compilation."""

from __future__ import annotations

import contextlib
import hashlib
import json
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import review
from .compile import (
    SciState,
    SciStateEvent,
    compile_tex,
    parse_sci_state,
    publish_file_atomically,
    resolve_engine,
    stage_cjk_fonts,
)
from .errors import WorkflowError
from .metadata import generate_metadata
from .review_ids import is_review_id
from .templates import resources_root
from .timing import BuildTelemetry
from .workspace import (
    ProjectConfig,
    artifact_input_digest,
    author_library_source_for_round,
)

LOCATION_USE = re.compile(r"\\ReviewLocation\{([^}]+)\}")
RESPONSE_LATIN_FONT = "Times New Roman"
_FONT_POLICIES = {
    "Darwin": (
        "macOS",
        ("Times New Roman", "Times", "TeX Gyre Termes"),
        ("Songti SC", "STSong", "Noto Serif CJK SC"),
    ),
    "Windows": (
        "Windows",
        ("Times New Roman", "Cambria", "Georgia"),
        ("SimSun", "NSimSun", "Noto Serif CJK SC"),
    ),
    "Linux": (
        "Linux",
        (
            "Times New Roman",
            "TeX Gyre Termes",
            "Liberation Serif",
            "Nimbus Roman",
        ),
        ("Noto Serif CJK SC", "Source Han Serif SC", "FandolSong"),
    ),
}


@dataclass(frozen=True)
class ResponseFontResolution:
    """TeX-verified correspondence font selection for one build."""

    platform: str
    latin_preferred: str
    latin_resolved: str
    latin_fallback: bool
    cjk_resolved: str | None


@dataclass(frozen=True, slots=True)
class ResponseTexRegistry:
    """Expected package events for one compiled response letter."""

    corresponding_author_ids: tuple[str, ...]
    comment_ids: tuple[str, ...]
    response_hashes: tuple[tuple[str, str], ...]
    location_hashes: tuple[tuple[str, str], ...]

    def events(self) -> tuple[SciStateEvent, ...]:
        """Return the exact deterministic TeX event sequence."""
        response_by_id = dict(self.response_hashes)
        location_by_id = dict(self.location_hashes)
        events = [
            SciStateEvent("RESPONSE_SCHEMA", ("1",)),
            SciStateEvent("TEMPLATE", ("1",)),
            *(
                SciStateEvent("CORRESPONDENCE", (author_id,))
                for author_id in self.corresponding_author_ids
            ),
        ]
        for review_id in self.comment_ids:
            events.append(SciStateEvent("COMMENT", (review_id,)))
            events.append(
                SciStateEvent("RESPONSE", (review_id, response_by_id[review_id]))
            )
            if review_id in location_by_id:
                events.append(
                    SciStateEvent("LOCATION", (review_id, location_by_id[review_id]))
                )
        return tuple(events)


def validate_response_tex_state(
    expected: ResponseTexRegistry,
    emitted: SciState,
) -> bool:
    """Require exact source-registry equality with TeX-emitted response state."""
    if emitted.document != "response" or emitted.events != expected.events():
        raise WorkflowError(
            "RESPONSE_TEX_STATE_CONSISTENCY_FAILED: expected and emitted "
            "response registries differ."
        )
    return True


def build_response_tex_registry(
    corresponding_author_ids: tuple[str, ...],
    comment_ids: tuple[str, ...],
    responses: dict[str, str],
    locations: dict[str, str],
) -> ResponseTexRegistry:
    """Build the source-owned expected registry without copying prose into TeX state."""
    if set(responses) != set(comment_ids):
        raise WorkflowError(
            "RESPONSE_SOURCE_REGISTRY_INCOMPLETE: response IDs do not match comments."
        )
    if not set(locations).issubset(comment_ids):
        raise WorkflowError(
            "RESPONSE_SOURCE_REGISTRY_INCOMPLETE: location IDs do not match comments."
        )

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    return ResponseTexRegistry(
        corresponding_author_ids=corresponding_author_ids,
        comment_ids=comment_ids,
        response_hashes=tuple(
            (review_id, digest(responses[review_id])) for review_id in comment_ids
        ),
        location_hashes=tuple(
            (review_id, digest(locations[review_id]))
            for review_id in comment_ids
            if review_id in locations
        ),
    )


def response_font_candidates(
    system_name: str,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Return the frozen serif candidate order for one operating system."""
    try:
        return _FONT_POLICIES[system_name]
    except KeyError as exc:
        raise WorkflowError(
            f"RESPONSE_FONT_PLATFORM_UNSUPPORTED: platform={system_name}"
        ) from exc


def _cjk_font_setup(candidate: str, root: Path) -> str:
    """Render a xeCJK setup for an installed font or staged Fandol fallback."""
    if candidate == "FandolSong" and (root / "FandolSong-Regular.otf").is_file():
        return r"\setCJKmainfont[Path=./]{FandolSong-Regular.otf}"
    return rf"\setCJKmainfont{{{candidate}}}"


def _font_usable_by_tex(
    config: ProjectConfig,
    probe_root: Path,
    kind: str,
    candidate: str,
    engine_override: str | None,
    telemetry: BuildTelemetry | None,
) -> bool:
    """Ask the actual correspondence TeX engine whether one font is usable."""
    selected = resolve_engine(config, engine_override)
    slug = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")
    candidate_root = probe_root / f"{kind}-{slug}"
    output = candidate_root / "output"
    output.mkdir(parents=True, exist_ok=True)
    if kind == "cjk":
        stage_cjk_fonts(candidate_root)
    setup = rf"\setmainfont{{{candidate}}}"
    packages = r"\usepackage{fontspec}"
    visible = "Response font probe"
    if kind == "cjk":
        packages += "\n" + r"\usepackage{xeCJK}"
        setup = _cjk_font_setup(candidate, candidate_root)
        visible = "中文字体测试"
    source = candidate_root / "font_probe.tex"
    source.write_text(
        "\\documentclass{article}\n"
        f"{packages}\n"
        f"{setup}\n"
        "\\begin{document}\n"
        f"{visible}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    if selected == "tectonic":
        command = [
            shutil.which("tectonic") or "tectonic",
            "-X",
            "compile",
            f"--outdir={output}",
            str(source),
        ]
    else:
        if shutil.which("xelatex") is None:
            return False
        command = [
            shutil.which("latexmk") or "latexmk",
            "-xelatex",
            f"-outdir={output}",
            "-interaction=nonstopmode",
            "-halt-on-error",
            str(source),
        ]
    if telemetry is not None:
        telemetry.latex_invocations += 1
    result = subprocess.run(
        command,
        cwd=candidate_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    (candidate_root / "font_probe.log").write_text(
        result.stdout + result.stderr,
        encoding="utf-8",
    )
    return result.returncode == 0 and (output / "font_probe.pdf").is_file()


def resolve_response_fonts(
    config: ProjectConfig,
    probe_root: Path,
    engine_override: str | None = None,
    telemetry: BuildTelemetry | None = None,
) -> ResponseFontResolution:
    """Resolve the first TeX-usable platform serif fonts, or fail closed."""
    platform_name, latin_candidates, cjk_candidates = response_font_candidates(
        platform.system()
    )

    def resolve(kind: str, candidates: tuple[str, ...]) -> str:
        for candidate in candidates:
            if _font_usable_by_tex(
                config,
                probe_root,
                kind,
                candidate,
                engine_override,
                telemetry,
            ):
                return candidate
        tried = ", ".join(candidates)
        raise WorkflowError(
            f"RESPONSE_{kind.upper()}_FONT_UNAVAILABLE: platform={platform_name}; "
            f"candidate fonts tried: {tried}"
        )

    latin = resolve("latin", latin_candidates)
    cjk = resolve("cjk", cjk_candidates) if config.language == "zh" else None
    return ResponseFontResolution(
        platform=platform_name,
        latin_preferred=RESPONSE_LATIN_FONT,
        latin_resolved=latin,
        latin_fallback=latin != RESPONSE_LATIN_FONT,
        cjk_resolved=cjk,
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
    if template.count("%%RESPONSE_CORRESPONDENCE_STATE%%") != 1:
        raise WorkflowError(
            f"Response template must contain one correspondence-state token: {path}"
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
    registry: ResponseTexRegistry,
) -> str:
    response_hashes = dict(registry.response_hashes)
    location_hashes = dict(registry.location_hashes)
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
                    f"\\SCIStateComment{{{comment.review_id}}}",
                    f"\\begin{{reviewcomment}}{{{_escape_latex(comment.review_id)}}}",
                    *_comment_tex(comment.paragraphs),
                    "\\end{reviewcomment}",
                    f"\\SCIStateResponse{{{comment.review_id}}}"
                    f"{{{response_hashes[comment.review_id]}}}",
                    "\\begin{response}",
                    responses[comment.review_id],
                    "\\end{response}",
                    "",
                ]
            )
            if comment.review_id in revised_ids:
                lines.extend(
                    [
                        f"\\SCIStateLocation{{{comment.review_id}}}"
                        f"{{{location_hashes[comment.review_id]}}}",
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
        selection = generate_metadata(
            config.round_dir(round_number),
            stage,
            author_library_source_for_round(config, round_number),
        )
        font_resolution = resolve_response_fonts(
            config,
            run_dir / "font_resolution",
            engine_override,
            telemetry,
        )
        text = _response_template(config.language)
        text = text.replace(
            "%%RESPONSE_LATIN_FONT_SETUP%%",
            rf"\setmainfont{{{font_resolution.latin_resolved}}}",
        )
        if font_resolution.cjk_resolved is not None:
            text = text.replace(
                "%%RESPONSE_CJK_FONT_SETUP%%",
                _cjk_font_setup(font_resolution.cjk_resolved, stage),
            )
        active_locations = {
            key: value for key, value in locations.items() if key in revised_ids
        }
        registry = build_response_tex_registry(
            tuple(author.author_id for author in selection.corresponding_authors),
            expected_ids,
            responses,
            active_locations,
        )
        text = text.replace(
            "%%RESPONSE_CORRESPONDENCE_STATE%%",
            "\n".join(
                f"\\SCIStateCorrespondence{{{author_id}}}"
                for author_id in registry.corresponding_author_ids
            ),
        )
        text = text.replace(
            "%%RESPONSE_BODY%%",
            _body_tex(blocks, config.language, responses, revised_ids, registry),
        )
        staged_source = stage / "response_letter.tex"
        staged_source.write_text(
            LOCATION_USE.sub(replace_location, text), encoding="utf-8"
        )
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
                force_xelatex=True,
                keep_intermediates=True,
            )
        else:
            compiled = compile_tex(
                staged_source,
                run_dir / "response_build",
                config,
                engine_override,
                force_xelatex=True,
                keep_intermediates=True,
                telemetry=telemetry,
            )
    staged_text = staged_source.read_text(encoding="utf-8")
    source_registry_complete = bool(
        all(body in staged_text for body in responses.values() if body)
        and not LOCATION_USE.search(staged_text)
        and "%%RESPONSE_CORRESPONDENCE_STATE%%" not in staged_text
        and [
            match.group(1)
            for match in re.finditer(
                r"\\begin\{reviewcomment\}\{([^}]+)\}", staged_text
            )
        ]
        == list(expected_ids)
    )
    if not source_registry_complete:
        raise WorkflowError(
            "RESPONSE_SOURCE_REGISTRY_INCOMPLETE: staged source composition differs "
            "from the expected response registry."
        )
    state_stage = (
        telemetry.measure("tex_state_parse") if telemetry else contextlib.nullcontext()
    )
    with state_stage:
        if compiled.state.sci is None:
            raise WorkflowError(
                "RESPONSE_TEX_STATE_CONSISTENCY_FAILED: SCI sidecar is missing."
            )
        emitted_state = parse_sci_state(compiled.state.sci, "response")
        response_tex_state_consistency = validate_response_tex_state(
            registry, emitted_state
        )
    output = config.output_dir(round_number) / "response_letter.pdf"
    audit = {
        "response_latin_font": {
            "preferred": font_resolution.latin_preferred,
            "resolved": font_resolution.latin_resolved,
            "fallback": font_resolution.latin_fallback,
            "platform": font_resolution.platform,
        },
        "response_cjk_font": {
            "resolved": font_resolution.cjk_resolved,
            "platform": font_resolution.platform,
        },
        "response_source_registry_complete": source_registry_complete,
        "response_tex_sidecar_registry_complete": bool(emitted_state.events),
        "response_tex_state_consistency": response_tex_state_consistency,
        "response_tex_state_issues": [],
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
        "response_sci_sha256": hashlib.sha256(
            compiled.state.sci.read_bytes()
        ).hexdigest(),
        "response_build_input_digest": artifact_input_digest(
            config, round_number, output, engine_override
        ),
        "response_letter_pdf_sha256": hashlib.sha256(
            compiled.pdf.read_bytes()
        ).hexdigest(),
    }
    (run_dir / "response_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    publish_stage = (
        telemetry.measure("artifact_publish") if telemetry else contextlib.nullcontext()
    )
    with publish_stage:
        published = publish_file_atomically(compiled.pdf, output)
    return published
