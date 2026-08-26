"""Unit tests for comment-aware reviewer provenance intervals."""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_manuscript.errors import WorkflowError
from sci_manuscript.provenance import (
    ReviewSpan,
    extract_provenance,
    split_by_review_provenance,
)


def test_review_wrapper_is_removed_but_interval_is_retained() -> None:
    source = extract_provenance(r"Before \review{1-1,2-1}{模型能够稳定执行。} After")

    assert source.text == "Before 模型能够稳定执行。 After"
    span = source.review_spans[0]
    assert span.review_ids == ("1-1", "2-1")
    assert source.text[span.start : span.end] == "模型能够稳定执行。"
    assert split_by_review_provenance(source, span.start, span.end) == (
        (span.start, span.end, ("1-1", "2-1")),
    )


def test_nested_review_scope_inherits_and_unions_ids() -> None:
    source = extract_provenance(r"\review{1-1}{A\review{2-1,1-1}{B}C}")

    assert source.text == "ABC"
    assert source.review_spans == (
        ReviewSpan(("1-1",), 0, 1),
        ReviewSpan(("1-1", "2-1"), 1, 2),
        ReviewSpan(("1-1",), 2, 3),
    )


def test_empty_review_wrapper_records_deletion_only_provenance() -> None:
    source = extract_provenance(r"Before. \review{1-1}{} After.")

    assert source.text == "Before.  After."
    assert source.review_spans == (ReviewSpan(("1-1",), 8, 8),)


def test_comments_do_not_activate_or_terminate_review_commands() -> None:
    source = extract_provenance(
        "% \\review{9-9}{commented}\n"
        "Before \\review{1-1}{owned % \\review{2-2}{ignored}\ntext} after."
    )

    assert r"\review{9-9}{commented}" in source.text
    assert r"\review{2-2}{ignored}" in source.text
    assert tuple(span.review_ids for span in source.review_spans) == (
        ("1-1",),
        ("1-1",),
    )
    owned = "".join(source.text[span.start : span.end] for span in source.review_spans)
    assert " ".join(owned.split()) == "owned text"


def test_wrapper_seams_preserve_only_real_paragraph_boundaries() -> None:
    adjacent = extract_provenance(
        "\\review{1-1}{\n First.\n}\\review{1-2}{\n Second.\n}"
    )
    inside = extract_provenance("\\review{1-1}{First.\n\nSecond.}")

    assert "First.\nSecond." in adjacent.text
    assert "First.\n\n" not in adjacent.text
    assert inside.text.count("\n\n") == 1


def test_invalid_review_reports_file_line_id_reason_and_context(tmp_path: Path) -> None:
    source = tmp_path / "sections" / "methods.tex"
    text = "Stable line.\n\\review{bad-id}{Changed context.}\n"

    with pytest.raises(WorkflowError) as raised:
        extract_provenance(text, source_path=source)

    message = str(raised.value)
    assert f"File: {source.resolve()}" in message
    assert "Line: 2" in message
    assert "ID: bad-id" in message
    assert "Reason: Invalid review ID list" in message
    assert r"Context: \review{bad-id}{Changed context.}" in message
