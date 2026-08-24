"""Final canonical review, response, and location workflow contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject
from sci_manuscript.api import LifecycleResult
from sci_manuscript.cli import _print_lifecycle
from sci_manuscript.errors import WorkflowError
from sci_manuscript.locations import REVIEW_REGISTRY_HEADER, calculate_locations
from sci_manuscript.metadata import ManuscriptMetadata, SubmissionSettings
from sci_manuscript.response import parse_response_entries
from sci_manuscript.review import audit_reviews, parse_reviews
from sci_manuscript.workspace import ProjectConfig, initialize_project


def _authors(tmp_path: Path) -> Path:
    path = tmp_path / "authors.yaml"
    path.write_text(
        """affiliations:
  institute:
    name_en: Anonymous Institute, Example City
    name_zh: 匿名机构
authors:
  author:
    name_en: Anonymous Author
    name_zh: 匿名作者
    email: author@example.invalid
    affiliations: [institute]
""",
        encoding="utf-8",
    )
    return path


def _project(tmp_path: Path, language: str = "en") -> ProjectConfig:
    root = tmp_path / language / "manuscript"
    root.parent.mkdir(parents=True)
    metadata = ManuscriptMetadata(
        title="Review Workflow Test",
        article_type="Research Article",
        language=language,
        journal_name="Example Journal",
        publisher="elsevier",
        round_number=0,
        parent_round=None,
        first_authors=("author",),
        corresponding_authors=("author",),
        other_authors=(),
        submission=SubmissionSettings(),
    )
    return initialize_project(ProjectConfig(root, metadata), _authors(tmp_path))


def _canonical_reviews(path: Path) -> None:
    path.write_text(
        """# Editor

## Main comment

Optional editor summary.

## Specific comments

1. First editor detail.
2. Second editor detail.

# Reviewer #1

## Main comment

## Specific comments

1. First reviewer detail.
2.
3. Second reviewer detail.
""",
        encoding="utf-8",
    )


def test_canonical_parser_uses_summary_without_id_and_ignores_blank_items(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reviews.md"
    _canonical_reviews(path)

    blocks = parse_reviews(path)

    assert blocks[0].summary == ("Optional editor summary.",)
    assert [comment.review_id for comment in blocks[0].comments] == ["E-1", "E-2"]
    assert blocks[1].summary == ()
    assert [comment.review_id for comment in blocks[1].comments] == ["1-1", "1-2"]


@pytest.mark.parametrize(
    "invalid_source",
    (
        "# Reviewer #1\n\n1. Old unlabeled list.\n",
        "# Reviewer #1\n\n## Unknown section\n\nOld detail.\n",
        "# Unknown role\n\n## Main comment\n\n## Specific comments\n\n1. Detail.\n",
    ),
)
def test_noncanonical_review_formats_are_rejected(
    tmp_path: Path,
    invalid_source: str,
) -> None:
    path = tmp_path / "reviews.md"
    path.write_text(invalid_source, encoding="utf-8")

    with pytest.raises(WorkflowError):
        parse_reviews(path)


def test_revision_initializes_only_actual_response_entries(tmp_path: Path) -> None:
    config = _project(tmp_path)
    reviews = tmp_path / "reviews.md"
    _canonical_reviews(reviews)

    result = ManuscriptProject(config.project).start_revision(
        reviews=reviews,
        confirmed=True,
    )

    response_source = config.response_dir(1) / "responses.tex"
    assert parse_response_entries(response_source) == {
        "E-1": "",
        "E-2": "",
        "1-1": "",
        "1-2": "",
    }
    text = response_source.read_text(encoding="utf-8")
    assert "Optional editor summary" not in text
    assert "line numbers are calculated automatically" in text
    assert all(token not in text for token in ("Location:", "Lines "))
    assert any(artifact.path == response_source for artifact in result.artifacts)


def test_blank_revision_defers_response_source_until_comments_exist(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)

    ManuscriptProject(config.project).start_revision(confirmed=True)

    assert not (config.response_dir(1) / "responses.tex").exists()


def test_audit_reports_missing_empty_and_orphan_without_blocking(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)
    reviews = tmp_path / "reviews.md"
    _canonical_reviews(reviews)
    ManuscriptProject(config.project).start_revision(
        reviews=reviews,
        confirmed=True,
    )
    responses = config.response_dir(1) / "responses.tex"
    responses.write_text(
        "\\Response{E-1}{Completed.}\n"
        "\\Response{E-2}{}\n"
        "\\Response{1-2}{Completed.}\n"
        "\\Response{2-1}{Orphan.}\n",
        encoding="utf-8",
    )

    audit = audit_reviews(config, 1)

    codes = {(issue.code, issue.review_id) for issue in audit.issues}
    assert ("EMPTY_RESPONSE", "E-2") in codes
    assert ("MISSING_RESPONSE", "1-1") in codes
    assert ("ORPHAN_RESPONSE", "2-1") in codes
    assert not audit.is_complete


def test_cli_completeness_output_is_concise_and_hides_source_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _project(tmp_path)
    reviews = tmp_path / "reviews.md"
    _canonical_reviews(reviews)
    ManuscriptProject(config.project).start_revision(
        reviews=reviews,
        confirmed=True,
    )
    responses = config.response_dir(1) / "responses.tex"
    responses.write_text("\\Response{E-1}{}\n", encoding="utf-8")
    audit = audit_reviews(config, 1)

    _print_lifecycle(LifecycleResult("build", "revision_01", (), audit), config.project)

    output = capsys.readouterr().out
    assert "Review responses incomplete:" in output
    assert "- E-1: empty response" in output
    assert "- E-2: missing response" in output
    assert "Path:" not in output
    assert str(config.response_dir(1)) not in output


def test_cli_malformed_response_prints_its_absolute_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _project(tmp_path)
    reviews = tmp_path / "reviews.md"
    _canonical_reviews(reviews)
    ManuscriptProject(config.project).start_revision(
        reviews=reviews,
        confirmed=True,
    )
    responses = config.response_dir(1) / "responses.tex"
    responses.write_text("\\Response{invalid}{Body.}\n", encoding="utf-8")
    audit = audit_reviews(config, 1)

    _print_lifecycle(LifecycleResult("build", "revision_01", (), audit), config.project)

    output = capsys.readouterr().out
    assert "RESPONSES_INVALID" in output
    assert f"Path: {responses.resolve()}" in output


@pytest.mark.parametrize(
    ("language", "expected"),
    (
        ("zh", "第 125--132 行和第 188--191 行"),
        ("en", "Lines 125--132 and 188--191"),
    ),
)
def test_locations_merge_duplicate_adjacent_and_overlapping_ranges(
    tmp_path: Path,
    language: str,
    expected: str,
) -> None:
    (tmp_path / "manuscript_marked.reviewloc").write_text(
        f"{REVIEW_REGISTRY_HEADER}\n1-1|1\n1-1|2\n1-1|3\n1-1|4\n1-1|5\n",
        encoding="utf-8",
    )
    (tmp_path / "manuscript_marked.aux").write_text(
        "\\newlabel{review:1:start}{{125}{1}}\n"
        "\\newlabel{review:1:end}{{128}{1}}\n"
        "\\newlabel{review:2:start}{{127}{1}}\n"
        "\\newlabel{review:2:end}{{130}{1}}\n"
        "\\newlabel{review:3:start}{{131}{1}}\n"
        "\\newlabel{review:3:end}{{132}{1}}\n"
        "\\newlabel{review:4:start}{{188}{1}}\n"
        "\\newlabel{review:4:end}{{191}{1}}\n"
        "\\newlabel{review:5:start}{{188}{1}}\n"
        "\\newlabel{review:5:end}{{191}{1}}\n",
        encoding="utf-8",
    )

    assert calculate_locations(tmp_path, language=language)["1-1"] == expected


def test_response_templates_own_localized_automatic_location_labels() -> None:
    resources = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sci_manuscript"
        / "resources"
        / "correspondence_templates"
        / "response"
    )
    zh = (resources / "response_zh.tex").read_text(encoding="utf-8")
    en = (resources / "response_en.tex").read_text(encoding="utf-8")
    assert "修改位置：#1。" in zh  # noqa: RUF001
    assert "Location of revisions: #1." in en
    assert "Location:" not in en
