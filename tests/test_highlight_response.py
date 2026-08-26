"""Response-letter contracts for highlighted current-only revisions."""

# ruff: noqa: RUF001 -- exact frozen Chinese and English typography snapshots.

from __future__ import annotations

from pathlib import Path

import pytest

from sci_manuscript.locations import _format_locations
from sci_manuscript.response import _body_tex
from sci_manuscript.review import ReviewBlock, ReviewComment

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src/sci_manuscript/resources/correspondence_templates/response"


def _block(prefix: str, review_id: str) -> ReviewBlock:
    return ReviewBlock(
        f"Reviewer #{prefix}",
        prefix,
        ("General comment.",),
        (ReviewComment(review_id, ("Specific comment.",)),),
    )


def _template(language: str) -> str:
    return (TEMPLATES / f"response_{language}.tex").read_text(encoding="utf-8")


ZH_FIXED_OPENING = r"""尊敬的编辑：\par
\vspace{0.50\baselineskip}
感谢您给予我们修改稿件《\ManuscriptTitle》的机会，并考虑将其发表于《\JournalName》。衷心感谢编辑和审稿人对本稿件的认真评阅以及富有建设性的意见和建议，这些意见帮助我们进一步完善了稿件。\par
\vspace{0.62\baselineskip}
我们已对所有审稿意见和问题进行了逐条回复，并根据相关意见对稿件进行了相应修改。为便于编辑和审稿人查阅，因审稿意见而新增或修改的正文内容以红色标示，作者在修订过程中主动新增或修改的正文内容以绿色标示。对于涉及正文修改的意见，我们同时在相应的逐条回复中注明了具体修改位置。\par
\vspace{1.05\baselineskip}
\CorrespondenceAuthorsZh"""

EN_FIXED_OPENING = r"""Dear Editor,\par
\vspace{0.50\baselineskip}
We sincerely thank the Editor and reviewers for their careful evaluation and constructive comments on our manuscript entitled ``\ManuscriptTitle,'' which is being considered for publication in \textit{\JournalName}. These comments have helped us further improve the manuscript.\par
\vspace{0.62\baselineskip}
We have provided point-by-point responses to all comments and questions and revised the manuscript accordingly. To facilitate review, text added or revised in response to the reviewers' comments is highlighted in red, whereas additional revisions made by the authors during the revision process are highlighted in green. For comments that resulted in changes to the manuscript, the corresponding locations are also specified in the respective responses.\par
\vspace{1.05\baselineskip}
\CorrespondenceAuthorsEn"""


def _opening(template: str) -> str:
    return template.split(r"\begin{document}", 1)[1].split(r"\clearpage", 1)[0].strip()


def test_package_templates_own_exact_fixed_opening_snapshots() -> None:
    assert _opening(_template("zh")) == ZH_FIXED_OPENING
    assert _opening(_template("en")) == EN_FIXED_OPENING
    for language in ("zh", "en"):
        text = _template(language)
        assert "%%RESPONSE_LETTER%%" not in text
        assert text.count("%%RESPONSE_BODY%%") == 1


def test_response_signature_is_fixed_and_includes_primary_address() -> None:
    chinese = _template("zh")
    english = _template("en")
    assert r"\CorrespondenceAuthorsZh" in chinese
    assert r"\CorrespondenceAuthorsEn" in english


def test_response_templates_forbid_signoffs_and_extra_first_page_prose() -> None:
    chinese = _template("zh")
    english = _template("en")
    for phrase in ("此致", "敬礼", "谨代表全体作者", "代表全体作者"):
        assert phrase not in chinese
    for phrase in ("Sincerely", "On behalf of all authors", "on behalf of all authors"):
        assert phrase not in english
    for phrase in ("稿件题目：", "期刊：", "回复信", "稿件编号："):
        assert phrase not in chinese
    for phrase in ("Manuscript ID:", "Response Letter"):
        assert phrase not in english


def test_pure_deletion_location_note_is_rendered_without_a_fake_line() -> None:
    body = _body_tex((_block("1", "1-1"),), "zh", {"1-1": "Reply."}, {"1-1"})
    note = "相关内容已删除，当前稿无对应高亮文本"

    rendered = body.replace(r"\ReviewLocation{1-1}", note)

    assert rf"\reviewlocation{{{note}}}" in rendered
    assert note in rendered
    assert "第 1 行" not in rendered
    assert r"\ResponseEntryEnd" not in rendered


def test_only_inter_comment_seams_own_entry_end() -> None:
    block = ReviewBlock(
        "Reviewer #1",
        "1",
        (),
        (
            ReviewComment("1-1", ("First comment.",)),
            ReviewComment("1-2", ("Second comment.",)),
        ),
    )

    body = _body_tex(
        (block,),
        "en",
        {"1-1": "Revised response.", "1-2": "Response only."},
        {"1-1"},
    )

    assert body.count(r"\ResponseEntryEnd") == 1
    assert body.count(r"\reviewlocation{") == 1
    first_end = body.index(r"\ResponseEntryEnd")
    second_comment = body.index(r"\begin{reviewcomment}{1-2}")
    assert first_end < second_comment
    assert body.rindex(r"\ResponseEntryEnd") < body.rindex(r"\end{response}")


def test_editor_empty_response_preview_keeps_local_entry_spacing() -> None:
    body = _body_tex((_block("E", "E-1"),), "zh", {"E-1": ""}, set())

    assert r"\ResponseSection{编辑}" in body
    assert body.index(r"\begin{response}") < body.index(r"\end{response}")
    assert body.count(r"\ResponseEntryEnd") == 0
    assert r"\reviewlocation{" not in body


def test_reviewer_sections_never_force_a_page_break() -> None:
    body = _body_tex(
        (_block("1", "1-1"), _block("2", "2-1")),
        "en",
        {"1-1": "Reply one.", "2-1": "Reply two."},
        {"1-1", "2-1"},
    )

    assert body.count(r"\ResponseSection") == 2
    assert r"\clearpage" not in body


def test_last_comment_does_not_stack_entry_and_reviewer_spacing() -> None:
    body = _body_tex(
        (_block("1", "1-1"), _block("2", "2-1")),
        "en",
        {"1-1": "Reply one.", "2-1": "Reply two."},
        set(),
    )
    between = body.split(r"\end{response}", 1)[1].split(
        r"\ResponseSection{Reviewer \#2}", 1
    )[0]
    assert r"\ResponseEntryEnd" not in between


def test_response_templates_have_one_clearpage_and_no_spacing_stack() -> None:
    for language in ("zh", "en"):
        text = _template(language)
        assert text.count(r"\clearpage") == 1
        assert r"\setlength{\parskip}{0pt}" in text
        assert r"\smallskip" not in text
        assert r"\medskip" not in text
        assert r"\addvspace" not in text


def test_response_rhythm_uses_frozen_component_spacing() -> None:
    for language in ("zh", "en"):
        text = _template(language)
        for value in (
            "0.12",
            "0.20",
            "0.25",
            "0.32",
            "0.36",
            "0.62",
            "0.65",
            "0.90",
            "1.05",
            "1.35",
            "1.20",
        ):
            assert f"{value}\\baselineskip" in text


def test_reply_heading_and_location_use_final_component_spacing() -> None:
    for language in ("zh", "en"):
        text = _template(language)

        assert "after skip=0.32\\baselineskip" in text
        assert (
            r"\vspace{0.12\baselineskip}\setlength{\parskip}{0.36\baselineskip}" in text
        )
        assert r"\newcommand{\ResponseEntryEnd}{\par\vspace{1.35\baselineskip}}" in text
        location = text.split(r"\newcommand{\reviewlocation}", 1)[1].split(
            r"\newcommand{\ResponseEntryEnd}", 1
        )[0]
        assert r"\vspace{0.25\baselineskip}" in location
        assert "after skip=0.40\\baselineskip" not in text


def test_reviewer_heading_and_panel_spacing_are_frozen() -> None:
    for language in ("zh", "en"):
        text = _template(language)
        assert r"\vspace{0.65\baselineskip}" in text
        assert "after skip=0.90\\baselineskip" in text
        assert "after skip=0.32\\baselineskip" in text
        assert r"\par\vspace{1.20\baselineskip}" in text


def test_opening_omits_forbidden_policy_and_legacy_wording() -> None:
    combined = _template("zh") + _template("en")
    forbidden = (
        "以下按照审稿人的意见列出相应回复",
        "以下按照编辑和审稿人的意见列出相应回复",
        "point to point answers",
        "yellow highlight",
        "green highlight",
        "references remain black",
        "deleted text is not shown",
    )
    for wording in forbidden:
        assert wording not in combined


def test_package_template_has_only_the_response_body_placeholder() -> None:
    for language in ("zh", "en"):
        text = _template(language)
        assert "%%RESPONSE_LETTER%%" not in text
        assert text.count("%%RESPONSE_BODY%%") == 1


def test_response_signature_uses_frozen_locale_labels() -> None:
    chinese = _template("zh")
    english = _template("en")

    assert r"\CorrespondenceAuthorsZh" in chinese
    assert r"\CorrespondenceAuthorsEn" in english


@pytest.mark.parametrize(
    ("ranges", "language", "expected"),
    (
        ([(26, 31)], "zh", "第 26--31 行"),
        ([(26, 31), (79, 82)], "zh", "第 26--31 行和第 79--82 行"),
        (
            [(26, 31), (79, 82), (169, 177)],
            "zh",
            "第 26--31 行、第 79--82 行和第 169--177 行",
        ),
        ([(26, 31)], "en", "Lines 26--31"),
        (
            [(26, 31), (79, 82), (169, 177)],
            "en",
            "Lines 26--31, 79--82, and 169--177",
        ),
    ),
)
def test_location_range_wording_is_frozen(
    ranges: list[tuple[int, int]], language: str, expected: str
) -> None:
    assert _format_locations(ranges, language) == expected
