"""Unit tests for reviewer provenance and revision-refinement semantics."""

from __future__ import annotations

import pytest

from sci_manuscript.diff import (
    CHARACTER_REFINEMENT_THRESHOLD,
    MAX_CHARACTER_REFINEMENT_CHARS,
    _classify_reviewer_additions,
    _encode_paragraph_boundaries,
    _encode_provenance_paragraph_boundaries,
    _materialize_current_paragraph_boundaries,
    _neutralize_unowned_paragraph_breaks,
    _safe_character_refinement,
)
from sci_manuscript.provenance import (
    ReviewSpan,
    extract_provenance,
    split_by_review_provenance,
)


def test_review_wrapper_is_removed_but_interval_is_retained() -> None:
    source = extract_provenance(r"Before \review{1-1,2-1}{模型能够稳定执行。} After")
    assert source.text == "Before 模型能够稳定执行。 After"
    assert len(source.review_spans) == 1
    span = source.review_spans[0]
    assert span.review_ids == ("1-1", "2-1")
    assert source.text[span.start : span.end] == "模型能够稳定执行。"
    assert split_by_review_provenance(source, span.start, span.end) == (
        (span.start, span.end, ("1-1", "2-1")),
    )


def test_nested_review_scope_inherits_and_canonicalizes_effective_ids() -> None:
    source = extract_provenance(r"\review{1-1}{A\review{2-1,1-1}{B}C}")

    assert source.text == "ABC"
    assert source.review_spans == (
        ReviewSpan(("1-1",), 0, 1),
        ReviewSpan(("1-1", "2-1"), 1, 2),
        ReviewSpan(("1-1",), 2, 3),
    )
    assert split_by_review_provenance(source, 0, 3) == (
        (0, 1, ("1-1",)),
        (1, 2, ("1-1", "2-1")),
        (2, 3, ("1-1",)),
    )


def test_adjacent_review_wrappers_do_not_invent_a_paragraph() -> None:
    source = extract_provenance(
        "\\review{1-1}{\n    First sentence.\n}\\review{1-2}{\n    Second sentence.\n}"
    )

    assert "First sentence.\nSecond sentence." in source.text
    assert "First sentence.\n\n" not in source.text
    assert tuple(span.review_ids for span in source.review_spans) == (
        ("1-1",),
        ("1-2",),
    )
    assert all(
        source.text[span.start : span.end].strip() for span in source.review_spans
    )


def test_real_paragraph_inside_or_between_review_wrappers_is_preserved() -> None:
    inside = extract_provenance("\\review{1-1}{First paragraph.\n\nSecond paragraph.}")
    between = extract_provenance(
        "\\review{1-1}{First paragraph.}\n\n\\review{1-2}{Second paragraph.}"
    )

    assert inside.text.count("\n\n") == 1
    assert between.text.count("\n\n") == 1


@pytest.mark.parametrize(
    ("current", "latexdiff"),
    (
        (
            r"Before \review{1-1}{reviewer addition} after.",
            r"Before \DIFadd{reviewer addition} after.",
        ),
        (
            r"Before \review{1-1}{new wording} after.",
            r"Before \DIFdel{old wording}\DIFadd{new wording} after.",
        ),
        (
            r"中文前文\review{1-1}{审稿新增内容}中文后文。",
            r"中文前文\DIFadd{审稿新增内容}中文后文。",
        ),
        (
            r"English before \review{1-1}{reviewed text} and after.",
            r"English before \DIFadd{reviewed text} and after.",
        ),
        (
            r"Math before \review{1-1}{formula $a+c$} and after.",
            r"Math before \DIFadd{formula $a+c$} and after.",
        ),
        (
            r"\review{1-1}{A complete reviewed paragraph.}",
            r"\DIFadd{A complete reviewed paragraph.}",
        ),
        (
            r"A \review{1-1}{B \review{2-1}{nested child} D} E.",
            r"A \DIFadd{B nested child D} E.",
        ),
        (
            "\\review{1-1}{First real paragraph.}\n\nSecond real paragraph.",
            "\\DIFadd{First real paragraph.}\n\nSecond real paragraph.",
        ),
    ),
    ids=(
        "unchanged-then-reviewer-addition",
        "deletion-reviewer-addition-unchanged",
        "chinese-continuous-text",
        "english-continuous-text",
        "inline-math",
        "whole-paragraph-scope",
        "nested-same-paragraph",
        "two-real-paragraphs",
    ),
)
def test_review_provenance_is_paragraph_transparent(
    current: str,
    latexdiff: str,
) -> None:
    provenance = extract_provenance(current)
    classified = _classify_reviewer_additions(latexdiff, provenance)

    assert classified.count("\n\n") == provenance.text.count("\n\n")


def test_current_topology_owns_all_paragraph_boundaries() -> None:
    provenance = extract_provenance(
        "\\review{1-1}{Current first paragraph.}\n\nCurrent second paragraph."
    )
    encoded = _encode_provenance_paragraph_boundaries(provenance)
    raw = encoded.text.replace(
        "Current first paragraph.",
        "Current first\n\nparagraph.",
    )
    normalized = _neutralize_unowned_paragraph_breaks(raw)
    classified = _classify_reviewer_additions(normalized, encoded)
    materialized, report = _materialize_current_paragraph_boundaries(classified, 1)

    assert "Current first\n\nparagraph" not in materialized
    assert "paragraph.\n\\SCIParagraphBoundary{}\nCurrent second" in materialized
    assert report == {
        "current_paragraph_boundaries": 1,
        "marked_current_paragraph_boundaries": 1,
        "missing_boundaries": 0,
        "invented_boundaries": 0,
    }


def test_materialized_bibliography_whitespace_is_not_prose_topology() -> None:
    source = """\\begin{document}
First paragraph.

Second paragraph.

\\begin{thebibliography}{1}

\\bibitem{key}
Reference text.

\\end{thebibliography}
\\end{document}
"""

    encoded = _encode_paragraph_boundaries(source, "SCIParagraph")

    assert encoded.count(r"\SCIParagraph{") == 2
    assert "\\begin{thebibliography}{1}\n\n\\bibitem{key}" in encoded


def test_topology_normalization_is_not_tied_to_dif_comment_names() -> None:
    raw = "A\n\n%DIFDELCMD old\n\n%DIFAUXCMD old\n\nB"
    normalized = _neutralize_unowned_paragraph_breaks(raw)

    assert "\n\n" not in normalized
    assert normalized.count("\n%\n") == 3


def test_character_refinement_colors_only_real_reviewer_change() -> None:
    provenance = extract_provenance(
        r"\begin{document}\review{1-1}{模型能够稳定执行。} 作者新增。\end{document}"
    )
    latexdiff = (
        r"\begin{document}"
        r"\DIFdel{模型能够执行。}\DIFadd{模型能够稳定执行。} "
        r"\DIFadd{作者新增。}"
        r"\end{document}"
    )
    classified = _classify_reviewer_additions(latexdiff, provenance)
    assert r"模型能够\SCIReviewSpan{1-1}{\DIFaddReview{稳定}}执行。" in classified
    assert r"\DIFadd{作者新增。}" in classified
    assert r"\DIFaddReview{模型能够" not in classified


def test_character_refinement_preserves_old_and_new_text_spans() -> None:
    provenance = extract_provenance(
        r"\begin{document}\review{1-1}{Refined wording.}\end{document}"
    )
    latexdiff = (
        r"\begin{document}"
        r"\DIFdel{Reviewed wording.}\DIFadd{Refined wording.}"
        r"\end{document}"
    )
    classified = _classify_reviewer_additions(latexdiff, provenance)
    assert (
        r"Re\DIFdel{v}\SCIReviewSpan{1-1}{\DIFaddReview{f}}i\DIFdel{ew}"
        r"\SCIReviewSpan{1-1}{\DIFaddReview{n}}ed wording."
    ) in classified


def test_frontmatter_addition_is_classified_before_begin_document() -> None:
    provenance = extract_provenance(
        r"\cnabstract{\review{1-1}{第一句不变。第二句新表述。}}"
        r"\begin{document}正文\end{document}"
    )
    latexdiff = (
        r"% SCI_DIFF_STYLE_BEGIN\n"
        r"\providecommand{\DIFadd}[1]{#1}\n"
        r"% SCI_DIFF_STYLE_END\n"
        r"\cnabstract{\DIFdel{第一句不变。第二句旧表述。}"
        r"\DIFadd{第一句不变。第二句新表述。}}"
        r"\begin{document}正文\end{document}"
    )
    classified = _classify_reviewer_additions(latexdiff, provenance)
    assert r"\SCIReviewSpan{1-1}{\DIFaddReview{新}}" in classified
    assert r"\DIFaddReview{第一句不变" not in classified
    assert r"\providecommand{\DIFadd}[1]{#1}" in classified


def test_unrelated_replacement_is_not_fragmented_by_character_matches() -> None:
    provenance = extract_provenance(
        r"\begin{document}\review{1-1}{Reviewed wording.}\end{document}"
    )
    latexdiff = (
        r"\begin{document}"
        r"\DIFdel{Replace this placeholder and its }"
        r"\DIFadd{Reviewed wording.}"
        r"\end{document}"
    )
    classified = _classify_reviewer_additions(latexdiff, provenance)
    assert r"\DIFdel{Replace this placeholder and its }" in classified
    assert r"\SCIReviewSpan{1-1}{\DIFaddReview{Reviewed wording.}}" in classified


def test_character_refinement_policy_values_are_release_contract() -> None:
    assert CHARACTER_REFINEMENT_THRESHOLD == 0.70
    assert MAX_CHARACTER_REFINEMENT_CHARS == 2000


def test_character_refinement_uses_seventy_percent_threshold() -> None:
    assert _safe_character_refinement("模型能够执行计算", "模型能够稳定执行计算")
    assert not _safe_character_refinement(
        "候选对象转化为规范结构化对象",
        "通过程序验证并经人工核查的候选对象进入正式结构化对象层",
    )


def test_character_refinement_rejects_tex_structural_content() -> None:
    assert not _safe_character_refinement(
        r"模型使用 $x$ 进行计算",
        r"模型使用 $y$ 进行计算",
    )
    assert not _safe_character_refinement(
        r"\textbf{旧结构}",
        r"\textbf{新结构}",
    )


def test_character_refinement_has_size_guard() -> None:
    assert not _safe_character_refinement("甲" * 2001, "甲" * 2000 + "乙")
