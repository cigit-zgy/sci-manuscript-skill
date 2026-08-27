"""Behavior contracts for publisher-independent manuscript projection."""

from __future__ import annotations

import pytest
from sci_manuscript.errors import WorkflowError
from sci_manuscript.regions import RegionKind, project_manuscript


def _block_text(source: str, kind: RegionKind) -> list[str]:
    return [
        source[block.source_start : block.source_end]
        for block in project_manuscript(source).blocks
        if block.kind is kind
    ]


def test_headings_project_whole_visible_fields_with_rendered_hierarchy() -> None:
    source = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{First heading}\n\n"
        "First paragraph.\n\n"
        "\\subsection{Nested heading}\n\n"
        "Nested paragraph.\n"
        "\\end{document}\n"
    )

    projection = project_manuscript(source)
    headings = [
        block for block in projection.blocks if block.kind.name.startswith("HEADING_")
    ]
    paragraphs = [
        block for block in projection.blocks if block.kind is RegionKind.PROSE_PARAGRAPH
    ]

    assert [source[item.source_start : item.source_end] for item in headings] == [
        "First heading",
        "Nested heading",
    ]
    assert headings[0].structural_path == ("mainmatter",)
    assert headings[1].structural_path == ("mainmatter", "heading_h1:1")
    assert paragraphs[0].structural_path == ("mainmatter", "heading_h1:1")
    assert paragraphs[1].structural_path == (
        "mainmatter",
        "heading_h1:1",
        "heading_h2:1",
    )


def test_chinese_prose_uses_50_atom_sentence_and_15_atom_max_three_clauses() -> None:
    short_sentence = "甲" * 25 + "，" + "乙" * 25 + "。"  # noqa: RUF001
    long_sentence = (
        "丙" * 20 + "，" + "丁" * 10 + "，" + "戊" * 20 + "，" + "己" * 10 + "。"  # noqa: RUF001
    )
    source = (
        "\\documentclass{article}\n\\begin{document}\n\n"
        f"{short_sentence}{long_sentence}\n\n"
        "\\end{document}\n"
    )

    paragraph = next(
        block
        for block in project_manuscript(source).blocks
        if block.kind is RegionKind.PROSE_PARAGRAPH
    )

    rendered = [source[unit.source_start : unit.source_end] for unit in paragraph.units]
    assert rendered[0] == short_sentence
    assert len(rendered[1:]) <= 3
    assert "".join(rendered[1:]) == long_sentence
    assert all(unit.kind is RegionKind.CLAUSE for unit in paragraph.units[1:])
    assert all(
        sum(character.isalnum() for character in item) >= 15 for item in rendered[1:]
    )


def test_english_prose_uses_30_words_and_merges_short_clauses_to_max_three() -> None:
    short = (
        "One two three four five six seven eight nine ten, eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone "
        "twentytwo twentythree twentyfour twentyfive twentysix twentyseven "
        "twentyeight twentynine thirty."
    )
    long = (
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda, "
        "short linking phrase for the stable comparison, mu nu xi omicron pi rho "
        "sigma tau upsilon phi chi psi, brief ending words remain scientifically "
        "clear for readers."
    )
    source = _document_with_prose(short + " " + long)
    paragraph = next(
        block
        for block in project_manuscript(source).blocks
        if block.kind is RegionKind.PROSE_PARAGRAPH
    )
    rendered = [source[unit.source_start : unit.source_end] for unit in paragraph.units]

    assert rendered[0] == short
    assert len(rendered[1:]) <= 3
    assert " ".join(item.strip() for item in rendered[1:]) == long
    assert all(
        len(item.replace(",", "").replace(".", "").split()) >= 10
        for item in rendered[1:]
    )


def _document_with_prose(prose: str) -> str:
    return (
        "\\documentclass{article}\n\\begin{document}\n\n"
        + prose
        + "\n\n\\end{document}\n"
    )


@pytest.mark.parametrize(
    ("frontmatter", "expected_abstract", "expected_keywords"),
    (
        (
            "\\title{Chinese title}\n"
            "\\begin{abstract}Chinese abstract.\\end{abstract}\n"
            "\\keywords{one，two}\n",  # noqa: RUF001
            "Chinese abstract.",
            ["one", "two"],
        ),
        (
            "\\title{Elsevier title}\n"
            "\\begin{frontmatter}\\begin{abstract}Elsevier abstract."
            "\\end{abstract}\\begin{keyword}one; two\\end{keyword}"
            "\\end{frontmatter}\n",
            "Elsevier abstract.",
            ["one", "two"],
        ),
        (
            "\\title{Nature title}\n"
            "\\abstract{Nature abstract.}\n\\keywords{one, two}\n",
            "Nature abstract.",
            ["one", "two"],
        ),
        (
            "\\title{ACS title}\n"
            "\\keywords{one, two}\n"
            "\\begin{abstract}ACS abstract.\\end{abstract}\n",
            "ACS abstract.",
            ["one", "two"],
        ),
    ),
)
def test_four_publisher_frontmatter_shapes_share_canonical_regions(
    frontmatter: str,
    expected_abstract: str,
    expected_keywords: list[str],
) -> None:
    source = (
        "\\documentclass{article}\n"
        + frontmatter
        + "\\begin{document}\nBody.\n\\end{document}\n"
    )

    assert _block_text(source, RegionKind.DOCUMENT_TITLE) == [
        frontmatter.split("\\title{", 1)[1].split("}", 1)[0]
    ]
    assert _block_text(source, RegionKind.ABSTRACT) == [expected_abstract]
    keyword_block = next(
        block
        for block in project_manuscript(source).blocks
        if block.kind is RegionKind.KEYWORDS
    )
    assert [
        source[unit.source_start : unit.source_end].strip()
        for unit in keyword_block.units
    ] == expected_keywords


def test_frontmatter_commands_accept_star_and_optional_arguments_but_skip_definitions() -> (
    None
):
    source = r"""\documentclass{article}
\newcommand*\author[2][]{definition only}
\newcommand*\affiliation[2][]{definition only}
\title[Short title]{Visible title}
\author[1]{Elsevier Author}
\author*[2]{Nature Corresponding Author}
\affiliation[1]{Elsevier Institute}
\affil[2]{Nature Institute}
\begin{document}
Body.
\end{document}
"""

    assert _block_text(source, RegionKind.DOCUMENT_TITLE) == ["Visible title"]
    assert _block_text(source, RegionKind.AUTHOR_ITEM) == [
        "Elsevier Author",
        "Nature Corresponding Author",
    ]
    assert _block_text(source, RegionKind.AFFILIATION_ITEM) == [
        "Elsevier Institute",
        "Nature Institute",
    ]


def test_english_sentence_boundaries_protect_abbreviation_decimal_doi_and_url() -> None:
    prose = (
        "Dr. Smith used e.g. Model No. 1 in Fig. 2 and Eq. 3, following "
        "Doe et al. while measuring 3.14 at "
        "https://example.org/a,b "
        "and citing DOI 10.1000/abc.def. The revised conclusion follows."
    )
    source = (
        "\\documentclass{article}\n\\begin{document}\n\n"
        + prose
        + "\n\n\\end{document}\n"
    )

    paragraph = next(
        block
        for block in project_manuscript(source).blocks
        if block.kind is RegionKind.PROSE_PARAGRAPH
    )

    assert [
        source[unit.source_start : unit.source_end] for unit in paragraph.units
    ] == [
        "Dr. Smith used e.g. Model No. 1 in Fig. 2 and Eq. 3, following "
        "Doe et al. while measuring 3.14 at "
        "https://example.org/a,b "
        "and citing DOI 10.1000/abc.def.",
        "The revised conclusion follows.",
    ]


def test_clause_segmentation_does_not_split_protected_commas() -> None:
    prose = (
        "This deliberately extended scientific sentence contains more than thirty "
        "ordinary visible words for robust segmentation and comparison, "
        r"keeps citation \cite{alpha,beta} and inline math $f(x,y)$ protected, "
        "and preserves the final scientific conclusion for every careful reader "
        "who evaluates the resulting manuscript."
    )
    source = _document_with_prose(prose)
    paragraph = next(
        block
        for block in project_manuscript(source).blocks
        if block.kind is RegionKind.PROSE_PARAGRAPH
    )

    rendered = [source[unit.source_start : unit.source_end] for unit in paragraph.units]
    assert any(r"\cite{alpha,beta}" in item for item in rendered)
    assert any("$f(x,y)$" in item for item in rendered)
    assert len(rendered) <= 3


def test_prose_records_math_citation_reference_and_link_protected_spans() -> None:
    prose = (
        r"Changed $x=1$ text cites \cite{a,b}, uses \eqref{eq:x}, "
        r"and links \doi{10.1000/example}."
    )
    source = (
        "\\documentclass{article}\n\\begin{document}\n\n"
        + prose
        + "\n\n\\end{document}\n"
    )

    paragraph = next(
        block
        for block in project_manuscript(source).blocks
        if block.kind is RegionKind.PROSE_PARAGRAPH
    )

    assert [item.kind for item in paragraph.protected_spans] == [
        RegionKind.INLINE_MATH,
        RegionKind.CITATION,
        RegionKind.CROSS_REFERENCE,
        RegionKind.URL_DOI,
    ]
    assert [item.identity for item in paragraph.protected_spans] == [
        "$x=1$",
        "a,b",
        "eq:x",
        "10.1000/example",
    ]


def test_equation_figure_table_list_and_bibliography_are_separate_regions() -> None:
    source = r"""\documentclass{article}
\begin{document}
\section{Methods}

\begin{equation}
x = 1
\label{eq:x}
\end{equation}

\begin{figure}
\includegraphics{figure-a.pdf}
\caption{Figure caption changed.}
\label{fig:a}
\end{figure}

\begin{table}
\caption{Table caption.}
\label{tab:a}
\begin{tabular}{cc}
A & B \\
1 & 2 \\
\end{tabular}
\end{table}

\begin{itemize}
\item First item.
\item Second item.
\end{itemize}

\begin{thebibliography}{9}
\bibitem{key-a} Entry A. \doi{10.1000/a}
\end{thebibliography}
\end{document}
"""

    projection = project_manuscript(source)

    assert _block_text(source, RegionKind.DISPLAY_EQUATION) == [
        "\nx = 1\n\\label{eq:x}\n"
    ]
    assert _block_text(source, RegionKind.FIGURE_CAPTION) == ["Figure caption changed."]
    assert _block_text(source, RegionKind.TABLE_CAPTION) == ["Table caption."]
    assert _block_text(source, RegionKind.TABLE_ROW) == ["A & B", "1 & 2"]
    assert _block_text(source, RegionKind.TABLE_CELL) == ["A", "B", "1", "2"]
    assert _block_text(source, RegionKind.LIST_ITEM) == [
        "First item.",
        "Second item.",
    ]
    entries = [
        block
        for block in projection.blocks
        if block.kind is RegionKind.BIBLIOGRAPHY_ENTRY
    ]
    assert [item.identity for item in entries] == ["key-a"]
    assert [item.kind for item in entries[0].protected_spans] == [RegionKind.URL_DOI]


def test_bilingual_caption_fields_are_independent_caption_regions() -> None:
    source = r"""\documentclass{article}
\begin{document}
\begin{figure}
\includegraphics{figure-a.pdf}
\bicaption{中文图题。}{English caption.}
\label{fig:a}
\end{figure}
\end{document}
"""

    captions = [
        block
        for block in project_manuscript(source).blocks
        if block.kind is RegionKind.FIGURE_CAPTION
    ]

    assert [source[item.source_start : item.source_end] for item in captions] == [
        "中文图题。",
        "English caption.",
    ]
    assert [item.ordinal for item in captions] == [1, 2]


def test_author_affiliation_note_and_funding_fields_use_natural_items() -> None:
    source = r"""\documentclass{article}
\author{Ada Example}
\author{Lin Example}
\affiliation{Institute A}
\email{ada@example.org}
\funding{Grant 123; Grant 456}
\begin{document}
Body.
\end{document}
"""

    projection = project_manuscript(source)

    assert _block_text(source, RegionKind.AUTHOR_ITEM) == [
        "Ada Example",
        "Lin Example",
    ]
    assert _block_text(source, RegionKind.AFFILIATION_ITEM) == ["Institute A"]
    assert _block_text(source, RegionKind.AUTHOR_NOTE) == ["ada@example.org"]
    funding = next(
        block
        for block in projection.blocks
        if block.kind is RegionKind.FUNDING_FRONTMATTER
    )
    assert [source[unit.source_start : unit.source_end] for unit in funding.units] == [
        "Grant 123",
        "Grant 456",
    ]


def test_funding_wrapper_is_not_part_of_each_grant_identity() -> None:
    source = (
        "\\documentclass{article}\n"
        "\\funding{国家自然科学基金项目（52500063, 52131003, 52327813）}\n"  # noqa: RUF001
        "\\begin{document}Body.\\end{document}\n"
    )

    projection = project_manuscript(source)
    funding = next(
        block
        for block in projection.blocks
        if block.kind is RegionKind.FUNDING_FRONTMATTER
    )

    assert [source[unit.source_start : unit.source_end] for unit in funding.units] == [
        "52500063",
        "52131003",
        "52327813",
    ]


def test_malformed_region_reports_actionable_ambiguity() -> None:
    source = "\\title{Unclosed\n\\begin{document}\nBody.\\end{document}\n"

    with pytest.raises(WorkflowError) as error:
        project_manuscript(source)

    message = str(error.value)
    assert "REGION_CLASSIFICATION_AMBIGUOUS" in message
    assert "file: <flattened manuscript>" in message
    assert "line:" in message
    assert "region context:" in message
    assert "nearby TeX:" in message


def test_footnote_and_named_backmatter_environments_are_natural_regions() -> None:
    source = r"""\documentclass{article}
\begin{document}
Main claim.\footnote{Footnote sentence.}
\begin{acknowledgements}Acknowledgement sentence.\end{acknowledgements}
\begin{authorcontributions}Author contribution sentence.\end{authorcontributions}
\begin{competinginterests}No competing interests.\end{competinginterests}
\begin{dataavailability}Data are available.\end{dataavailability}
\begin{codeavailability}Code is available.\end{codeavailability}
\begin{supplementarystatement}Supplementary statement.\end{supplementarystatement}
\end{document}
"""

    assert _block_text(source, RegionKind.FOOTNOTE) == ["Footnote sentence."]
    assert _block_text(source, RegionKind.ACKNOWLEDGEMENTS) == [
        "Acknowledgement sentence."
    ]
    assert _block_text(source, RegionKind.AUTHOR_CONTRIBUTIONS) == [
        "Author contribution sentence."
    ]
    assert _block_text(source, RegionKind.COMPETING_INTERESTS) == [
        "No competing interests."
    ]
    assert _block_text(source, RegionKind.DATA_AVAILABILITY) == ["Data are available."]
    assert _block_text(source, RegionKind.CODE_AVAILABILITY) == ["Code is available."]
    assert _block_text(source, RegionKind.SUPPLEMENTARY_STATEMENT) == [
        "Supplementary statement."
    ]


def test_starred_heading_preserves_hierarchy_and_h4_plus_unit() -> None:
    source = r"""\documentclass{article}
\begin{document}
\section*{One}
\subsection*{Two}
\subsubsection*{Three}
\paragraph*{Four}
Body.
\end{document}
"""

    projection = project_manuscript(source)

    assert _block_text(source, RegionKind.HEADING_H1) == ["One"]
    assert _block_text(source, RegionKind.HEADING_H2) == ["Two"]
    assert _block_text(source, RegionKind.HEADING_H3) == ["Three"]
    h4 = next(
        block for block in projection.blocks if block.kind is RegionKind.HEADING_H4_PLUS
    )
    assert source[h4.source_start : h4.source_end] == "Four"
    body = next(
        block for block in projection.blocks if block.kind is RegionKind.PROSE_PARAGRAPH
    )
    assert body.structural_path == (
        "mainmatter",
        "heading_h1:1",
        "heading_h2:1",
        "heading_h3:1",
        "heading_h4:1",
    )
