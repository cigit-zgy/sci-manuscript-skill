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
    TinyIslandAudit,
    adaptive_blocks,
    added_citation_provenance,
    analyze_equations,
    apply_highlights,
    citation_spans,
    coalesce_tiny_unchanged_islands,
    display_evidence_is_covered,
    equation_spans,
    preserve_text_command_shells,
    preserve_topology_seams,
    protected_citation_spans,
    replace_special_spans,
    resolve_equation_spans,
    strip_highlight_markup,
    suppress_exact_moves,
    validate_topology_identity,
)

STYLE_BEGIN = "% TEST_STYLE_BEGIN"
STYLE_END = "% TEST_STYLE_END"


def _document(body: str) -> str:
    return f"\\documentclass{{article}}\n\\begin{{document}}\n\n{body}\n\n\\end{{document}}\n"


def _span(text: str, value: str, owner: tuple[str, ...] | None = None) -> HighlightSpan:
    start = text.index(value)
    return HighlightSpan(start, start + len(value), owner)


def _tiny_island_case(
    left: str,
    gap: str,
    right: str,
    left_owner: tuple[str, ...] | None = ("1-1",),
    right_owner: tuple[str, ...] | None = ("1-1",),
) -> tuple[str, list[HighlightSpan], TinyIslandAudit]:
    current = _document(left + gap + right)
    left_start = current.index(left)
    right_start = left_start + len(left) + len(gap)
    spans, audit = coalesce_tiny_unchanged_islands(
        current,
        [
            HighlightSpan(left_start, left_start + len(left), left_owner),
            HighlightSpan(right_start, right_start + len(right), right_owner),
        ],
    )
    return current, spans, audit


def test_perspective_tiny_island_gold_case_coalesces_black_ben() -> None:
    left = "上述研究表明，将原"  # noqa: RUF001
    gap = "本"
    right = (
        "依赖语言理解和临时推断的科学信息与操作转化为边界明确、关系清晰的结构，"  # noqa: RUF001
        "可以为智能体后续任务提供更加稳定的依据"
    )

    current, spans, audit = _tiny_island_case(left, gap, right)
    marked = apply_highlights(current, spans)

    assert len(spans) == 1
    assert audit.coalesced == 1
    assert f"{left}{gap}{right}" in marked
    assert "}}本\\SCIReviewSpan" not in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


@pytest.mark.parametrize(
    ("gap", "coalesced"),
    (
        ("本", True),
        ("模型", True),
        ("新模型", True),
        ("不同对象", True),
        ("已有模型知", True),
        ("已有模型知识", False),
    ),
)
def test_tiny_island_cjk_threshold_is_five_atoms(gap: str, coalesced: bool) -> None:
    _current, spans, audit = _tiny_island_case("甲" * 12, gap, "乙" * 12)

    assert (len(spans) == 1) is coalesced
    assert (audit.coalesced == 1) is coalesced


@pytest.mark.parametrize(
    ("modified_atoms", "coalesced"), ((19, False), (20, True), (21, True))
)
def test_tiny_island_density_uses_exact_eighty_percent_cross_multiplication(
    modified_atoms: int, coalesced: bool
) -> None:
    left_atoms = modified_atoms // 2
    right_atoms = modified_atoms - left_atoms
    _current, spans, audit = _tiny_island_case(
        "甲" * left_atoms, "不同对象甲", "乙" * right_atoms
    )

    assert (len(spans) == 1) is coalesced
    assert (audit.rejected_density == 0) is coalesced


@pytest.mark.parametrize(
    ("left_owner", "right_owner", "coalesced"),
    (
        (("1-1",), ("1-1",), True),
        (None, None, True),
        (("1-1",), None, False),
        (("1-1",), ("2-2",), False),
        (("1-1", "2-2"), ("1-1", "2-2"), True),
    ),
)
def test_tiny_island_requires_exact_effective_provenance(
    left_owner: tuple[str, ...] | None,
    right_owner: tuple[str, ...] | None,
    coalesced: bool,
) -> None:
    _current, spans, audit = _tiny_island_case(
        "甲" * 12, "本", "乙" * 12, left_owner, right_owner
    )

    assert (len(spans) == 1) is coalesced
    assert (audit.rejected_provenance == 0) is coalesced


@pytest.mark.parametrize(
    "gap",
    (
        "。本",
        "；本",  # noqa: RUF001
        "\n\n本",
        r"\par 本",
        r"\section{标题}本",
        r"\begin{equation}x=1\end{equation}本",
        r"\begin{figure}x\end{figure}本",
        r"\begin{table}x\end{table}本",
    ),
)
def test_tiny_island_never_crosses_sentence_or_structural_boundary(gap: str) -> None:
    _current, spans, audit = _tiny_island_case("甲" * 12, gap, "乙" * 12)

    assert len(spans) == 2
    assert audit.rejected_boundary == 1


@pytest.mark.parametrize(
    "gap", (r"\cite{A}", r"\ref{item}", r"$k$", r"\url{https://example.org}")
)
def test_tiny_island_never_absorbs_protected_content(gap: str) -> None:
    current, spans, audit = _tiny_island_case("甲" * 12, gap, "乙" * 12)
    marked = apply_highlights(current, spans)

    assert len(spans) == 2
    assert audit.rejected_protected == 1
    assert gap in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


@pytest.mark.parametrize(
    ("gap", "coalesced"),
    (
        ("model", True),
        ("the model", True),
        ("the current model", False),
        ("模型 AI", True),
    ),
)
def test_tiny_island_latin_and_mixed_script_thresholds(
    gap: str, coalesced: bool
) -> None:
    left = "revised scientific content remains extensive and "
    right = " with another substantial revised scientific region"
    _current, spans, audit = _tiny_island_case(left, gap, right, None, None)

    assert (len(spans) == 1) is coalesced
    assert (audit.coalesced == 1) is coalesced


@pytest.mark.parametrize("gap", ("， ", "、", ", "))  # noqa: RUF001
def test_punctuation_only_tiny_island_preserves_exact_whitespace(gap: str) -> None:
    current, spans, audit = _tiny_island_case("甲" * 12, gap, "乙" * 12)
    marked = apply_highlights(current, spans)

    assert len(spans) == 1
    assert audit.coalesced == 1
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_whole_block_span_skips_tiny_island_processing() -> None:
    current = _document("Whole current block.")
    span = _span(current, "Whole current block.", ("1-1",))

    spans, audit = coalesce_tiny_unchanged_islands(current, [span])

    assert spans == [span]
    assert audit.examined == 0


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

    assert r"\DIFadd{Author phrase}" in marked
    assert r"\SCIReviewSpan{1-1}{\DIFaddReview{reviewer phrase}}" in marked


@pytest.mark.parametrize(
    ("body", "evidence", "expected"),
    (
        ("进一步通过 Python、MATLAB 或 Julia", " Python", r"通过 \DIFadd{Python}、"),
        ("Python 模型", "Python ", r"\DIFadd{Python} 模型"),
        (r"参数 $k$", " $k$", r"参数 \DIFadd{$k$}"),
        (r"$k$ model", "$k$ ", r"\DIFadd{$k$} model"),
        ("例如，Python", "Python", r"例如，\DIFadd{Python}"),  # noqa: RUF001
        ("Python，模型", "Python", r"\DIFadd{Python}，模型"),  # noqa: RUF001
        (r"term~model", "~model", r"term~\DIFadd{model}"),
        (r"term\ model", r"\ model", r"term\ \DIFadd{model}"),
    ),
)
def test_highlight_edges_leave_tex_whitespace_in_exact_source_position(
    body: str, evidence: str, expected: str
) -> None:
    current = _document(body)
    marked = apply_highlights(current, [_span(current, evidence)])

    assert expected in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


@pytest.mark.parametrize("owner", (None, ("1-1",)))
def test_leading_and_trailing_space_stay_outside_author_or_reviewer_wrapper(
    owner: tuple[str, ...] | None,
) -> None:
    current = _document("Prefix revised text suffix")
    start = current.index(" revised")
    end = current.index(" suffix") + 1

    marked = apply_highlights(current, [HighlightSpan(start, end, owner)])

    macro = (
        r"\DIFadd{revised text}"
        if owner is None
        else r"\SCIReviewSpan{1-1}{\DIFaddReview{revised text}}"
    )
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

    assert r"\DIFadd{author} \SCIReviewSpan{1-1}{\DIFaddReview{reviewer}}" in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current


def test_unchanged_text_inside_review_remains_black() -> None:
    provenance = extract_provenance(_document(r"\review{1-1}{Stable current text.}"))

    marked = apply_highlights(provenance.text, [])

    assert marked == provenance.text
    assert "DIFadd" not in marked


def test_deferred_frontmatter_command_keeps_color_inside_visible_field() -> None:
    current = _document(r"\keywords{new keyword}")
    command_start = current.index(r"\keywords")
    command_end = command_start + len(r"\keywords{new keyword}")

    spans = preserve_text_command_shells(
        current,
        [HighlightSpan(command_start, command_end, None)],
        ("keywords",),
    )
    marked = apply_highlights(current, spans)

    assert r"\keywords{\DIFadd{new keyword}}" in marked
    assert r"\DIFadd{\keywords" not in marked


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


@pytest.mark.parametrize(
    ("coverage", "whole"),
    ((10, False), (40, False), (59, False), (60, True), (80, True)),
)
def test_adaptive_highlight_uses_frozen_sixty_percent_threshold(
    coverage: int, whole: bool
) -> None:
    body = "a" * 100
    current = _document(body)
    start = current.index(body)
    spans, _blocks, _fine, whole_count = adaptive_blocks(
        current, [HighlightSpan(start, start + coverage, ("1-1",))]
    )

    assert (whole_count == 1) is whole
    assert (spans[0].end - spans[0].start == 100) is whole


@pytest.mark.parametrize(
    "owners",
    ((None, ("1-1",)), (("1-1",), ("2-2",))),
)
def test_mixed_provenance_disables_whole_block_collapse(
    owners: tuple[tuple[str, ...] | None, tuple[str, ...] | None],
) -> None:
    body = "a" * 100
    current = _document(body)
    start = current.index(body)
    spans = [
        HighlightSpan(start, start + 40, owners[0]),
        HighlightSpan(start + 40, start + 80, owners[1]),
    ]

    revised, _blocks, _fine, whole = adaptive_blocks(current, spans)

    assert whole == 0
    assert len(revised) == 2


def test_shared_reviewer_ids_allow_whole_block_collapse() -> None:
    body = "a" * 100
    current = _document(body)
    start = current.index(body)

    spans, _blocks, _fine, whole = adaptive_blocks(
        current,
        [
            HighlightSpan(start, start + 35, ("1-1", "2-2")),
            HighlightSpan(start + 35, start + 70, ("1-1", "2-2")),
        ],
    )

    assert whole == 1
    assert spans[0].review_ids == ("1-1", "2-2")


def test_heading_highlight_stays_inside_current_heading_field() -> None:
    current = _document("\\section{Revised title}\nText.")
    title = _span(current, "Revised title", ("1-1",))

    marked = apply_highlights(current, [title])

    assert marked.index(r"\section{") < marked.index(r"\SCIReviewSpan")
    assert r"\SCIReviewSpan{1-1}{\DIFaddReview{\section" not in marked


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


def test_whitespace_addition_cannot_consume_paragraph_boundary() -> None:
    current = _document("First paragraph.\n\nSecond paragraph.")
    separator = current.index("\n\n")

    spans, _blocks, _fine, _whole = adaptive_blocks(
        current, [HighlightSpan(separator, separator + 2, None)]
    )

    assert spans == []
    assert apply_highlights(current, spans) == current


def test_cross_block_addition_collapses_only_the_covered_current_block() -> None:
    current = _document("Rewritten paragraph.\n\nNext paragraph.")
    start = current.index("Rewritten")
    crossing_end = current.index("Next") + 2

    spans, _blocks, _fine, whole = adaptive_blocks(
        current, [HighlightSpan(start, crossing_end, None)]
    )

    assert whole == 1
    assert len(spans) == 2
    separator = current.index("\n\n", start)
    assert all(not (span.start < separator < span.end) for span in spans)


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


def test_whole_block_collapse_preserves_following_separator() -> None:
    current = _document("a" * 100 + "\n\nFollowing paragraph.")
    start = current.index("a" * 100)

    spans, _blocks, _fine, whole = adaptive_blocks(
        current, [HighlightSpan(start, start + 80, ("1-1",))]
    )
    marked = apply_highlights(current, spans)

    assert whole == 1
    assert "}}\n\nFollowing paragraph." in marked


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

    assert r"}\par \DIFadd{" in marked


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

    assert r"\section{\DIFadd{Heading}" in marked
    assert r"\DIFadd{\section" not in marked


def test_display_after_highlighted_paragraph_keeps_environment_boundary() -> None:
    current = _document("Revised paragraph.\n\n\\begin{equation}x=1\\end{equation}")
    marked = apply_highlights(current, [_span(current, "Revised paragraph.")])

    assert r"\begin{equation}" in marked
    assert r"\DIFadd{\begin{equation}" not in marked


def test_highlighted_paragraph_after_display_keeps_environment_boundary() -> None:
    current = _document("\\begin{equation}x=1\\end{equation}\n\nRevised paragraph.")
    marked = apply_highlights(current, [_span(current, "Revised paragraph.")])

    assert r"\end{equation}\n\n" not in marked
    assert r"\end{equation}" in marked
    assert "\n\n\\DIFadd{Revised paragraph.}" in marked


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
def test_exact_block_move_is_suppressed(kind: str) -> None:
    if kind == "paragraph":
        parent = _document("Alpha block.\n\nBeta block.")
        current = _document("Beta block.\n\nAlpha block.")
        value = "Beta block."
    else:
        parent = _document("\\section{Alpha}\nA.\n\n\\section{Beta}\nB.")
        current = _document("\\section{Beta}\nB.\n\n\\section{Alpha}\nA.")
        value = "Beta"
    span = _span(current, value)

    retained, count = suppress_exact_moves(parent, current, [span])

    assert retained == []
    assert count >= 1


def test_moved_and_rewritten_block_keeps_best_effort_addition() -> None:
    parent = _document("Alpha block.\n\nBeta block.")
    current = _document("Beta revised block.\n\nAlpha block.")
    span = _span(current, "revised ")

    retained, _count = suppress_exact_moves(parent, current, [span])

    assert retained == [span]


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


def test_changed_display_highlights_only_current_equation_body_and_owner() -> None:
    parent = _document(r"\begin{equation}x=1\label{eq:x}\end{equation}")
    current_raw = _document(
        r"\review{1-1}{\begin{equation}x=2\label{eq:x}\end{equation}}"
    )
    current = extract_provenance(current_raw)
    additions = [_span(current.text, "2", ("1-1",))]

    equations = equation_spans(parent, current, additions)
    marked = apply_highlights(current.text, equations)

    assert len(equations) == 1
    assert r"\begin{equation}\SCIReviewDisplayBegin{1-1}" in marked
    assert r"\label{eq:x}" in marked
    assert "x=1" not in marked
    assert strip_highlight_markup(marked, STYLE_BEGIN, STYLE_END) == current.text


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


def test_unchanged_display_and_exact_moved_display_remain_black() -> None:
    equation = r"\begin{equation}x=1\label{eq:x}\end{equation}"
    parent = _document(equation + "\n\nText.")
    current = extract_provenance(_document("Text.\n\n" + equation))

    assert equation_spans(parent, current, []) == []


@pytest.mark.parametrize(
    "parent_equation,current_equation",
    (
        (
            r"\begin{equation}q\in\{\mathrm M,\mathrm D\}\label{eq:q}\end{equation}",
            "\\begin{equation}\n  q \\in \\{ \\mathrm M, \\mathrm D \\}\n"
            "  \\label{eq:q}\n\\end{equation}",
        ),
        (
            r"\begin{equation}a+b=c\label{eq:q}\end{equation}",
            "\\begin{equation}\n  a + b = c\n  \\label{eq:q}\n\\end{equation}",
        ),
    ),
)
def test_display_identity_ignores_math_layout_whitespace(
    parent_equation: str, current_equation: str
) -> None:
    parent = _document(parent_equation)
    current = extract_provenance(
        _document(f"\\review{{1-1}}{{Rewritten prose.\n\n{current_equation}}}")
    )
    additions = [_span(current.text, "Rewritten prose.", ("1-1",))]

    filtered, equations, audit = resolve_equation_spans(parent, current, additions)

    assert equations == []
    assert audit.examined == 1
    assert audit.normalized_identical == 1
    assert audit.highlighted == 0
    assert audit.ambiguous == 0
    assert filtered == additions


def test_normalized_identical_display_vetoes_internal_fine_spans() -> None:
    parent = _document(r"\begin{equation}q\in M\label{eq:q}\end{equation}")
    current = extract_provenance(
        _document(
            "\\review{1-1}{Rewritten.\n\n"
            "\\begin{equation} q \\in M \\label{eq:q}\\end{equation}}"
        )
    )
    prose = _span(current.text, "Rewritten.", ("1-1",))
    equation_fine = _span(current.text, r"q \in M", ("1-1",))

    additions, equations, audit = resolve_equation_spans(
        parent, current, [prose, equation_fine]
    )
    marked = apply_highlights(current.text, [*additions, *equations])

    assert equations == []
    assert audit.normalized_identical == 1
    assert "Rewritten." in marked and r"\SCIReviewSpan{1-1}" in marked
    equation_start = marked.index(r"\begin{equation}")
    equation_end = marked.index(r"\end{equation}")
    assert "SCIReview" not in marked[equation_start:equation_end]
    assert "DIFadd" not in marked[equation_start:equation_end]


def test_display_identity_preserves_text_argument_content() -> None:
    parent = _document(
        r"\begin{equation}x_{\text{old state}}=1\label{eq:x}\end{equation}"
    )
    current = extract_provenance(
        _document(
            r"\review{1-1}{\begin{equation}"
            r"x_{\text{new state}}=1\label{eq:x}\end{equation}}"
        )
    )
    additions = [_span(current.text, "new", ("1-1",))]

    equations, audit = analyze_equations(parent, current, additions)

    assert len(equations) == 1
    assert equations[0].review_ids == ("1-1",)
    assert audit.highlighted == 1


def test_perspective_object_definition_is_black_but_formula_six_is_reviewer_red() -> (
    None
):
    object_parent = r"""\begin{equation}
\mathcal{O}_{q}=\left\langle\mathcal{I}_{q},\mathcal{E}_{q},
\mathcal{S}_{q}\!\left(\mathcal{E}_{q}\right),
\mathcal{B}_{q}\!\left(\mathcal{E}_{q},\mathcal{S}_{q}\right),
\mathcal{C}_{q}\!\left[\mathcal{E}_{q},\mathcal{S}_{q},\mathcal{B}_{q}\right]
\right\rangle,\qquad q\in\left\{\mathrm{M},\mathrm{D},\mathrm{P},\mathrm{N}\right\}.
\label{eq:structured_object}\end{equation}"""
    object_current = object_parent.replace(r"q\in", r"q \in").replace(
        r"\mathcal{I}_{q},", "\n        \\mathcal{I}_{q},"
    )
    formula_parent = (
        r"\begin{equation}\langle a+b+c,\mathcal N_j\rangle"
        r"\Longrightarrow s\label{eq:object_coordination}\end{equation}"
    )
    formula_current = (
        r"\begin{equation}a+b+c\xrightarrow{\text{数值执行对象 }\mathcal N_j}s"
        r"\label{eq:object_coordination}\end{equation}"
    )
    parent = _document(object_parent + "\n\n" + formula_parent)
    current = extract_provenance(
        _document(object_current + "\n\n" + f"\\review{{2-2}}{{{formula_current}}}")
    )
    additions = [
        _span(current.text, r"q \in", None),
        _span(current.text, r"\xrightarrow", ("2-2",)),
    ]

    filtered, equations, audit = resolve_equation_spans(parent, current, additions)
    marked = apply_highlights(current.text, [*filtered, *equations])

    assert len(equations) == 1
    assert equations[0].review_ids == ("2-2",)
    assert "object_coordination" in current.text[equations[0].start : equations[0].end]
    assert audit.examined == 2
    assert audit.normalized_identical == 1
    assert audit.highlighted == 1
    object_start = marked.index(r"\begin{equation}")
    object_end = marked.index(r"\end{equation}")
    assert "DIFadd" not in marked[object_start:object_end]
    assert "SCIReview" not in marked[object_start:object_end]


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
