"""Future-facing contracts for the current-layout marked architecture."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from sci_manuscript.compile import SciStateEvent
from sci_manuscript.diff import (
    _complete_revision_truth,
    _locate_additions,
    _mask_overridden_frontmatter_fields,
    _validate_revision_render_registry,
    extract_addition_evidence,
    prepare_change_detection_sources,
    run_latexdiff,
    structure_highlight_spans,
)
from sci_manuscript.provenance import extract_provenance
from sci_manuscript.revision_render import HighlightSpan, apply_highlights

STYLE_BEGIN = "% SCI_DIFF_STYLE_BEGIN"
STYLE_END = "% SCI_DIFF_STYLE_END"


def test_render_registry_compares_identity_not_tex_execution_order() -> None:
    expected = (
        SciStateEvent("REVISION", ("sci:rev:e0001", "author")),
        SciStateEvent("REVISION", ("sci:rev:e0002", "reviewer", "1-1")),
    )
    actual = (
        SciStateEvent("MARKED_SCHEMA", ("1",)),
        expected[1],
        expected[0],
    )

    _validate_revision_render_registry(expected, actual)


def test_structure_match_decides_what_before_provenance_decides_who() -> None:
    parent = (
        "\\documentclass{article}\\begin{document}"
        "\\section{Old heading}Stable sentence. Old sentence."
        "\\end{document}"
    )
    current = extract_provenance(
        "\\documentclass{article}\\begin{document}"
        "\\section{\\review{1-1}{New heading}}"
        "\\review{1-2}{Stable sentence.} Author sentence."
        "\\end{document}"
    )

    spans, audit = structure_highlight_spans(parent, current)
    marked = apply_highlights(current.text, spans)

    assert audit.changed_units == 2
    assert (
        r"\SCIReviewSpan{1-1}{\SciReviewerRevision{sci:rev:e0001}{1-1}"
        r"{New heading}}" in marked
    )
    assert "Stable sentence." in marked
    assert r"\SciReviewerRevision{sci:rev:e0002}{1-2}{Stable sentence.}" not in marked
    assert r"\SciAuthorRevision{sci:rev:e0002}{Author sentence.}" in marked


def test_change_certificates_render_through_named_event_macros(
    tmp_path: Path,
) -> None:
    parent = (
        "\\documentclass{article}\\begin{document}"
        "Old author sentence. Old reviewer sentence."
        "\\end{document}"
    )
    current = extract_provenance(
        "\\documentclass{article}\\begin{document}"
        "New author sentence. \\review{1-1}{New reviewer sentence.}"
        "\\end{document}"
    )

    truth = tmp_path / "revision_truth.json"
    spans, audit = structure_highlight_spans(parent, current, truth_path=truth)
    marked = apply_highlights(current.text, spans)
    payload = json.loads(truth.read_text(encoding="utf-8"))

    assert audit.change_certificates == 2
    assert [span.event_id for span in spans] == [
        "sci:rev:e0001",
        "sci:rev:e0002",
    ]
    assert r"\SciAuthorRevision{sci:rev:e0001}{New author sentence.}" in marked
    assert (
        r"\SCIReviewSpan{1-1}{\SciReviewerRevision{sci:rev:e0002}{1-1}"
        r"{New reviewer sentence.}}" in marked
    )
    assert r"\DIFadd{" not in marked
    assert r"\DIFaddReview{" not in marked
    assert payload["summary"]["change_certificates"] == 2
    assert len(payload["authorized_highlights"]) == 2


def test_completed_truth_manifest_records_exact_tex_render_registry(
    tmp_path: Path,
) -> None:
    truth = tmp_path / "revision_truth.json"
    truth.write_text('{"summary": {}, "performance_seconds": {}}\n', encoding="utf-8")
    events = (
        SciStateEvent("REVISION", ("sci:rev:e0002", "reviewer", "1-1")),
        SciStateEvent("REVISION", ("sci:rev:e0001", "author")),
    )

    _complete_revision_truth(truth, events, 0.125)
    payload = json.loads(truth.read_text(encoding="utf-8"))

    assert payload["summary"]["render_certificates"] == 2
    assert payload["summary"]["unexpected_render_events"] == 0
    assert payload["summary"]["missing_render_events"] == 0
    assert [item["event_id"] for item in payload["render_certificates"]] == [
        "sci:rev:e0001",
        "sci:rev:e0002",
    ]
    assert payload["performance_seconds"]["tex_sidecar_validation"] == 0.125


def test_structure_match_preserves_mixed_provenance_boundaries() -> None:
    parent = (
        "\\documentclass{article}\\begin{document}"
        "Shared opening, old author detail, old reviewer detail."
        "\\end{document}"
    )
    current = extract_provenance(
        "\\documentclass{article}\\begin{document}"
        "Shared opening, new author detail, "
        "\\review{2-3}{new reviewer detail.}"
        "\\end{document}"
    )

    spans, _audit = structure_highlight_spans(parent, current)
    marked = apply_highlights(current.text, spans)

    assert (
        r"\SciAuthorRevision{sci:rev:e0001}{Shared opening, new author detail,}"
        in marked
    )
    assert (
        r"\SCIReviewSpan{2-3}{\SciReviewerRevision{sci:rev:e0002}{2-3}"
        r"{new reviewer detail.}}" in marked
    )


def test_auxiliary_evidence_cannot_decide_provenance() -> None:
    parent = (
        "\\documentclass{article}\\begin{document}Old author sentence.\\end{document}"
    )
    current = extract_provenance(
        "\\documentclass{article}\\begin{document}New author sentence.\\end{document}"
    )
    start = current.text.index("New author sentence")
    evidence = [HighlightSpan(start, start + len("New author sentence"), ("1-4",))]

    spans, _audit = structure_highlight_spans(parent, current, evidence=evidence)
    marked = apply_highlights(current.text, spans)

    assert [span.review_ids for span in spans] == [None]
    assert r"\SciAuthorRevision{sci:rev:e0001}{New author sentence.}" in marked


def test_identity_certificate_records_detector_disagreement(tmp_path: Path) -> None:
    parent = (
        "\\documentclass{article}\\begin{document}"
        "Stable scientific sentence."
        "\\end{document}"
    )
    current = extract_provenance(parent)
    start = current.text.index("Stable scientific sentence")
    truth = tmp_path / "revision_truth.json"

    spans, _audit = structure_highlight_spans(
        parent,
        current,
        evidence=[
            HighlightSpan(start, start + len("Stable scientific sentence"), None)
        ],
        truth_path=truth,
    )
    payload = json.loads(truth.read_text(encoding="utf-8"))

    assert spans == []
    assert payload["summary"]["detector_disagreements"] == 1
    assert len(payload["detector_disagreements"]) == 1


def test_unchanged_display_inside_review_scope_stays_black() -> None:
    equation = r"\begin{equation}x=1\label{eq:x}\end{equation}"
    parent = "\\documentclass{article}\\begin{document}" + equation + "\\end{document}"
    current = extract_provenance(
        "\\documentclass{article}\\begin{document}"
        + rf"\review{{1-5}}{{{equation}}}"
        + "\\end{document}"
    )

    spans, _audit = structure_highlight_spans(parent, current)

    assert spans == []


def test_structure_match_renders_changed_display_as_one_valid_environment() -> None:
    parent = (
        "\\documentclass{article}\\begin{document}"
        "\\begin{equation}x=1\\label{eq:x}\\end{equation}"
        "\\end{document}"
    )
    current = extract_provenance(
        "\\documentclass{article}\\begin{document}"
        "\\begin{equation}x=2\\label{eq:x}\\end{equation}"
        "\\end{document}"
    )

    spans, _audit = structure_highlight_spans(parent, current)
    marked = apply_highlights(current.text, spans)

    assert len(spans) == 1
    assert spans[0].kind == "display"
    assert (
        r"\begin{equation}\SciAuthorDisplayRevisionBegin{sci:rev:e0001}"
        r"x=2\label{eq:x}"
        r"\SCIDisplayEnd{}\end{equation}" in marked
    )


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
        / "src/resources/revision/marked_runtime.tex"
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
    inactive_start = provenance.text.index("Inactive overwritten draft.")
    active_start = provenance.text.index("Shared prose remains black.")
    assert unresolved == ()
    assert not any(span.start <= inactive_start < span.end for span in spans)
    assert not any(span.start <= active_start < span.end for span in spans)


def test_abstract_mixed_author_and_reviewer_additions_keep_ownership() -> None:
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
    spans, _audit = structure_highlight_spans(parent_text, provenance)
    marked = apply_highlights(provenance.text, spans)

    assert r"\SciAuthorRevision{sci:rev:e0001}{Author addition.}" in marked
    assert (
        r"\SCIReviewSpan{1-1}{\SciReviewerRevision{sci:rev:e0002}{1-1}"
        r"{Reviewer addition.}}" in marked
    )
