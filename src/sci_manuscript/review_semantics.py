"""Reviewer-provenance alignment for adjacent marked manuscripts.

The user-facing ``\\review{ID}{...}`` wrapper records provenance only. This
module removes that wrapper before diffing, projects its boundaries onto the
direct parent, and inserts identical transparent internal boundaries into both
latexdiff inputs. Consequently, unchanged text inside a reviewer scope remains
ordinary manuscript text; only actual additions inside the scope are classified
as reviewer-linked additions.

For Chinese manuscripts, an internal zero-width source marker is inserted after
CJK characters before latexdiff. The marker exists only in the temporary diff
sources and is removed before compilation. This gives latexdiff stable token
boundaries for Chinese text, including abstracts that contain no whitespace,
without changing the final TeX source or rendered typography.
"""

from __future__ import annotations

import difflib
import re
import shutil
from pathlib import Path

from . import diff as _diff
from .workspace import ProjectConfig, WorkflowError

ReviewScope = tuple[str, int, int]
CJK_DIFF_BOUNDARY = r"\sciCJKDiffBoundary"
_CJK_DIFF_BOUNDARY_PATTERN = re.compile(re.escape(CJK_DIFF_BOUNDARY) + r"\s*\{\s*\}")


def _strip_and_collect_provenance(
    text: str,
    *,
    review_depth: int = 0,
) -> tuple[str, tuple[ReviewScope, ...]]:
    """Strip provenance wrappers and retain review spans in stripped-source offsets."""
    output: list[str] = []
    scopes: list[ReviewScope] = []
    output_length = 0
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "%" and not _diff._is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            end = len(text) if newline == -1 else newline + 1
            chunk = text[cursor:end]
            output.append(chunk)
            output_length += len(chunk)
            cursor = end
            continue
        if text[cursor] == "\\":
            parsed_review = _diff._parse_command_arguments(
                text,
                cursor,
                r"\review",
                2,
            )
            if parsed_review is not None:
                if review_depth:
                    raise WorkflowError(
                        "Nested \\review blocks are ambiguous; combine reviewer IDs "
                        "in one wrapper instead."
                    )
                (raw_ids, body), end = parsed_review
                review_ids = tuple(
                    item.strip() for item in raw_ids.split(",") if item.strip()
                )
                if not review_ids or any(
                    not _diff.is_review_id(item) for item in review_ids
                ):
                    raise WorkflowError(
                        f"Invalid reviewer ID list {raw_ids!r}; expected IDs such as 1-1."
                    )
                stripped_body, nested = _strip_and_collect_provenance(
                    body,
                    review_depth=1,
                )
                if nested:
                    raise WorkflowError("Nested reviewer scopes are not supported.")
                start = output_length
                output.append(stripped_body)
                output_length += len(stripped_body)
                scopes.append((",".join(review_ids), start, output_length))
                cursor = end
                continue
            parsed_user = _diff._parse_command_arguments(
                text,
                cursor,
                r"\user",
                1,
            )
            if parsed_user is not None:
                (body,), end = parsed_user
                stripped_body, nested = _strip_and_collect_provenance(
                    body,
                    review_depth=review_depth,
                )
                output.append(stripped_body)
                output_length += len(stripped_body)
                scopes.extend(nested)
                cursor = end
                continue
        output.append(text[cursor])
        output_length += 1
        cursor += 1
    return "".join(output), tuple(scopes)


def _map_new_boundary_to_old(
    matching_blocks: list[difflib.Match],
    position: int,
    *,
    side: str,
) -> int:
    """Project one current-source review boundary onto the direct parent."""
    previous: difflib.Match | None = None
    following: difflib.Match | None = None
    for block in matching_blocks:
        if block.b <= position <= block.b + block.size:
            return block.a + (position - block.b)
        if block.b + block.size < position:
            previous = block
            continue
        if block.b > position:
            following = block
            break
    if side == "start":
        if previous is not None:
            return previous.a + previous.size
        if following is not None:
            return following.a
    elif side == "end":
        if following is not None:
            return following.a
        if previous is not None:
            return previous.a + previous.size
    else:
        raise WorkflowError(f"Unknown review-boundary side: {side}")
    return 0


def _insert_review_boundaries(text: str, scopes: tuple[ReviewScope, ...]) -> str:
    """Insert transparent internal markers without changing manuscript semantics."""
    result = text
    for ids, start, end in sorted(
        scopes,
        key=lambda item: (item[1], item[2]),
        reverse=True,
    ):
        result = result[:end] + f"{_diff.INTERNAL_REVIEW_END}{{{ids}}}" + result[end:]
        result = (
            result[:start] + f"{_diff.INTERNAL_REVIEW_START}{{{ids}}}" + result[start:]
        )
    return result


def _is_cjk_diff_character(char: str) -> bool:
    """Return whether *char* benefits from an explicit latexdiff token boundary."""
    codepoint = ord(char)
    return (
        0x2E80 <= codepoint <= 0x2FFF
        or 0x3000 <= codepoint <= 0x303F
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0xFF00 <= codepoint <= 0xFFEF
        or 0x20000 <= codepoint <= 0x2FA1F
    )


def _tokenize_cjk_for_diff(text: str) -> str:
    """Add temporary zero-width TeX token boundaries after CJK characters."""
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char == "%" and not _diff._is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            end = len(text) if newline == -1 else newline + 1
            output.append(text[cursor:end])
            cursor = end
            continue
        output.append(char)
        if _is_cjk_diff_character(char):
            output.append(f"{CJK_DIFF_BOUNDARY}{{}}")
        cursor += 1
    return "".join(output)


def paired_review_sources(old_text: str, new_text: str) -> tuple[str, str]:
    """Return aligned direct-parent/current sources for reviewer-aware latexdiff."""
    old_stripped, _ = _strip_and_collect_provenance(old_text)
    new_stripped, new_scopes = _strip_and_collect_provenance(new_text)
    if not new_scopes:
        return old_stripped, new_stripped

    matching_blocks = difflib.SequenceMatcher(
        None,
        old_stripped,
        new_stripped,
        autojunk=False,
    ).get_matching_blocks()
    old_scopes: list[ReviewScope] = []
    previous_new_end = -1
    previous_old_end = -1
    for ids, new_start, new_end in new_scopes:
        if new_start < previous_new_end:
            raise WorkflowError("Reviewer provenance scopes must not overlap.")
        old_start = _map_new_boundary_to_old(
            matching_blocks,
            new_start,
            side="start",
        )
        old_end = _map_new_boundary_to_old(
            matching_blocks,
            new_end,
            side="end",
        )
        if old_start > old_end:
            raise WorkflowError(
                f"Could not align reviewer scope {ids} with the direct parent."
            )
        if old_start < previous_old_end:
            raise WorkflowError(
                f"Reviewer scope {ids} crosses a previous scope after alignment."
            )
        old_scopes.append((ids, old_start, old_end))
        previous_new_end = new_end
        previous_old_end = old_end

    return (
        _insert_review_boundaries(old_stripped, tuple(old_scopes)),
        _insert_review_boundaries(new_stripped, new_scopes),
    )


def _denest_review_boundaries(text: str) -> str:
    """Move provenance boundaries outside both addition and deletion spans."""
    macros = (r"\DIFaddFL", r"\DIFadd", r"\DIFdelFL", r"\DIFdel")
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        candidates = [(text.find(f"{macro}{{", cursor), macro) for macro in macros]
        matches = [item for item in candidates if item[0] != -1]
        if not matches:
            output.append(text[cursor:])
            break
        index, macro = min(matches, key=lambda item: item[0])
        output.append(text[cursor:index])
        content, end = _diff._extract_braced(text, index + len(macro))
        output.append(_diff._split_added_content(content, macro))
        cursor = end

    result = "".join(output)
    for macro in macros:
        cursor = 0
        while True:
            index = result.find(f"{macro}{{", cursor)
            if index < 0:
                break
            content, end = _diff._extract_braced(result, index + len(macro))
            if any(
                marker in content
                for marker in (
                    _diff.INTERNAL_REVIEW_START,
                    _diff.INTERNAL_REVIEW_END,
                    r"\review",
                    r"\user",
                )
            ):
                raise WorkflowError(
                    "Could not safely separate provenance markup from latexdiff output."
                )
            cursor = end
    return result


def _remove_cjk_diff_boundaries(text: str) -> str:
    """Remove temporary CJK token boundaries before TeX compilation."""
    return _CJK_DIFF_BOUNDARY_PATTERN.sub("", text)


def build_marked_manuscript(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None = None,
) -> _diff.MarkedResult:
    """Build a reviewer-aware adjacent marked PDF with aligned provenance scopes."""
    if round_number < 1:
        raise WorkflowError("R0 has no marked manuscript; build its clean PDF instead.")
    previous = config.round_dir(round_number - 1)
    current = config.round_dir(round_number)
    if not previous.is_dir() or not current.is_dir():
        raise WorkflowError(
            f"Revision requires both r{round_number - 1} and r{round_number}."
        )
    if shutil.which("latexdiff") is None:
        raise WorkflowError("latexdiff is required for marked manuscripts.")
    if shutil.which("pdftotext") is None:
        raise WorkflowError("pdftotext is required for revision location extraction.")

    source_dir = run_dir / "marked_source"
    build_dir = run_dir / "marked_build"
    source_dir.mkdir(parents=True)
    roots = (previous, current, config.project)
    old_text, new_text = paired_review_sources(
        _diff._flatten_tex(previous / "manuscript.tex", roots),
        _diff._flatten_tex(current / "manuscript.tex", roots),
    )
    if config.language == "zh" or config.metadata.publisher == "chinese":
        old_text = _tokenize_cjk_for_diff(old_text)
        new_text = _tokenize_cjk_for_diff(new_text)

    old_source = source_dir / "old.tex"
    new_source = source_dir / "new.tex"
    old_source.write_text(old_text, encoding="utf-8")
    new_source.write_text(new_text, encoding="utf-8")
    style = source_dir / "revision_preamble.tex"
    user_style = (config.references / "revision_style.tex").read_text(encoding="utf-8")
    style.write_text(
        f"{user_style}\n{_diff._revision_runtime(config.language)}",
        encoding="utf-8",
    )
    _diff._copy_resources(config, current, source_dir)

    command = [
        shutil.which("latexdiff") or "latexdiff",
        "--encoding=utf8",
        "--packages=none",
        f"--preamble={style}",
        "--disable-citation-markup",
        "--append-safecmd=sciReviewStart,sciReviewEnd,sciCJKDiffBoundary",
        "--ignore-warnings",
        str(old_source),
        str(new_source),
    ]
    if config.metadata.publisher == "chinese":
        command.insert(
            -3,
            f"--append-textcmd={','.join(_diff.CHINESE_TEXT_COMMANDS)}",
        )
    result = _diff.run_command(command, cwd=source_dir)
    marked_source = source_dir / "manuscript_marked.tex"
    denested = _denest_review_boundaries(result.stdout)
    classified = _diff._mark_reviewer_additions(denested)
    math_safe = _diff._separate_inline_math_from_diff_markup(classified)
    final_source = _remove_cjk_diff_boundaries(math_safe)
    marked_source.write_text(final_source, encoding="utf-8")
    compiled = _diff.compile_tex(
        marked_source,
        build_dir,
        config,
        engine_override,
        keep_intermediates=True,
    )
    extracted_text = run_dir / "marked_manuscript.txt"
    _diff.run_command(
        [
            shutil.which("pdftotext") or "pdftotext",
            str(compiled.pdf),
            str(extracted_text),
        ],
        cwd=run_dir,
    )
    if not extracted_text.exists() or extracted_text.stat().st_size == 0:
        raise WorkflowError("Marked PDF text extraction produced no text.")

    locations = _diff._calculate_locations(build_dir)
    output = current / "output" / "manuscript_marked.pdf"
    output.parent.mkdir(exist_ok=True)
    shutil.copy2(compiled.pdf, output)
    return _diff.MarkedResult(pdf=output, locations=locations)


def install() -> None:
    """Install the reviewer-aware builder into public workflow entrypoints."""
    from . import api as _api

    _diff.build_marked_manuscript = build_marked_manuscript
    _api.build_marked_manuscript = build_marked_manuscript
