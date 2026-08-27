"""Behavior contracts for canonical region matching and revision units."""

from __future__ import annotations

from pathlib import Path

import pytest
from sci_manuscript.errors import WorkflowError
from sci_manuscript.regions import RegionKind, project_manuscript
from sci_manuscript.revision_match import (
    ChangedUnit,
    ChangeReason,
    ChangeState,
    ProofKind,
    RevisionMatchResult,
    match_revisions,
)


def _document(body: str) -> str:
    return f"\\documentclass{{article}}\n\\begin{{document}}\n\n{body}\n\n\\end{{document}}\n"


def _changes(parent: str, current: str) -> tuple[ChangedUnit, ...]:
    return _result(parent, current).changes


def _result(parent: str, current: str) -> RevisionMatchResult:
    return match_revisions(project_manuscript(parent), project_manuscript(current))


def _changed_text(parent: str, current: str) -> list[str]:
    return [
        current[item.source_start : item.source_end]
        for item in _changes(parent, current)
    ]


def test_heading_whitespace_is_black_but_changed_h1_h2_h3_are_whole() -> None:
    parent = _document(
        "\\section{Shared heading}\n\n"
        "\\subsection{Old subsection}\n\n"
        "\\subsubsection{Old detail}\n\n"
        "Shared prose."
    )
    whitespace_only = _document(
        "\\section{  Shared   heading }\n\n"
        "\\subsection{Old subsection}\n\n"
        "\\subsubsection{Old detail}\n\n"
        "Shared prose."
    )
    current = _document(
        "\\section{Changed heading}\n\n"
        "\\subsection{Changed subsection}\n\n"
        "\\subsubsection{Changed detail}\n\n"
        "Shared prose."
    )

    assert _changes(parent, whitespace_only) == ()
    assert _changed_text(parent, current) == [
        "Changed heading",
        "Changed subsection",
        "Changed detail",
    ]
    assert [item.region_kind for item in _changes(parent, current)] == [
        RegionKind.HEADING_H1,
        RegionKind.HEADING_H2,
        RegionKind.HEADING_H3,
    ]


def test_chinese_prose_colors_only_changed_sentence_or_long_clause() -> None:
    shared = "第一句保持不变。"
    parent_short = "甲" * 36 + "旧结论保持可读。"
    current_short = "甲" * 36 + "新结论保持可读。"
    parent_long = "乙" * 20 + "，" + "旧" * 16 + "，" + "丙" * 20 + "。"  # noqa: RUF001
    current_long = "乙" * 20 + "，" + "新" * 16 + "，" + "丙" * 20 + "。"  # noqa: RUF001
    parent = _document(shared + parent_short + parent_long)
    current = _document(shared + current_short + current_long)

    assert _changed_text(parent, current) == [
        current_short,
        "新" * 16 + "，",  # noqa: RUF001
    ]


def test_duplicate_long_clause_identity_multiplicity_fails_closed() -> None:
    repeated = "甲" * 20 + "，"  # noqa: RUF001
    parent = _document(repeated + repeated + "乙" * 20 + "。")
    current = _document(
        repeated + "丙" * 20 + "，" + "乙" * 20 + "。"  # noqa: RUF001
    )

    with pytest.raises(WorkflowError, match="REVISION_MATCH_AMBIGUOUS"):
        _changes(parent, current)


def test_whole_sentence_identity_precedes_long_clause_segmentation() -> None:
    shared = (
        "污水过程具有显著的非线性、动态性和多过程耦合特征，"  # noqa: RUF001
        "其运行状态受到进水水量与水质、反应池温度、溶解氧浓度、"
        "碱度及污泥特性等多重因素共同影响"
    )
    citation = r"\cite{one,two,three,four}。"
    parent = _document(shared + citation + "旧结论需要修改。")
    current = _document(shared + "\n" + citation + "新结论需要修改。")

    result = match_revisions(project_manuscript(parent), project_manuscript(current))

    assert [
        current[item.source_start : item.source_end] for item in result.changes
    ] == ["新结论需要修改。"]
    shared_decision = next(
        item
        for item in result.decisions
        if current[item.source_start : item.source_end].startswith("污水过程具有显著")
    )
    assert shared_decision.state is ChangeState.UNCHANGED
    assert shared_decision.proof in {
        ProofKind.EXACT_IDENTITY,
        ProofKind.NORMALIZED_IDENTITY,
    }
    assert shared_decision.visual_authorized is False
    assert shared_decision.candidate_parent_ids
    assert len(result.identity_certificates) >= 1
    assert len(result.change_certificates) == 1
    assert result.change_certificates[0].event_id == "sci:rev:e0001"


def test_model_number_abbreviation_stays_in_one_unchanged_identity_sentence() -> None:
    shared = (
        "Example models include Activated Sludge Models (ASMs) and Anaerobic "
        "Digestion Model No. 1 (ADM1), while the exact scientific sentence "
        "remains unchanged across both manuscript rounds "
        r"\cite{asm,adm}."
    )
    parent = _document("旧引导句。" + shared)
    current = _document("新引导句。" + shared)

    result = _result(parent, current)
    shared_decisions = [
        item
        for item in result.decisions
        if "Anaerobic Digestion Model No. 1"
        in current[item.source_start : item.source_end]
    ]

    assert len(shared_decisions) == 1
    assert shared_decisions[0].state is ChangeState.UNCHANGED
    assert shared_decisions[0].visual_authorized is False


def test_cjk_source_line_break_after_citation_punctuation_is_identity_noise() -> None:
    parent = _document("稳定论述\\cite{one}，并继续说明科学结论。")  # noqa: RUF001
    current = _document(
        "稳定论述\n\\cite{one}，\n并继续说明科学结论。"  # noqa: RUF001
    )

    result = _result(parent, current)

    assert result.changes == ()
    decision = next(
        item
        for item in result.decisions
        if item.region_kind is RegionKind.PROSE_PARAGRAPH
    )
    assert decision.state is ChangeState.UNCHANGED
    assert decision.candidate_parent_ids


def test_unresolved_duplicate_correspondence_fails_closed() -> None:
    parent = _document("Repeated sentence.\n\nRepeated sentence.\n\nOld ending.")
    current = _document("Repeated sentence.\n\nNew middle.\n\nRepeated sentence.")

    with pytest.raises(WorkflowError, match="REVISION_MATCH_AMBIGUOUS"):
        _changes(parent, current)


def test_english_prose_colors_whole_changed_sentence_and_protects_doi() -> None:
    parent = _document(
        "Dr. Smith retained DOI 10.1000/abc.def. The old conclusion is concise."
    )
    current = _document(
        "Dr. Smith retained DOI 10.1000/abc.def. The new conclusion is concise."
    )

    assert _changed_text(parent, current) == ["The new conclusion is concise."]


def test_long_english_sentence_colors_only_the_changed_clause() -> None:
    parent = _document(
        "This deliberately long sentence contains more than thirty words for a "
        "stable scientific comparison today, keeps the unchanged middle clause "
        "available to every careful reader, and ends with the old scientific "
        "conclusion for the final report."
    )
    current = _document(
        "This deliberately long sentence contains more than thirty words for a "
        "stable scientific comparison today, keeps the unchanged middle clause "
        "available to every careful reader, and ends with the new scientific "
        "conclusion for the final report."
    )

    assert _changed_text(parent, current) == [
        "and ends with the new scientific conclusion for the final report."
    ]


def test_duplicate_identical_paragraphs_do_not_steal_the_changed_sibling() -> None:
    stable = "Repeated scientific statement."
    parent = _document(f"{stable}\n\n{stable}\n\nOld conclusion.")
    current = _document(f"{stable}\n\n{stable}\n\nNew conclusion.")

    assert _changed_text(parent, current) == ["New conclusion."]


def test_rendered_hierarchy_move_changes_heading_but_source_comment_move_does_not() -> (
    None
):
    parent = _document(
        "% BEGIN INPUT sections/old.tex\n"
        "\\section{One}\n\\subsection{Shared child}\n"
        "% END INPUT sections/old.tex\n"
        "\\section{Two}"
    )
    source_only_move = _document(
        "% BEGIN INPUT sections/new.tex\n"
        "\\section{One}\n\\subsection{Shared child}\n"
        "% END INPUT sections/new.tex\n"
        "\\section{Two}"
    )
    hierarchy_move = _document(
        "\\section{One}\n\\section{Two}\n\\subsection{Shared child}"
    )

    assert _changes(parent, source_only_move) == ()
    moved = _result(parent, hierarchy_move)
    assert moved.changes == ()
    assert [event.state for event in moved.structural_events] == [
        ChangeState.STRUCTURAL_CHANGED
    ]


def test_same_text_in_new_subsection_is_a_structural_move() -> None:
    prose = "Identical scientific statement."
    parent = _document(
        f"\\section{{One}}\n\\subsection{{A}}\n\n{prose}\n\n\\subsection{{B}}"
    )
    current = _document(
        f"\\section{{One}}\n\\subsection{{A}}\n\n\\subsection{{B}}\n\n{prose}"
    )

    result = _result(parent, current)

    assert result.changes == ()
    assert [event.state for event in result.structural_events] == [
        ChangeState.STRUCTURAL_CHANGED
    ]
    moved_decision = next(
        decision
        for decision in result.decisions
        if decision.region_kind is RegionKind.PROSE_PARAGRAPH
    )
    assert moved_decision.state is ChangeState.STRUCTURAL_CHANGED
    assert moved_decision.visual_authorized is False
    assert moved_decision.candidate_parent_ids


def test_paragraph_reorder_marks_every_participant_but_insertion_preserves_order() -> (
    None
):
    first = "First independent paragraph."
    second = "Second independent paragraph."
    parent = _document(f"\\section{{One}}\n\n{first}\n\n{second}")
    reordered = _document(f"\\section{{One}}\n\n{second}\n\n{first}")
    inserted = _document(
        f"\\section{{One}}\n\nInserted paragraph.\n\n{first}\n\n{second}"
    )

    reorder_result = _result(parent, reordered)

    assert reorder_result.changes == ()
    assert len(reorder_result.structural_events) == 2
    inserted_changes = _changes(parent, inserted)
    assert _changed_text(parent, inserted) == ["Inserted paragraph."]
    assert inserted_changes[0].reason is ChangeReason.CURRENT_ONLY


def test_frontmatter_uses_whole_title_and_item_level_keyword_and_funding() -> None:
    parent = (
        "\\documentclass{article}\n"
        "\\title{Old title}\n"
        "\\keywords{stable, old keyword}\n"
        "\\funding{Grant 123; Grant 456}\n"
        "\\begin{document}\nBody.\n\\end{document}\n"
    )
    current = (
        "\\documentclass{article}\n"
        "\\title{New title}\n"
        "\\keywords{stable, new keyword}\n"
        "\\funding{Grant 123; Grant 456; Grant 789}\n"
        "\\begin{document}\nBody.\n\\end{document}\n"
    )

    assert _changed_text(parent, current) == [
        "New title",
        "new keyword",
        "Grant 789",
    ]


def test_distinct_empty_keyword_fields_match_by_field_identity() -> None:
    parent = _document("\\keywords{}\n\\enkeywords{}\nStable body.")
    current = _document("\\keywords{new keyword}\n\\enkeywords{}\nStable body.")

    assert _changed_text(parent, current) == ["new keyword"]


def test_funding_additions_preserve_the_existing_wrapped_grant() -> None:
    parent = _document(
        "\\funding{国家自然科学基金项目（52500063）}\nStable body."  # noqa: RUF001
    )
    current = _document(
        "\\funding{国家自然科学基金项目（52500063, 52131003, 52327813）}\nStable body."  # noqa: RUF001
    )

    result = _result(parent, current)

    assert [
        current[item.source_start : item.source_end] for item in result.changes
    ] == ["52131003", "52327813"]
    added = [
        decision for decision in result.decisions if decision.state is ChangeState.ADDED
    ]
    assert len(added) == 2
    assert all(not decision.candidate_parent_ids for decision in added)


def test_author_reorder_marks_both_items_but_affiliation_stays_black() -> None:
    parent = (
        "\\documentclass{article}\n"
        "\\author{Ada Example}\n\\author{Lin Example}\n"
        "\\affiliation{Institute A}\n"
        "\\begin{document}\nBody.\n\\end{document}\n"
    )
    current = (
        "\\documentclass{article}\n"
        "\\author{Lin Example}\n\\author{Ada Example}\n"
        "\\affiliation{Institute A}\n"
        "\\begin{document}\nBody.\n\\end{document}\n"
    )

    result = _result(parent, current)

    assert result.changes == ()
    assert len(result.structural_events) == 2


def test_equation_whitespace_and_moves_are_black_but_math_change_is_whole() -> None:
    parent = _document(
        "\\section{One}\n\\subsection{A}\n"
        "\\begin{equation}x=1\\label{eq:x}\\end{equation}\n"
        "\\subsection{B}"
    )
    whitespace = _document(
        "\\section{One}\n\\subsection{A}\n"
        "\\begin{equation}\n  x = 1\n\\label{eq:x}\n\\end{equation}\n"
        "\\subsection{B}"
    )
    changed = _document(
        "\\section{One}\n\\subsection{A}\n"
        "\\begin{equation}x=2\\label{eq:x}\\end{equation}\n"
        "\\subsection{B}"
    )
    moved = _document(
        "\\section{One}\n\\subsection{A}\n\\subsection{B}\n"
        "\\begin{equation}x=1\\label{eq:x}\\end{equation}"
    )

    assert _changes(parent, whitespace) == ()
    assert _changed_text(parent, changed) == ["x=2\\label{eq:x}"]
    assert _changes(parent, moved) == ()


def test_identical_equation_reordered_in_same_section_remains_black() -> None:
    equation = "\\begin{equation}x=1\\label{eq:x}\\end{equation}"
    parent = _document(f"\\section{{One}}\nFirst paragraph.\n\n{equation}")
    current = _document(f"\\section{{One}}\n{equation}\n\nFirst paragraph.")

    equation_changes = [
        item
        for item in _changes(parent, current)
        if item.region_kind is RegionKind.DISPLAY_EQUATION
    ]
    assert equation_changes == []


def test_table_edit_uses_cell_new_row_uses_row_and_reorder_uses_rows() -> None:
    def table(rows: str) -> str:
        return _document(
            "\\begin{table}\\label{tab:a}\\begin{tabular}{cc}\n"
            + rows
            + "\\end{tabular}\\end{table}"
        )

    parent = table("A & B \\\\\n1 & 2 \\\\\n")
    edited = table("A & B \\\\\n1 & 3 \\\\\n")
    added = table("A & B \\\\\n1 & 2 \\\\\n3 & 4 \\\\\n")
    reordered = table("1 & 2 \\\\\nA & B \\\\\n")

    assert _changed_text(parent, edited) == ["3"]
    assert _changed_text(parent, added) == ["3 & 4"]
    assert _changes(parent, reordered) == ()
    assert len(_result(parent, reordered).structural_events) == 2


def test_merged_table_cell_change_highlights_the_whole_current_cell() -> None:
    parent = _document(
        "\\begin{table}\\label{tab:a}\\begin{tabular}{cc}\n"
        "\\multicolumn{2}{c}{Old heading} \\\\\n"
        "\\end{tabular}\\end{table}"
    )
    current = parent.replace("Old heading", "New heading")

    assert _changed_text(parent, current) == [r"\multicolumn{2}{c}{New heading}"]


def test_list_edit_uses_sentence_and_reorder_uses_whole_items() -> None:
    parent = _document(
        "\\begin{itemize}\n\\item Shared sentence. Old detail.\n"
        "\\item Second item.\n\\end{itemize}"
    )
    edited = _document(
        "\\begin{itemize}\n\\item Shared sentence. New detail.\n"
        "\\item Second item.\n\\end{itemize}"
    )
    reordered = _document(
        "\\begin{itemize}\n\\item Second item.\n"
        "\\item Shared sentence. Old detail.\n\\end{itemize}"
    )

    assert _changed_text(parent, edited) == ["New detail."]
    assert _changes(parent, reordered) == ()
    assert len(_result(parent, reordered).structural_events) == 2


def test_citation_key_change_does_not_revision_color_surrounding_prose() -> None:
    parent = _document("Stable claim~\\cite{old-key} remains supported.")
    current = _document("Stable claim~\\cite{new-key} remains supported.")

    assert _changes(parent, current) == ()


def test_figure_caption_change_move_and_same_path_asset_replacement(
    tmp_path: Path,
) -> None:
    def figure(section: str, asset: str, caption: str) -> str:
        return _document(
            f"\\section{{{section}}}\n"
            "\\begin{figure}"
            f"\\includegraphics{{{asset}}}"
            f"\\caption{{{caption}}}"
            "\\label{fig:a}\\end{figure}"
        )

    parent = figure("One", "figure-a.pdf", "Shared caption.")
    caption_changed = figure("One", "figure-a.pdf", "Changed caption.")
    moved_parent = _document(
        "\\section{One}\n\\begin{figure}\\includegraphics{figure-a.pdf}"
        "\\caption{Shared caption.}\\label{fig:a}\\end{figure}\n"
        "\\section{Two}"
    )
    moved_current = _document(
        "\\section{One}\n\\section{Two}\n"
        "\\begin{figure}\\includegraphics{figure-a.pdf}"
        "\\caption{Shared caption.}\\label{fig:a}\\end{figure}"
    )

    assert _changed_text(parent, caption_changed) == ["Changed caption."]
    moved_changes = _changes(moved_parent, moved_current)
    assert _changed_text(moved_parent, moved_current) == ["Shared caption."]
    assert moved_changes[0].reason is ChangeReason.CURRENT_ONLY

    parent_root = tmp_path / "parent"
    current_root = tmp_path / "current"
    parent_root.mkdir()
    current_root.mkdir()
    (parent_root / "figure-a.pdf").write_bytes(b"parent asset")
    (current_root / "figure-a.pdf").write_bytes(b"current asset")
    result = match_revisions(
        project_manuscript(parent, asset_root=parent_root),
        project_manuscript(parent, asset_root=current_root),
    )

    assert result.changes == ()
    assert result.audit.figure_asset_changes == 1


def test_duplicate_table_rows_reorder_without_coloring_the_wrong_row() -> None:
    def table(rows: str) -> str:
        return _document(
            "\\begin{table}\\label{tab:a}\\begin{tabular}{c}\n"
            + rows
            + "\\end{tabular}\\end{table}"
        )

    parent = table("Repeated \\\\\nRepeated \\\\\nDistinct \\\\\n")
    current = table("Repeated \\\\\nDistinct \\\\\nRepeated \\\\\n")

    with pytest.raises(WorkflowError, match="REVISION_MATCH_AMBIGUOUS"):
        _changes(parent, current)


def test_duplicate_list_item_never_matches_across_list_owners() -> None:
    parent = _document(
        "\\begin{itemize}\\item Shared item.\\end{itemize}\n"
        "\\begin{itemize}\\item Other item.\\end{itemize}"
    )
    current = _document(
        "\\begin{itemize}\\item Replacement item.\\end{itemize}\n"
        "\\begin{itemize}\\item Other item.\\item Shared item.\\end{itemize}"
    )

    assert "Shared item." in _changed_text(parent, current)


def test_same_h2_title_under_sibling_h1_cannot_cross_match_changed_heading() -> None:
    parent = _document(
        "\\section{First}\\subsection{Shared}\n\\section{Second}\\subsection{Shared}"
    )
    current = _document(
        "\\section{First}\\subsection{Changed}\n\\section{Second}\\subsection{Shared}"
    )

    assert _changed_text(parent, current) == ["Changed"]
