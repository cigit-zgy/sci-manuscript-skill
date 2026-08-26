"""TeX-native AUX reviewer-location regression contracts."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest

import sci_manuscript.locations as location_backend
from sci_manuscript.compile import stage_cjk_fonts
from sci_manuscript.errors import WorkflowError


def _record(
    review_ids: str,
    event_id: str,
    *,
    kind: str = "VISIBLE_REVIEW_REVISION",
    source: str = "SCIReviewSpan",
    source_line: int = 20,
) -> str:
    return "|".join(
        (
            review_ids,
            event_id,
            kind,
            source,
            str(source_line),
            f"sci:loc:r01:{event_id}:start",
            f"sci:loc:r01:{event_id}:end",
        )
    )


def _write_registry(path: Path, *records: str) -> None:
    path.write_text(
        "\n".join((location_backend.TEX_LOCATION_REGISTRY_HEADER, *records)) + "\n",
        encoding="utf-8",
    )


def _write_aux(path: Path, **labels: int | str) -> None:
    path.write_text(
        "\n".join(
            rf"\newlabel{{{label}}}{{{{{line}}}{{5}}{{}}{{}}{{}}}}"
            for label, line in labels.items()
        )
        + "\n",
        encoding="utf-8",
    )


def test_parse_location_labels_reads_only_package_namespace(tmp_path: Path) -> None:
    aux = tmp_path / "marked.aux"
    aux.write_text(
        "\n".join(
            (
                r"\newlabel{eq:formula-6}{{6}{5}{}{}{equation.6}}",
                r"\newlabel{page:4}{{4}{5}{}{}{}}",
                r"\newlabel{sci:loc:r01:e0001:start}{{152}{5}{}{}{}}",
                r"\newlabel{sci:loc:r01:e0001:end}{{158}{5}{}{}{}}",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assert location_backend.parse_location_labels(aux) == {
        "sci:loc:r01:e0001:start": 152,
        "sci:loc:r01:e0001:end": 158,
    }


def test_duplicate_location_label_with_same_value_is_stable(tmp_path: Path) -> None:
    aux = tmp_path / "marked.aux"
    aux.write_text(
        r"\newlabel{sci:loc:r01:e0001:start}{{12}{1}{}{}{}}"
        "\n"
        r"\newlabel{sci:loc:r01:e0001:start}{{12}{1}{}{}{}}"
        "\n",
        encoding="utf-8",
    )

    assert location_backend.parse_location_labels(aux) == {
        "sci:loc:r01:e0001:start": 12
    }


def test_conflicting_duplicate_location_label_fails(tmp_path: Path) -> None:
    aux = tmp_path / "marked.aux"
    aux.write_text(
        r"\newlabel{sci:loc:r01:e0001:start}{{12}{1}{}{}{}}"
        "\n"
        r"\newlabel{sci:loc:r01:e0001:start}{{13}{1}{}{}{}}"
        "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        WorkflowError,
        match=r"LINE_LOCATION_RESOLUTION_ERROR.*conflicting.*e0001:start",
    ):
        location_backend.parse_location_labels(aux)


def test_invalid_package_line_number_fails(tmp_path: Path) -> None:
    aux = tmp_path / "marked.aux"
    aux.write_text(
        r"\newlabel{sci:loc:r01:e0001:start}{{not-a-line}{1}{}{}{}}" "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        WorkflowError,
        match=r"LINE_LOCATION_RESOLUTION_ERROR.*positive integer.*e0001:start",
    ):
        location_backend.parse_location_labels(aux)


@pytest.mark.parametrize(
    ("ranges", "expected"),
    (
        (((10, 10),), "第 10 行"),
        (((20, 22),), "第 20--22 行"),
        (((30, 31), (40, 42)), "第 30--31 行和第 40--42 行"),
        (((50, 51), (52, 53)), "第 50--53 行"),
        (((60, 60), (60, 60)), "第 60 行"),
    ),
)
def test_tex_ranges_are_deduplicated_and_merged(
    tmp_path: Path,
    ranges: tuple[tuple[int, int], ...],
    expected: str,
) -> None:
    registry = tmp_path / "marked.reviewloc"
    aux = tmp_path / "marked.aux"
    records: list[str] = []
    labels: dict[str, int] = {}
    for index, (start, end) in enumerate(ranges, 1):
        event_id = f"e{index:04d}"
        records.append(_record("1-1", event_id))
        labels[f"sci:loc:r01:{event_id}:start"] = start
        labels[f"sci:loc:r01:{event_id}:end"] = end
    _write_registry(registry, *records)
    _write_aux(aux, **labels)

    locations, report = location_backend.calculate_tex_locations(registry, aux, "zh")

    assert locations == {"1-1": expected}
    assert report["location_backend"] == "tex-linelabel"
    assert report["resolved_labels"] == len(labels)
    assert report["unresolved_labels"] == []


def test_multiple_review_ids_share_one_event_range(tmp_path: Path) -> None:
    registry = tmp_path / "marked.reviewloc"
    aux = tmp_path / "marked.aux"
    _write_registry(registry, _record("1-1,2-3", "e0001"))
    _write_aux(
        aux,
        **{
            "sci:loc:r01:e0001:start": 70,
            "sci:loc:r01:e0001:end": 72,
        },
    )

    locations, _ = location_backend.calculate_tex_locations(registry, aux, "en")

    assert locations == {"1-1": "Lines 70--72", "2-3": "Lines 70--72"}


def test_reference_only_event_gets_a_location_without_revision_color(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "marked.reviewloc"
    aux = tmp_path / "marked.aux"
    _write_registry(
        registry,
        _record(
            "2-1",
            "e0001",
            kind="REVIEW_REFERENCE_LOCATION",
            source="SCIReviewReferenceSpan",
        ),
    )
    _write_aux(
        aux,
        **{
            "sci:loc:r01:e0001:start": 201,
            "sci:loc:r01:e0001:end": 203,
        },
    )

    locations, report = location_backend.calculate_tex_locations(registry, aux, "zh")

    assert locations == {"2-1": "第 201--203 行"}
    events = report["location_events"]
    assert isinstance(events, list)
    assert events[0]["event_kind"] == "REVIEW_REFERENCE_LOCATION"


def test_registry_without_reviewer_events_produces_no_location(tmp_path: Path) -> None:
    registry = tmp_path / "marked.reviewloc"
    aux = tmp_path / "marked.aux"
    _write_registry(registry)
    aux.write_text(
        r"\newlabel{eq:formula-6}{{6}{5}{}{}{equation.6}}" "\n",
        encoding="utf-8",
    )

    locations, report = location_backend.calculate_tex_locations(registry, aux, "zh")

    assert locations == {}
    assert report["location_events"] == []
    assert report["resolved_labels"] == 0


@pytest.mark.parametrize("missing_edge", ("start", "end"))
def test_missing_event_label_fails_with_traceable_context(
    tmp_path: Path, missing_edge: str
) -> None:
    registry = tmp_path / "marked.reviewloc"
    aux = tmp_path / "marked.aux"
    _write_registry(registry, _record("1-7", "e0001", source_line=332))
    labels = {
        f"sci:loc:r01:e0001:{edge}": 152 if edge == "start" else 158
        for edge in ("start", "end")
        if edge != missing_edge
    }
    _write_aux(aux, **labels)

    with pytest.raises(
        WorkflowError,
        match=(
            rf"LINE_LOCATION_RESOLUTION_ERROR.*missing {missing_edge} label.*"
            r"review ID 1-7.*event ID e0001.*source line 332"
        ),
    ):
        location_backend.calculate_tex_locations(registry, aux, "zh")


def test_reversed_event_range_fails(tmp_path: Path) -> None:
    registry = tmp_path / "marked.reviewloc"
    aux = tmp_path / "marked.aux"
    _write_registry(registry, _record("1-1", "e0001"))
    _write_aux(
        aux,
        **{
            "sci:loc:r01:e0001:start": 20,
            "sci:loc:r01:e0001:end": 19,
        },
    )

    with pytest.raises(
        WorkflowError,
        match=r"LINE_LOCATION_RESOLUTION_ERROR.*start 20 exceeds end 19.*1-1",
    ):
        location_backend.calculate_tex_locations(registry, aux, "zh")


def test_numeric_glyph_classes_cannot_create_locations_without_package_labels(
    tmp_path: Path,
) -> None:
    """Page, footnote, equation, sub/superscript, and table numbers are inert."""
    registry = tmp_path / "marked.reviewloc"
    aux = tmp_path / "marked.aux"
    _write_registry(registry)
    aux.write_text(
        "\n".join(
            (
                r"\newlabel{page:4}{{4}{1}{}{}{}}",
                r"\newlabel{footnote:2}{{2}{1}{}{}{}}",
                r"\newlabel{equation:6}{{6}{1}{}{}{}}",
                r"\newlabel{subscript:4}{{4}{1}{}{}{}}",
                r"\newlabel{superscript:2}{{2}{1}{}{}{}}",
                r"\newlabel{table-cell:400714}{{400714}{1}{}{}{}}",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    locations, _ = location_backend.calculate_tex_locations(registry, aux, "zh")

    assert locations == {}


def test_equation_is_supported_but_align_fails_without_geometry_fallback(
    tmp_path: Path,
) -> None:
    equation = tmp_path / "equation.tex"
    equation.write_text(
        r"\begin{equation}\SCIReviewDisplayBegin{1-1}PO_4^2"
        r"\SCIDisplayEnd{}\end{equation}",
        encoding="utf-8",
    )
    location_backend.validate_location_math_environments(equation)

    align = tmp_path / "align.tex"
    align.write_text(
        r"\begin{align}\SCIReviewDisplayBegin{1-1}a&=b"
        r"\SCIDisplayEnd{}\end{align}",
        encoding="utf-8",
    )
    with pytest.raises(
        WorkflowError,
        match=(
            r"LINE_LOCATION_UNSUPPORTED_MATH_ENVIRONMENT.*environment=align.*"
            r"review ID=1-1.*event ID=e0001"
        ),
    ):
        location_backend.validate_location_math_environments(align)


@pytest.mark.integration
def test_linelabel_proof_is_layout_neutral_for_text_math_and_references(
    tmp_path: Path,
) -> None:
    tectonic = shutil.which("tectonic")
    pdftotext = shutil.which("pdftotext")
    if tectonic is None or pdftotext is None:
        pytest.skip("Tectonic and pdftotext are required for the lineno proof.")
    staged_fonts = stage_cjk_fonts(tmp_path)
    if staged_fonts:
        cjk_setup = r"\setCJKmainfont[Path=./]{FandolSong-Regular.otf}"
    elif Path("/System/Library/Fonts/Supplemental/Songti.ttc").is_file():
        cjk_setup = r"\setCJKmainfont{Songti SC}"
    else:
        pytest.skip("A CJK font is required for the lineno proof.")
    body = r"""
\section{Line label proof}

\SciReviewLineStart{sci:loc:r01:e0001:start}%
This English reviewer span wraps across printed lines while retaining spaces
around inline math $S_{\mathrm{PO_4},j}(t)=4$ and mixed text 通过 Python
成为可能~\cite{proof-reference}.
\SciReviewLineEnd{sci:loc:r01:e0001:end}%

\SciReviewLineStart{sci:loc:r01:e0002:start}%
中文审稿修订段落验证中文断行以及 CJK 与 Latin 混排, 并包含行内公式
$x_j^2+y_j^3=5$ 和数值 400714。
\SciReviewLineEnd{sci:loc:r01:e0002:end}%

\begin{equation}
  \SciReviewLineStart{sci:loc:r01:e0003:start}%
  \frac{\mathrm{d}S_{\mathrm{PO_4},j}(t)}{\mathrm{d}t}
  = \mathcal{R}_{\mathrm{PO_4},j}^{\mathrm{M}}(t) + x_j^2
  \SciReviewLineEnd{sci:loc:r01:e0003:end}%
  \label{eq:proof-equation}
\end{equation}

The equation reference is \eqref{eq:proof-equation}. Citation target:
\SciReviewLineStart{sci:loc:r01:e0004:start}%
\cite{proof-reference}%
\SciReviewLineEnd{sci:loc:r01:e0004:end}.

\begin{thebibliography}{9}
\bibitem{proof-reference}
\SciReviewLineStart{sci:loc:r01:e0005:start}%
Example Author. Bibliography numbers 4, 52500063, and 400714.
\SciReviewLineEnd{sci:loc:r01:e0005:end}%
\end{thebibliography}
"""
    (tmp_path / "proof_body.tex").write_text(body, encoding="utf-8")
    preamble = r"""\documentclass[a4paper,10pt]{article}
\usepackage{xeCJK}
%%CJK_SETUP%%
\usepackage{amsmath}
\usepackage[numbers]{natbib}
\usepackage[colorlinks=true,citecolor=blue,linkcolor=blue]{hyperref}
\usepackage[mathrefs]{lineno}
\setlength{\textwidth}{12cm}
%%LABEL_MACROS%%
\begin{document}
\linenumbers
\input{proof_body.tex}
\end{document}
"""
    variants = {
        "instrumented": (
            r"\newcommand{\SciReviewLineStart}[1]{\linelabel{#1}}"
            "\n"
            r"\newcommand{\SciReviewLineEnd}[1]{\linelabel{#1}}"
        ),
        "control": (
            r"\newcommand{\SciReviewLineStart}[1]{}"
            "\n"
            r"\newcommand{\SciReviewLineEnd}[1]{}"
        ),
    }
    for name, macros in variants.items():
        source = tmp_path / f"proof_{name}.tex"
        source.write_text(
            preamble.replace("%%CJK_SETUP%%", cjk_setup).replace(
                "%%LABEL_MACROS%%", macros
            ),
            encoding="utf-8",
        )
        output = tmp_path / name
        output.mkdir()
        subprocess.run(
            [
                tectonic,
                "-X",
                "compile",
                "--keep-intermediates",
                f"--outdir={output}",
                str(source),
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )

    instrumented_pdf = tmp_path / "instrumented" / "proof_instrumented.pdf"
    control_pdf = tmp_path / "control" / "proof_control.pdf"

    def pdf_words(path: Path) -> list[tuple[str, tuple[str, ...]]]:
        xml = subprocess.run(
            [pdftotext, "-bbox", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        root = ElementTree.fromstring(xml)
        return [
            (
                "".join(word.itertext()),
                tuple(word.attrib[key] for key in ("xMin", "yMin", "xMax", "yMax")),
            )
            for word in root.iter()
            if word.tag.rsplit("}", 1)[-1] == "word"
        ]

    assert pdf_words(instrumented_pdf) == pdf_words(control_pdf)
    aux_path = tmp_path / "instrumented" / "proof_instrumented.aux"
    labels = location_backend.parse_location_labels(aux_path)
    assert len(labels) == 10
    for event_number in range(1, 6):
        start = labels[f"sci:loc:r01:e{event_number:04d}:start"]
        end = labels[f"sci:loc:r01:e{event_number:04d}:end"]
        assert 0 < start <= end
    aux = aux_path.read_text(encoding="utf-8", errors="replace")
    assert re.search(r"\\newlabel\{eq:proof-equation\}\{\{1\}", aux)
    assert re.search(r"\\bibcite\{proof-reference\}\{\{1\}", aux)
