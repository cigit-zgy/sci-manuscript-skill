"""Unit tests for reviewer provenance sidecar classification."""

from __future__ import annotations

import pytest

from sci_manuscript.diff import _classify_reviewer_additions
from sci_manuscript.provenance import extract_provenance, split_by_review_provenance
from sci_manuscript.workspace import WorkflowError


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


def test_nested_review_scope_is_rejected() -> None:
    with pytest.raises(WorkflowError, match="Nested"):
        extract_provenance(r"\review{1-1}{outer \review{2-1}{inner}}")


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
    assert r"模型能够\DIFaddReview{稳定}执行。" in classified
    assert r"\DIFadd{作者新增。}" in classified
    assert r"\DIFaddReview{模型能够" not in classified


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
    assert r"\DIFaddReview{新}" in classified
    assert r"\DIFaddReview{第一句不变" not in classified
    assert r"\providecommand{\DIFadd}[1]{#1}" in classified
