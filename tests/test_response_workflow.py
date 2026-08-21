"""Editor, associate-editor, and reviewer response-workflow regressions."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sci_manuscript._runtime import diff, metadata, response, workspace


def _config(project: Path) -> workspace.ProjectConfig:
    manuscript = metadata.ManuscriptMetadata(
        title="Anonymous Response Test",
        article_type="Research Paper",
        language="en",
        journal_name="Example Journal",
        publisher="elsevier",
        journal_template=metadata.PUBLISHER_TEMPLATES["elsevier"],
        round_number=0,
        parent_round=None,
        submission=metadata.SubmissionSettings(True, True, True),
        first_authors=("Guangyao Zhao",),
        corresponding_authors=("Hong Liu",),
        authors=(),
    )
    return workspace.initialize_project(workspace.ProjectConfig(project, manuscript))


def _parse(text: str) -> tuple[response.ReviewBlock, ...]:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "reviews.md"
        path.write_text(text, encoding="utf-8")
        return response.parse_reviews(path)


def test_all_supported_roles_keep_stable_ids_and_input_order() -> None:
    blocks = _parse(
        """# Editor

1. Editor comment.

# Associate Editor

1. Associate-editor comment.

# Reviewer #2

1. Reviewer two comment.

# Reviewer #1

1. Reviewer one comment.
"""
    )
    assert [block.owner for block in blocks] == ["E", "AE", "2", "1"]
    assert [block.comments[0].review_id for block in blocks] == [
        "E-1",
        "AE-1",
        "2-1",
        "1-1",
    ]


def test_numeric_reviewer_ids_remain_backward_compatible() -> None:
    blocks = _parse("# Reviewer #1\n\n1. First.\n\n2. Second.\n")
    assert [comment.review_id for comment in blocks[0].comments] == ["1-1", "1-2"]


def test_multi_paragraph_comment_is_preserved_in_source() -> None:
    blocks = _parse(
        """# Reviewer #1

1. First paragraph.

   Second paragraph on another issue.

   Third paragraph.
"""
    )
    comment = blocks[0].comments[0]
    assert comment.text == (
        "First paragraph.\n\nSecond paragraph on another issue.\n\nThird paragraph."
    )
    rendered = response._body_tex(blocks, "en")
    assert rendered.count(r"\ReviewerComment{") == 3


def test_indented_multi_paragraph_comment_preserves_each_input_paragraph() -> None:
    blocks = _parse(
        """# Reviewer #1

1. First paragraph.
   Second paragraph explaining another issue.
   Third paragraph.
"""
    )
    assert blocks[0].comments[0].text == (
        "First paragraph.\n\nSecond paragraph explaining another issue.\n\n"
        "Third paragraph."
    )
    assert response._body_tex(blocks, "en").count(r"\ReviewerComment{") == 3


def test_external_comment_latex_characters_are_safely_escaped() -> None:
    blocks = _parse(
        """# Editor

1. 10% A_B x & y $z$ #tag {value} C:\\path ~10 ^ symbol 中文.
"""
    )
    rendered = response._body_tex(blocks, "en")
    for expected in (
        r"10\%",
        r"A\_B",
        r"x \& y",
        r"\$z\$",
        r"\#tag",
        r"\{value\}",
        r"C:\textbackslash{}path",
        r"\textasciitilde{}10",
        r"\textasciicircum{} symbol",
        "中文",
    ):
        assert expected in rendered


@pytest.mark.parametrize(
    "text, message",
    [
        ("# Editor\n\n1. A.\n\n# Editor\n\n1. B.\n", "Duplicate"),
        ("# Reviewer #01\n\n1. A.\n", "leading zeros"),
        ("# Reviewer #1\n\n1. A.\n\n3. C.\n", "consecutive"),
        ("# Reviewer #1\n\n01. A.\n", "leading zeros"),
    ],
)
def test_invalid_blocks_are_rejected_without_silent_renumbering(
    text: str,
    message: str,
) -> None:
    with pytest.raises(workspace.WorkflowError, match=message):
        _parse(text)


def test_pending_and_location_ids_are_strict_for_every_role() -> None:
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp) / "response.tex"
        source.write_text(
            r"\ResponsePending{E-1}\ResponsePending{AE-2}\ResponsePending{1-3}",
            encoding="utf-8",
        )
        assert response.pending_response_ids(source) == ("E-1", "AE-2", "1-3")
        source.write_text(r"\ResponsePending{editor-1}", encoding="utf-8")
        with pytest.raises(workspace.WorkflowError, match="Invalid pending"):
            response.pending_response_ids(source)


def test_allow_placeholders_never_bypasses_invalid_infrastructure_ids() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = Path(temp) / "project"
        r0 = _config(project)
        with workspace.temporary_run(project, keep=False) as run_dir:
            r1 = workspace.start_revision(r0, 1, run_dir)
        source = r1.round_dir(1) / "response" / "response_letter.tex"
        source.write_text(r"\ReviewLocation{invalid-id}", encoding="utf-8")
        with pytest.raises(workspace.WorkflowError, match="Invalid review location"):
            response.build_response(
                r1,
                1,
                {},
                project / "tmp" / "response-test",
                allow_placeholders=True,
            )


def test_editor_and_reviewer_locations_share_existing_numeric_line_registry() -> None:
    with tempfile.TemporaryDirectory() as temp:
        build = Path(temp)
        (build / "manuscript_marked.reviewloc").write_text(
            "E-1|1\nAE-1|2\n1-1|3\n",
            encoding="utf-8",
        )
        (build / "manuscript_marked.aux").write_text(
            "\\newlabel{review:1:start}{{4}{1}}\n"
            "\\newlabel{review:1:end}{{5}{1}}\n"
            "\\newlabel{review:2:start}{{8}{1}}\n"
            "\\newlabel{review:2:end}{{8}{1}}\n"
            "\\newlabel{review:3:start}{{11}{1}}\n"
            "\\newlabel{review:3:end}{{13}{1}}\n",
            encoding="utf-8",
        )
        locations = diff._calculate_locations(build)
    assert locations == {
        "E-1": "Lines 4--5",
        "AE-1": "Line 8",
        "1-1": "Lines 11--13",
    }


def test_editor_provenance_denesting_does_not_change_marked_renderer() -> None:
    assert diff._denest_provenance(r"\DIFadd{\review{E-1}{Editor revision.}}") == (
        r"\review{E-1}{Editor revision.}"
    )
    assert (
        diff._denest_provenance(r"\DIFadd{\review{AE-1}{Associate revision.}}")
        == r"\review{AE-1}{Associate revision.}"
    )
