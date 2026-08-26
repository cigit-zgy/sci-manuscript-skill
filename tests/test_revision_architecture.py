"""Future-facing contracts for the current-layout marked architecture."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sci_manuscript.diff import (
    _locate_additions,
    _mask_overridden_frontmatter_fields,
    extract_addition_evidence,
    normalized_block_hash,
    prepare_change_detection_sources,
    run_latexdiff,
)
from sci_manuscript.provenance import extract_provenance
from sci_manuscript.revision_render import (
    HighlightSpan,
    apply_highlights,
    equation_spans,
    replace_special_spans,
    strip_highlight_markup,
    suppress_exact_moves,
)

STYLE_BEGIN = "% SCI_DIFF_STYLE_BEGIN"
STYLE_END = "% SCI_DIFF_STYLE_END"


def _detector_preamble(tmp_path: Path) -> Path:
    preamble = tmp_path / "detector_preamble.tex"
    preamble.write_text(
        "\\providecommand{\\DIFadd}[1]{#1}\n"
        "\\providecommand{\\DIFaddbegin}{}\n"
        "\\providecommand{\\DIFaddend}{}\n"
        "\\providecommand{\\DIFaddFL}[1]{#1}\n"
        "\\providecommand{\\DIFaddbeginFL}{}\n"
        "\\providecommand{\\DIFaddendFL}{}\n",
        encoding="utf-8",
    )
    return preamble


def _structural_revision(
    tmp_path: Path,
    parent_body: str,
    current_body: str,
) -> tuple[str, list[HighlightSpan], int]:
    if shutil.which("latexdiff") is None:
        pytest.skip("latexdiff is required for this targeted synthetic contract")
    prefix = (
        "\\documentclass{article}\n"
        "\\newcommand{\\bicaption}[2]{#1 #2}\n"
        "\\begin{document}\n"
    )
    suffix = "\n\\end{document}\n"
    parent_text = prefix + parent_body + suffix
    current = extract_provenance(prefix + current_body + suffix)
    parent = tmp_path / "structural_parent.tex"
    current_path = tmp_path / "structural_current.tex"
    output = tmp_path / "structural_evidence.tex"
    parent.write_text(parent_text, encoding="utf-8")
    current_path.write_text(current.text, encoding="utf-8")
    run_latexdiff(parent, current_path, output, preamble=_detector_preamble(tmp_path))
    spans, unresolved = _locate_additions(output.read_text(), current)
    assert unresolved == ()
    spans, moves = suppress_exact_moves(parent_text, current.text, spans, current)
    displays = equation_spans(parent_text, current, spans)
    spans = replace_special_spans(spans, displays)
    return apply_highlights(current.text, spans), spans, moves


def test_current_source_is_the_only_layout_authority() -> None:
    parent = (
        r"\begin{document}"
        r"\subsection{Deleted parent structure}Old text."
        r"\end{document}"
    )
    current = (
        r"\begin{document}"
        r"\review{1-1}{Current text.}"
        r"\end{document}"
    )

    detection_parent, provenance = prepare_change_detection_sources(parent, current)

    assert r"\subsection{Deleted parent structure}" in detection_parent
    assert r"\subsection{Deleted parent structure}" not in provenance.text
    assert provenance.text == r"\begin{document}Current text.\end{document}"
    assert provenance.review_spans[0].review_ids == ("1-1",)


def test_exact_normalized_block_identity_is_the_complete_move_policy() -> None:
    original = "Moved scientific block.\n% source note\n"
    moved = "  Moved   scientific block.  "
    rewritten = "Moved revised scientific block."

    assert normalized_block_hash(original) == normalized_block_hash(moved)
    assert normalized_block_hash(original) != normalized_block_hash(rewritten)


def test_latexdiff_addition_parser_preserves_nested_tex() -> None:
    evidence = extract_addition_evidence(
        r"Before \DIFdel{old \textit{term}}\DIFadd{new \textit{term}} after."
    )

    assert [item.content for item in evidence] == [r"new \textit{term}"]


def test_addition_locator_restores_latexdiff_current_comment_prefix() -> None:
    current = extract_provenance("Before。\n% /// source note\n需要强调的是, after")
    evidence = "\\DIFadd{。\n%DIF >  /// source note\n需要强调的是, }"

    spans, unresolved = _locate_additions(evidence, current)

    assert unresolved == ()
    assert len(spans) == 1
    assert current.text[spans[0].start : spans[0].end] == (
        "。\n% /// source note\n需要强调的是, "
    )


def test_latexdiff_invocation_produces_change_evidence(tmp_path: Path) -> None:
    if shutil.which("latexdiff") is None:
        pytest.skip("latexdiff is required for this targeted synthetic contract")
    parent = tmp_path / "parent.tex"
    current = tmp_path / "current.tex"
    output = tmp_path / "latexdiff_evidence.tex"
    parent.write_text(
        r"\documentclass{article}\begin{document}Old text.\end{document}",
        encoding="utf-8",
    )
    current.write_text(
        r"\documentclass{article}\begin{document}Current text.\end{document}",
        encoding="utf-8",
    )

    evidence = run_latexdiff(parent, current, output)

    assert output.is_file()
    assert any("Current" in item.content for item in evidence)
    assert "Old text" not in output.read_text(encoding="utf-8")


def test_marked_runtime_has_no_deletion_renderer() -> None:
    runtime = (
        Path(__file__).resolve().parents[1]
        / "src/sci_manuscript/resources/revision/marked_runtime.tex"
    ).read_text(encoding="utf-8")

    assert r"\DIFdel" not in runtime
    assert "RevisionDeleted" not in runtime
    assert "sout" not in runtime


def test_last_definition_wins_projection_preserves_offsets_and_newlines() -> None:
    source = (
        "\\begin{abstract}\nInactive text.\n\\end{abstract}\n\n"
        "\\begin{abstract}\nActive text.\n\\end{abstract}\n"
        "\\keywords{inactive}\n\\keywords{active}\n"
    )

    projected, shadowed = _mask_overridden_frontmatter_fields(source, "chinese")

    assert shadowed == 2
    assert len(projected) == len(source)
    assert projected.count("\n") == source.count("\n")
    assert "Inactive text." not in projected
    assert "Active text." in projected
    assert r"\keywords{inactive}" not in projected
    assert r"\keywords{active}" in projected


def test_non_chinese_projection_never_assumes_last_definition_wins() -> None:
    source = (
        r"\begin{abstract}First.\end{abstract}"
        r"\begin{abstract}Second.\end{abstract}"
    )

    projected, shadowed = _mask_overridden_frontmatter_fields(source, "elsevier")

    assert projected == source
    assert shadowed == 0


def test_active_abstract_additions_map_past_shadowed_definition(
    tmp_path: Path,
) -> None:
    if shutil.which("latexdiff") is None:
        pytest.skip("latexdiff is required for this targeted synthetic contract")
    parent_text = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{abstract}Shared prose remains black. Old tail.\\end{abstract}\n"
        "\\end{document}\n"
    )
    current_text = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{abstract}Inactive overwritten draft.\\end{abstract}\n"
        "\\begin{abstract}Shared prose remains black. New tail.\\end{abstract}\n"
        "\\end{document}\n"
    )
    provenance = extract_provenance(current_text)
    detector_parent, _ = _mask_overridden_frontmatter_fields(parent_text, "chinese")
    detector_current, _ = _mask_overridden_frontmatter_fields(
        provenance.text, "chinese"
    )
    parent = tmp_path / "parent.tex"
    current = tmp_path / "current.tex"
    output = tmp_path / "evidence.tex"
    parent.write_text(detector_parent, encoding="utf-8")
    current.write_text(detector_current, encoding="utf-8")

    run_latexdiff(parent, current, output, preamble=_detector_preamble(tmp_path))
    spans, unresolved = _locate_additions(
        output.read_text(encoding="utf-8"), provenance, detector_current
    )
    marked = apply_highlights(provenance.text, spans)

    inactive_start = provenance.text.index("Inactive overwritten draft.")
    active_start = provenance.text.index("Shared prose remains black.")
    assert unresolved == ()
    assert not any(span.start <= inactive_start < span.end for span in spans)
    assert not any(span.start <= active_start < span.end for span in spans)
    assert r"Shared prose remains black. \DIFadd{New} tail." in marked


@pytest.mark.parametrize(
    ("parent_body", "current_body", "expected_black", "expected_added"),
    (
        ("Alpha beta.", "Alpha new beta.", "Alpha ", "new"),
        ("Alpha old beta.", "Alpha beta.", "Alpha beta.", None),
        ("Alpha old beta.", "Alpha new beta.", "Alpha ", "new"),
        ("原有摘要内容。", "原有新增摘要内容。", "原有", "新增"),
        ("Value $k_1$.", "Value $k_2$.", "Value ", r"$k_2$"),
    ),
)
def test_abstract_prose_uses_native_fine_addition_evidence(
    tmp_path: Path,
    parent_body: str,
    current_body: str,
    expected_black: str,
    expected_added: str | None,
) -> None:
    if shutil.which("latexdiff") is None:
        pytest.skip("latexdiff is required for this targeted synthetic contract")
    parent_text = (
        "\\documentclass{article}\\begin{document}"
        f"\\begin{{abstract}}{parent_body}\\end{{abstract}}"
        "\\end{document}"
    )
    current_text = (
        "\\documentclass{article}\\begin{document}"
        f"\\begin{{abstract}}{current_body}\\end{{abstract}}"
        "\\end{document}"
    )
    parent = tmp_path / "parent.tex"
    current = tmp_path / "current.tex"
    output = tmp_path / "evidence.tex"
    parent.write_text(parent_text, encoding="utf-8")
    current.write_text(current_text, encoding="utf-8")

    run_latexdiff(parent, current, output, preamble=_detector_preamble(tmp_path))
    provenance = extract_provenance(current_text)
    spans, unresolved = _locate_additions(output.read_text(), provenance)
    marked = apply_highlights(provenance.text, spans)

    assert unresolved == ()
    assert expected_black in marked
    if expected_added is None:
        assert r"\DIFadd" not in marked
    else:
        assert expected_added in marked
        assert r"\DIFadd" in marked


def test_abstract_mixed_author_and_reviewer_additions_keep_ownership(
    tmp_path: Path,
) -> None:
    if shutil.which("latexdiff") is None:
        pytest.skip("latexdiff is required for this targeted synthetic contract")
    parent_text = (
        r"\documentclass{article}\begin{document}"
        r"\begin{abstract}Stable prose.\end{abstract}\end{document}"
    )
    current_text = (
        r"\documentclass{article}\begin{document}\begin{abstract}"
        r"Stable prose. Author addition. \review{1-1}{Reviewer addition.}"
        r"\end{abstract}\end{document}"
    )
    provenance = extract_provenance(current_text)
    parent = tmp_path / "parent.tex"
    current = tmp_path / "current.tex"
    output = tmp_path / "evidence.tex"
    parent.write_text(parent_text, encoding="utf-8")
    current.write_text(provenance.text, encoding="utf-8")

    run_latexdiff(parent, current, output, preamble=_detector_preamble(tmp_path))
    spans, unresolved = _locate_additions(output.read_text(), provenance)
    marked = apply_highlights(provenance.text, spans)

    assert unresolved == ()
    assert r"\DIFadd{Author addition.}" in marked
    assert r"\SCIReviewSpan{1-1}{\DIFaddReview{Reviewer addition.}}" in marked


def test_labeled_bilingual_figure_moved_with_layout_only_changes_stays_black(
    tmp_path: Path,
) -> None:
    parent = (
        "正文 A。\n\n"
        "\\begin{figure}[htbp]\n"
        "\\includegraphics{figure.pdf}\n"
        "\\setlength{\\abovecaptionskip}{10pt} % source note\n"
        "\\bicaption{中文图题。}{English caption. }\n"
        "\\label{fig:test}\n"
        "\\end{figure}\n\n正文 B。"
    )
    current = (
        "正文 A。新增正文。\n\n正文 B。\n\n"
        "\\begin{figure}[htbp]\n"
        "\\includegraphics{figure.pdf}\n"
        "\\setlength{\\abovecaptionskip}{10pt}\n"
        "\\bicaption\n  {中文图题。}\n  {English caption.}\n"
        "\\label{fig:test}\n"
        "\\end{figure}"
    )

    marked, spans, moves = _structural_revision(tmp_path, parent, current)

    assert moves >= 1
    assert r"\bicaption" in marked
    assert r"\DIFadd{中文图题" not in marked
    assert r"\DIFadd{English caption" not in marked
    assert not any("中文图题" in marked[item.start : item.end] for item in spans)


def test_perspective_figure_one_caption_move_regression(tmp_path: Path) -> None:
    zh = "面向智能体安全操作的污水生物处理过程动力学模型结构化对象层框架。"
    en = (
        "Framework of the structured object layer for the safe operation of "
        "dynamic models of biological wastewater treatment processes by AI agents."
    )
    parent_figure = (
        "\\begin{figure}[htbp]\n"
        "\\includegraphics{./figures/figure_1.jpg}\n"
        "\\bicaption{%s}{%s }\n"
        "\\label{fig:structured_object_framework}\n"
        "\\end{figure}"
    ) % (zh, en)
    current_figure = (
        "\\begin{figure}[htbp]\n"
        "\\includegraphics{./figures/figure_1.jpg}\n"
        "\\bicaption\n{%s}\n{%s}\n"
        "\\label{fig:structured_object_framework}\n"
        "\\end{figure}"
    ) % (zh, en)

    marked, spans, moves = _structural_revision(
        tmp_path,
        "Parent lead.\n\n" + parent_figure + "\n\nParent tail.",
        "Current lead.\n\nCurrent tail.\n\n" + current_figure,
    )

    assert moves >= 1
    assert not any(zh in marked[item.start : item.end] for item in spans)
    assert r"\DIFadd{Framework of the structured object layer" not in marked


def test_moved_unchanged_reviewer_wrapped_figure_has_no_reviewer_location_event(
    tmp_path: Path,
) -> None:
    figure = (
        "\\begin{figure}\n"
        "\\bicaption{中文图题}{English caption}\n"
        "\\label{fig:test}\n"
        "\\end{figure}"
    )

    _marked, spans, moves = _structural_revision(
        tmp_path,
        "Alpha.\n\n" + figure + "\n\nOmega.",
        "Alpha.\n\nOmega.\n\n\\review{1-1}{" + figure + "}",
    )

    assert moves >= 1
    assert not any(item.review_ids == ("1-1",) for item in spans)


def test_unlabeled_structural_block_is_not_guessed_as_stable_identity() -> None:
    parent = (
        "\\begin{document}Alpha.\n\n"
        "\\begin{figure}\\includegraphics{stable.pdf}\\end{figure}\n\n"
        "Omega.\\end{document}"
    )
    current = (
        "\\begin{document}Alpha.\n\nOmega.\n\n"
        "\\begin{figure}\\includegraphics{stable.pdf}\\end{figure}\\end{document}"
    )
    start = current.index("stable.pdf")
    evidence = [HighlightSpan(start, start + len("stable.pdf"), None)]

    retained, moves = suppress_exact_moves(parent, current, evidence)

    assert retained == evidence
    assert moves == 0


@pytest.mark.parametrize(
    ("old_zh", "new_zh", "old_en", "new_en", "expected"),
    (
        ("中文图题 A", "中文图题 B", "English caption", "English caption", ("B",)),
        ("中文图题", "中文图题", "English caption A", "English caption B", ("B",)),
        (
            "中文图题 A",
            "中文图题 B",
            "English caption A",
            "English caption B",
            ("B", "B"),
        ),
    ),
)
def test_moved_bilingual_figure_keeps_only_real_caption_changes(
    tmp_path: Path,
    old_zh: str,
    new_zh: str,
    old_en: str,
    new_en: str,
    expected: tuple[str, ...],
) -> None:
    figure = (
        "\\begin{figure}\n"
        "\\includegraphics{figure.pdf}\n"
        "\\bicaption{%s}{%s}\n"
        "\\label{fig:test}\n"
        "\\end{figure}"
    )
    parent = "Alpha.\n\n" + figure % (old_zh, old_en) + "\n\nOmega."
    current = "Alpha revised.\n\nOmega.\n\n" + figure % (new_zh, new_en)

    marked, _spans, _moves = _structural_revision(tmp_path, parent, current)

    assert marked.count(r"\DIFadd{B}") == len(expected)
    if old_zh == new_zh:
        assert r"\DIFadd{中文图题" not in marked
    if old_en == new_en:
        assert r"\DIFadd{English caption" not in marked


def test_moved_figure_reviewer_caption_change_keeps_provenance_and_location(
    tmp_path: Path,
) -> None:
    block = (
        "\\begin{figure}\n"
        "\\bicaption{中文图题 %s}{English caption}\n"
        "\\label{fig:test}\n"
        "\\end{figure}"
    )
    parent = "Alpha.\n\n" + block % "A" + "\n\nOmega."
    current = "Alpha.\n\nOmega.\n\n" + block % r"\review{1-1}{B}"

    marked, spans, _moves = _structural_revision(tmp_path, parent, current)

    assert r"\SCIReviewSpan{1-1}{\DIFaddReview{B}}" in marked
    assert any(item.review_ids == ("1-1",) for item in spans)
    assert r"\DIFaddReview{English caption}" not in marked


@pytest.mark.parametrize(
    ("parent_table", "current_table", "expected_added"),
    (
        (
            r"\caption{Stable caption}\label{tab:test} A & B \\",
            r"\caption{Stable caption}\label{tab:test} A & B \\",
            None,
        ),
        (
            r"\caption{Caption A}\label{tab:test} A & B \\",
            r"\caption{Caption B}\label{tab:test} A & B \\",
            "B",
        ),
        (
            r"\caption{Stable caption}\label{tab:test} A & B \\",
            r"\caption{Stable caption}\label{tab:test} A & C \\",
            "C",
        ),
    ),
)
def test_labeled_table_move_preserves_real_change_only(
    tmp_path: Path,
    parent_table: str,
    current_table: str,
    expected_added: str | None,
) -> None:
    block = "\\begin{table}\n%s\n\\end{table}"
    parent = "Alpha.\n\n" + block % parent_table + "\n\nOmega."
    current = "Alpha revised.\n\nOmega.\n\n" + block % current_table

    marked, _spans, moves = _structural_revision(tmp_path, parent, current)

    assert r"\DIFadd{Stable caption}" not in marked
    if expected_added is None:
        assert moves >= 1
        assert "\\DIFadd" not in marked[marked.index(r"\begin{table}") :]
    else:
        assert rf"\DIFadd{{{expected_added}" in marked


@pytest.mark.parametrize(
    ("old", "new", "changed"), (("1", "1", False), ("1", "2", True))
)
def test_labeled_equation_move_uses_identity_then_whole_current_strategy(
    tmp_path: Path,
    old: str,
    new: str,
    changed: bool,
) -> None:
    block = "\\begin{equation}\nx=%s\\label{eq:test}\n\\end{equation}"
    parent = "Alpha.\n\n" + block % old + "\n\nOmega."
    current = "Alpha revised.\n\nOmega.\n\n" + block % new

    marked, _spans, moves = _structural_revision(tmp_path, parent, current)

    if changed:
        assert r"\begin{equation}\SCIAuthorDisplayBegin{}" in marked
        assert "x=1" not in marked
        assert "x=2" in marked
    else:
        assert moves >= 1
        assert r"\SCIAuthorDisplayBegin" not in marked


def test_labeled_figure_image_change_does_not_color_unchanged_caption(
    tmp_path: Path,
) -> None:
    block = (
        "\\begin{figure}\n"
        "\\includegraphics{%s}\n"
        "\\bicaption{中文图题}{English caption}\n"
        "\\label{fig:test}\n"
        "\\end{figure}"
    )
    parent = "Alpha.\n\n" + block % "old.pdf" + "\n\nOmega."
    current = "Alpha.\n\nOmega.\n\n" + block % "new.pdf"

    marked, _spans, _moves = _structural_revision(tmp_path, parent, current)

    assert r"\DIFadd{中文图题}" not in marked
    assert r"\DIFadd{English caption}" not in marked


@pytest.mark.parametrize(
    ("parent", "current", "expected"),
    (
        ("普通中文段落。", "普通新增中文段落。", "新增"),
        ("Ordinary English prose.", "Ordinary revised English prose.", "revised"),
    ),
)
def test_labeled_structural_alignment_does_not_change_ordinary_prose_diff(
    tmp_path: Path,
    parent: str,
    current: str,
    expected: str,
) -> None:
    marked, _spans, _moves = _structural_revision(tmp_path, parent, current)

    assert rf"\DIFadd{{{expected}}}" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END).endswith(
        current + "\n\\end{document}\n"
    )
