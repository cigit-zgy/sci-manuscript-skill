"""Targeted contracts for the current-only highlighted revision renderer."""

from __future__ import annotations

from pathlib import Path

import pytest
from sci_manuscript.diff import _locate_additions
from sci_manuscript.errors import WorkflowError
from sci_manuscript.provenance import extract_provenance
from sci_manuscript.revision_render import (
    CitationProvenance,
    HighlightSpan,
    added_citation_provenance,
    apply_highlights,
    citation_spans,
    display_evidence_is_covered,
    preserve_topology_seams,
    protected_citation_spans,
    replace_special_spans,
    strip_highlight_markup,
    validate_topology_identity,
)

STYLE_BEGIN = "% TEST_STYLE_BEGIN"
STYLE_END = "% TEST_STYLE_END"


def _document(body: str) -> str:
    return f"\\documentclass{{article}}\n\\begin{{document}}\n\n{body}\n\n\\end{{document}}\n"


def _span(text: str, value: str, owner: tuple[str, ...] | None = None) -> HighlightSpan:
    start = text.index(value)
    return HighlightSpan(start, start + len(value), owner)


def _author(content: str, number: int = 1) -> str:
    return rf"\SciAuthorRevision{{sci:rev:adhoc:e{number:04d}}}{{{content}}}"


def _reviewer(content: str, review_id: str = "1-1", number: int = 1) -> str:
    return (
        rf"\SCIReviewSpan{{{review_id}}}"
        rf"{{\SciReviewerRevision{{sci:rev:adhoc:e{number:04d}}}"
        rf"{{{review_id}}}{{{content}}}}}"
    )


@pytest.mark.parametrize(
    ("body", "changed"),
    (
        ("Plain current paragraph.", "current"),
        ("One author addition.", "author"),
        ("One reviewer addition.", "reviewer"),
        ("A sentence was extensively rewritten.", "extensively rewritten"),
        ("A complete current paragraph replaces its parent.", "complete current"),
        (r"Inline $k_2$ and citation \cite{A,B}.", "k_2"),
    ),
)
def test_strip_highlight_preserves_exact_current_source(
    body: str, changed: str
) -> None:
    current = _document(body)
    marked = apply_highlights(current, [_span(current, changed)])

    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_author_and_reviewer_additions_use_exclusive_colors() -> None:
    current = _document("Author phrase and reviewer phrase.")
    author = _span(current, "Author phrase")
    reviewer = _span(current, "reviewer phrase", ("1-1",))

    marked = apply_highlights(current, [author, reviewer])

    assert _author("Author phrase") in marked
    assert _reviewer("reviewer phrase", number=2) in marked


@pytest.mark.parametrize(
    ("body", "evidence", "expected"),
    (
        ("进一步通过 Python、MATLAB 或 Julia", " Python", "通过 {macro}、"),
        ("Python 模型", "Python ", "{macro} 模型"),
        (r"参数 $k$", " $k$", "参数 {macro}"),
        (r"$k$ model", "$k$ ", "{macro} model"),
        ("例如，Python", "Python", "例如，{macro}"),  # noqa: RUF001
        ("Python，模型", "Python", "{macro}，模型"),  # noqa: RUF001
        (r"term~model", "~model", "term~{macro}"),
        (r"term\ model", r"\ model", r"term\ {macro}"),
    ),
)
def test_highlight_edges_leave_tex_whitespace_in_exact_source_position(
    body: str, evidence: str, expected: str
) -> None:
    current = _document(body)
    marked = apply_highlights(current, [_span(current, evidence)])

    content = evidence.strip(" ~\\")
    assert expected.format(macro=_author(content)) in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


@pytest.mark.parametrize("owner", (None, ("1-1",)))
def test_leading_and_trailing_space_stay_outside_author_or_reviewer_wrapper(
    owner: tuple[str, ...] | None,
) -> None:
    current = _document("Prefix revised text suffix")
    start = current.index(" revised")
    end = current.index(" suffix") + 1

    marked = apply_highlights(current, [HighlightSpan(start, end, owner)])

    macro = _author("revised text") if owner is None else _reviewer("revised text")
    assert f"Prefix {macro} suffix" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_adjacent_red_and_blue_spans_preserve_intervening_space() -> None:
    current = _document("author reviewer")
    space = current.index(" ", current.index("author"))
    marked = apply_highlights(
        current,
        [
            HighlightSpan(current.index("author"), space + 1, None),
            HighlightSpan(space + 1, space + len(" reviewer"), ("1-1",)),
        ],
    )

    assert f"{_author('author')} {_reviewer('reviewer', number=2)}" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_unchanged_text_inside_review_remains_black() -> None:
    provenance = extract_provenance(_document(r"\review{1-1}{Stable current text.}"))

    marked = apply_highlights(provenance.text, [])

    assert marked == provenance.text
    assert "DIFadd" not in marked


def test_latexdiff_addition_intersects_nested_effective_provenance() -> None:
    source = extract_provenance(
        _document(r"\review{1-1}{outer \review{2-2}{new phrase} tail}")
    )
    spans, unresolved = _locate_additions(r"\DIFadd{new phrase}", source)

    assert unresolved == ()
    assert spans == [
        HighlightSpan(
            source.text.index("new phrase"),
            source.text.index("new phrase") + len("new phrase"),
            ("1-1", "2-2"),
        )
    ]


def test_heading_highlight_stays_inside_current_heading_field() -> None:
    current = _document("\\section{Revised title}\nText.")
    title = _span(current, "Revised title", ("1-1",))

    marked = apply_highlights(current, [title])

    assert marked.index(r"\section{") < marked.index(r"\SCIReviewSpan")
    assert r"\SciReviewerRevision{sci:rev:adhoc:e0001}{1-1}{\section" not in marked


def test_highlight_never_changes_historical_single_paragraph_topology() -> None:
    sentence = "模型知识的持续积累、共享和扩充。在此基础上，形成当前表达。"  # noqa: RUF001
    current = _document(sentence)
    marked = apply_highlights(current, [_span(current, "形成当前表达", ("1-1",))])

    assert "扩充。\n\n在此基础上" not in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_parent_deleted_subsection_cannot_enter_marked_current_paragraph() -> None:
    parent = _document("A.\n\n\\subsection{Old}\n\nB.")
    current = _document("A. B.")
    marked = apply_highlights(current, [_span(current, "B.")])

    assert "Old" in parent
    assert "Old" not in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_source_line_wrapping_does_not_create_a_paragraph() -> None:
    current = _document("One source line\ncontinues the same paragraph.")
    marked = apply_highlights(current, [_span(current, "continues")])

    assert "\n\ncontinues" not in marked


@pytest.mark.parametrize(
    ("first_owner", "second_owner", "highlight_first", "highlight_second"),
    (
        (None, None, False, False),
        (("1-1",), None, True, False),
        (None, ("1-1",), False, True),
        (("1-1",), ("1-1",), True, True),
        (None, None, True, True),
    ),
)
def test_blank_line_seam_is_never_enclosed_by_same_color_spans(
    first_owner: tuple[str, ...] | None,
    second_owner: tuple[str, ...] | None,
    highlight_first: bool,
    highlight_second: bool,
) -> None:
    current = _document("First paragraph.\n\nSecond paragraph.")
    spans = []
    if highlight_first:
        spans.append(_span(current, "First paragraph.", first_owner))
    if highlight_second:
        spans.append(_span(current, "Second paragraph.", second_owner))

    marked = apply_highlights(current, spans)

    assert "\n\n" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_one_crossing_span_is_split_at_blank_line_seam() -> None:
    current = _document("First paragraph.\n\nSecond paragraph.")
    start = current.index("First")
    end = current.index("Second") + len("Second paragraph.")

    spans = preserve_topology_seams(current, [HighlightSpan(start, end, ("1-1",))])
    marked = apply_highlights(current, spans)

    assert len(spans) == 2
    assert "}}\n\n\\SCIReviewSpan{1-1}" in marked


def test_fine_span_ending_at_paragraph_end_excludes_separator() -> None:
    current = _document("Stable revised.\n\nNext.")
    start = current.index("revised")
    end = current.index("Next")
    spans = preserve_topology_seams(current, [HighlightSpan(start, end, None)])

    assert spans == [HighlightSpan(start, current.index("\n\n", start), None)]


def test_fine_span_starting_at_paragraph_begin_excludes_separator() -> None:
    current = _document("First.\n\nRevised next.")
    separator = current.index("\n\n", current.index("First"))
    end = current.index("next") + len("next")
    spans = preserve_topology_seams(current, [HighlightSpan(separator, end, ("1-1",))])

    assert spans == [HighlightSpan(current.index("Revised"), end, ("1-1",))]


def test_explicit_par_is_an_immutable_seam() -> None:
    current = _document(r"First paragraph.\par Second paragraph.")
    start = current.index("First")
    end = current.index("Second") + len("Second paragraph.")
    marked = apply_highlights(current, [HighlightSpan(start, end, None)])

    assert r"}\par \SciAuthorRevision{" in marked


def test_comment_preserved_blank_line_is_an_immutable_seam() -> None:
    current = _document("First paragraph.\n% keep seam\n\nSecond paragraph.")
    start = current.index("First")
    end = current.index("Second") + len("Second paragraph.")
    marked = apply_highlights(current, [HighlightSpan(start, end, ("1-1",))])

    assert "% keep seam\n\n" in marked
    assert "seam\n\n\\SCIReviewSpan" in marked


def test_heading_boundary_stays_outside_crossing_highlight() -> None:
    current = _document("Revised paragraph.\n\n\\section{Heading}\nBody.")
    start = current.index("Revised")
    end = current.index("Body") + len("Body.")
    marked = apply_highlights(current, [HighlightSpan(start, end, None)])

    assert r"\section{\SciAuthorRevision{" in marked
    assert r"\SciAuthorRevision{sci:rev:adhoc:e0001}{\section" not in marked


def test_display_after_highlighted_paragraph_keeps_environment_boundary() -> None:
    current = _document("Revised paragraph.\n\n\\begin{equation}x=1\\end{equation}")
    marked = apply_highlights(current, [_span(current, "Revised paragraph.")])

    assert r"\begin{equation}" in marked
    assert r"\SciAuthorRevision{sci:rev:adhoc:e0001}{\begin{equation}" not in marked


def test_highlighted_paragraph_after_display_keeps_environment_boundary() -> None:
    current = _document("\\begin{equation}x=1\\end{equation}\n\nRevised paragraph.")
    marked = apply_highlights(current, [_span(current, "Revised paragraph.")])

    assert r"\end{equation}\n\n" not in marked
    assert r"\end{equation}" in marked
    assert f"\n\n{_author('Revised paragraph.')}" in marked


def test_topology_validator_reports_first_boundary_mismatch(tmp_path: Path) -> None:
    clean = _document("First paragraph.\n\nSecond paragraph.")
    marked = clean.replace("paragraph.\n\nSecond", "paragraph. Second")

    with pytest.raises(WorkflowError, match="CLEAN_MARKED_TOPOLOGY_MISMATCH") as error:
        validate_topology_identity(clean, marked, tmp_path / "marked.tex")

    message = str(error.value)
    assert "nearest line:" in message
    assert "boundary type:" in message
    assert "clean context:" in message
    assert "marked context:" in message


def test_perspective_other_hand_paragraph_boundary_regression() -> None:
    body = (
        "\\review{1-2}{对象契约中已经明确规定的结构和科学约束。\n\n"
        "另一方面，某组参数在特定运行条件下是否最适用。}"  # noqa: RUF001
    )
    current = extract_provenance(_document(body))
    start = current.text.index("对象契约")
    end = current.text.index("最适用。") + len("最适用。")
    marked = apply_highlights(current.text, [HighlightSpan(start, end, ("1-2",))])

    assert "}}\n\n\\SCIReviewSpan{1-2}" in marked


def test_perspective_shared_expansion_remains_one_paragraph() -> None:
    body = (
        "\\review{1-3}{模型知识的持续积累、共享和扩充。}\n"
        "\\review{1-4}{在此基础上，继续探索。}"  # noqa: RUF001
    )
    current = extract_provenance(_document(body))
    marked = apply_highlights(
        current.text,
        [
            _span(current.text, "共享和扩充。", ("1-3",)),
            _span(current.text, "在此基础上", ("1-4",)),
        ],
    )

    assert "共享和扩充。\n\n在此基础上" not in strip_highlight_markup(
        marked, STYLE_BEGIN, STYLE_END
    )


@pytest.mark.parametrize("kind", ("paragraph", "heading"))
def _citation_case(
    parent_body: str, current_body: str, reviewer: bool
) -> tuple[str, list[HighlightSpan]]:
    parent = _document(parent_body)
    raw = _document(rf"\review{{1-1}}{{{current_body}}}" if reviewer else current_body)
    provenance = extract_provenance(raw)
    command_start = provenance.text.index(r"\cite")
    owner = ("1-1",) if reviewer else None
    additions = [HighlightSpan(command_start, command_start + 5, owner)]
    return provenance.text, citation_spans(parent, provenance, additions)


@pytest.mark.parametrize(
    ("parent", "current", "reviewer", "highlighted"),
    (
        (r"Text \cite{A}.", r"Text \cite{A}.", False, False),
        (r"Text \cite{A}.", r"Text \cite{A,B}.", True, True),
        (r"Text \cite{A}.", r"Text \cite{A,B}.", False, True),
        (r"Text \cite{A,B}.", r"Text \cite{A}.", False, False),
        (r"Text \cite{A}.", r"Text \cite{B}.", True, True),
    ),
)
def test_citation_key_set_contract(
    parent: str, current: str, reviewer: bool, highlighted: bool
) -> None:
    source, spans = _citation_case(parent, current, reviewer)

    assert bool(spans) is highlighted
    if spans:
        marked = apply_highlights(source, spans)
        assert r"\SCIReferenceLink{\cite" in marked
        assert (r"\SCIReviewReferenceSpan{" in marked) is reviewer
        assert "SCIReviewCitation" not in marked
        assert "SCIAuthorCitation" not in marked
        assert "[?]" not in marked


@pytest.mark.parametrize("owner", (None, ("1-1",)))
@pytest.mark.parametrize("changed_keys", (False, True))
def test_citation_is_a_link_blue_island_inside_fine_or_whole_highlight(
    owner: tuple[str, ...] | None,
    changed_keys: bool,
) -> None:
    parent = _document(r"Old prose \cite{A} tail.")
    current_body = (
        r"Rewritten prose \cite{A,B} tail."
        if changed_keys
        else r"Rewritten prose \cite{A} tail."
    )
    raw = _document(
        rf"\review{{1-1}}{{{current_body}}}" if owner is not None else current_body
    )
    current = extract_provenance(raw)
    body_start = current.text.index("Rewritten")
    body_end = current.text.index("tail.") + len("tail.")
    additions = [HighlightSpan(body_start, body_end, owner)]
    changes = citation_spans(parent, current, additions)
    protected = protected_citation_spans(current, additions, changes)
    rendered = replace_special_spans(additions, protected)

    marked = apply_highlights(current.text, rendered)

    assert r"\SCIReferenceLink{\cite" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current.text
    assert (r"\SCIReviewReferenceSpan{1-1}" in marked) is (
        owner is not None and changed_keys
    )


def test_citation_space_remains_outside_blue_island_and_text_highlight() -> None:
    parent = _document(r"内容。")
    current = extract_provenance(_document(r"\review{1-1}{成为可能 \cite{A}。}"))
    start = current.text.index("成为可能")
    end = current.text.index("。", start)
    additions = [HighlightSpan(start, end, ("1-1",))]
    changes = citation_spans(parent, current, additions)
    protected = protected_citation_spans(current, additions, changes)

    marked = apply_highlights(current.text, replace_special_spans(additions, protected))

    assert (
        r"成为可能}} \SCIReviewReferenceSpan{1-1}{\SCIReferenceLink{\cite{A}}}"
        in marked
    )
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current.text


def test_cjk_revision_wrapper_restores_native_glue_before_adjacent_citation() -> None:
    current = extract_provenance(_document(r"\review{1-1}{交互成为可能\cite{A}。}"))
    start = current.text.index("交互成为可能")
    end = current.text.index(r"\cite", start)
    additions = [HighlightSpan(start, end, ("1-1",))]

    marked = apply_highlights(current.text, additions)

    assert r"成为可能}}\SCIRevisionCitationSeam{}\cite{A}" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current.text


def test_latin_revision_wrapper_does_not_add_cjk_glue_before_citation() -> None:
    current = _document(r"model\cite{A}")
    start = current.index("model")
    marked = apply_highlights(current, [HighlightSpan(start, start + 5, None)])

    assert r"\SCIRevisionCitationSeam" not in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


@pytest.mark.parametrize(
    "command", ("cite", "citep", "citet", "citealp", "citeauthor", "citeyear")
)
def test_supported_citation_family_is_always_a_blue_island(command: str) -> None:
    parent = _document("Text.")
    current = extract_provenance(_document(rf"\review{{1-1}}{{Text \{command}{{A}}.}}"))
    start = current.text.index("Text")
    end = current.text.index(".", start)
    additions = [HighlightSpan(start, end, ("1-1",))]
    changes = citation_spans(parent, current, additions)
    protected = protected_citation_spans(current, additions, changes)

    marked = apply_highlights(current.text, replace_special_spans(additions, protected))

    assert rf"\SCIReferenceLink{{\{command}{{A}}}}" in marked
    assert r"\SCIReviewReferenceSpan{1-1}{" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current.text


def _new_citation_provenance(
    parent_body: str,
    current_body: str,
    changed: str,
) -> dict[str, CitationProvenance]:
    parent = _document(parent_body)
    current = extract_provenance(_document(current_body))
    start = current.text.index(changed)
    owner = next(
        (
            span.review_ids
            for span in current.review_spans
            if span.start <= start < span.end
        ),
        None,
    )
    additions = [HighlightSpan(start, start + len(changed), owner)]
    return added_citation_provenance(parent, current, additions)


def test_new_author_citation_key_has_author_primary_provenance() -> None:
    owners = _new_citation_provenance("Text.", r"Text \cite{newKey}.", r"\cite")

    assert owners["newKey"].review_ids is None


def test_auxiliary_citation_evidence_cannot_override_author_provenance() -> None:
    parent = _document("Text.")
    current = extract_provenance(_document(r"Text \cite{newKey}."))
    start = current.text.index(r"\cite")
    evidence = [HighlightSpan(start, start + len(r"\cite"), ("1-1",))]

    owners = added_citation_provenance(parent, current, evidence)
    groups = citation_spans(parent, current, evidence)

    assert owners["newKey"].review_ids is None
    assert groups[0].review_ids is None


def test_new_reviewer_citation_key_has_reviewer_primary_provenance() -> None:
    owners = _new_citation_provenance(
        "Text.", r"\review{1-1}{Text \cite{newKey}.}", r"\cite"
    )

    assert owners["newKey"].review_ids == ("1-1",)


def test_nested_review_citation_unions_effective_reviewer_ids() -> None:
    owners = _new_citation_provenance(
        "Text.",
        r"\review{1-1}{Text \review{2-2}{\cite{newKey}}.}",
        r"\cite",
    )

    assert owners["newKey"].review_ids == ("1-1", "2-2")


def test_existing_citation_renumbering_has_no_new_key_provenance() -> None:
    owners = _new_citation_provenance(
        r"Text \cite{stable}.", r"Text \cite{stable}.", r"\cite"
    )

    assert owners == {}


def test_deleted_citation_has_no_current_provenance() -> None:
    parent = _document(r"Text \cite{deleted}.")
    current = extract_provenance(_document("Text."))

    assert added_citation_provenance(parent, current, []) == {}


def test_added_key_in_citation_group_receives_group_ownership() -> None:
    parent = _document(r"Text \cite{stable}.")
    current = extract_provenance(_document(r"\review{1-1}{Text \cite{stable,newKey}.}"))
    start = current.text.index(r"\cite")
    additions = [HighlightSpan(start, start + len(r"\cite"), ("1-1",))]

    owners = added_citation_provenance(parent, current, additions)
    groups = citation_spans(parent, current, additions)

    assert owners["newKey"].review_ids == ("1-1",)
    assert groups[0].review_ids == ("1-1",)


@pytest.mark.parametrize("owner", (None, ("1-1",)))
def test_citation_inside_whole_display_is_protected_blue(
    owner: tuple[str, ...] | None,
) -> None:
    current = _document(r"\begin{equation}x=1\quad\cite{A}\label{eq:x}\end{equation}")
    display_start = current.index(r"\begin{equation}")
    display_end = current.index(r"\end{equation}") + len(r"\end{equation}")

    marked = apply_highlights(
        current, [HighlightSpan(display_start, display_end, owner, "display")]
    )

    assert r"\SCIReferenceLink{\cite{A}}" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_labeled_display_evidence_may_defer_whitespace_normalization() -> None:
    current = _document(
        "\\begin{equation}\n\\frac{a}\n{b}\\label{eq:one}\n\\end{equation}"
    )

    assert display_evidence_is_covered(current, r"\frac{a}{b}\label{eq:one}")
    assert not display_evidence_is_covered(current, r"\frac{a}{b}")
    assert not display_evidence_is_covered(current, r"\label{eq:missing}")


def test_special_current_units_replace_overlapping_fine_spans() -> None:
    current = _document(r"Text \cite{A,B}.")
    command_start = current.index(r"\cite")
    fine = HighlightSpan(command_start + 6, command_start + 7, ("1-1",))
    whole = HighlightSpan(
        command_start, command_start + len(r"\cite{A,B}"), ("1-1",), "citation"
    )

    spans = replace_special_spans([fine], [whole])

    assert spans == [whole]


def test_no_parent_only_scientific_content_can_be_rendered(tmp_path: Path) -> None:
    parent = tmp_path / "parent.txt"
    parent.write_text("Deleted old evidence.", encoding="utf-8")
    current = _document("Only current evidence.")

    marked = apply_highlights(current, [_span(current, "current")])

    assert parent.read_text(encoding="utf-8") not in marked
