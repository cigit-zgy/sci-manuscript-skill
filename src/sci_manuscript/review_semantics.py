"""Reviewer-aware adjacent marked-manuscript generation.

The user-facing ``\\review{ID}{...}`` wrapper is provenance only. The direct
parent is diffed without provenance wrappers. In the current source, review
wrappers become transparent start/end markers. Latexdiff first determines the
actual additions and deletions; only additions between those markers are then
reclassified as reviewer-linked green changes. Unchanged text inside a review
scope therefore remains ordinary manuscript text.

Chinese manuscripts additionally receive temporary zero-width source markers
after CJK characters before latexdiff. These markers improve token boundaries
for Chinese text without whitespace, including abstracts, and are removed before
TeX compilation.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import diff as _diff
from .workspace import ProjectConfig, WorkflowError, strip_provenance_wrappers

CJK_DIFF_BOUNDARY = r"\sciCJKDiffBoundary"
_CJK_DIFF_BOUNDARY_PATTERN = re.compile(re.escape(CJK_DIFF_BOUNDARY) + r"\s*\{\s*\}")


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
    """Return parent/current sources with provenance affecting classification only."""
    return (
        strip_provenance_wrappers(old_text),
        _diff._expand_provenance_wrappers(new_text),
    )


def _remove_cjk_diff_boundaries(text: str) -> str:
    """Remove temporary CJK token boundaries before TeX compilation."""
    return _CJK_DIFF_BOUNDARY_PATTERN.sub("", text)


def build_marked_manuscript(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None = None,
) -> _diff.MarkedResult:
    """Build a reviewer-aware adjacent marked PDF."""
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
    denested = _diff._denest_provenance(result.stdout)
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
