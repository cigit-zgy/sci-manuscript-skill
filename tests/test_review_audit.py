"""Reviewer-comment input and cross-source audit regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject
from sci_manuscript.api import LifecycleResult
from sci_manuscript.cli import _print_lifecycle
from sci_manuscript.metadata import ManuscriptMetadata, SubmissionSettings
from sci_manuscript.response import audit_reviews, parse_reviews
from sci_manuscript.workspace import ProjectConfig, initialize_project


def _authors(tmp_path: Path) -> Path:
    path = tmp_path / "authors.yaml"
    path.write_text(
        """affiliations:
  institute:
    name_en: Anonymous Institute
    address: Example City
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
        title="Review Audit Test",
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


def test_revision_creates_user_facing_chinese_review_template(tmp_path: Path) -> None:
    config = _project(tmp_path, "zh")
    result = ManuscriptProject(config.project).start_revision(confirmed=True)
    comments = config.project / "revision_01" / "response" / "reviewer_comments.md"
    text = comments.read_text(encoding="utf-8")
    assert "# 编辑" in text
    assert "# 审稿人 #1" in text
    assert "# 审稿人 #2" in text
    assert "1." in text
    assert "manuscript_revised" not in text
    assert "无需填写" not in text
    assert result.artifacts[0].label == "Reviewer comments"
    assert result.artifacts[0].path == comments
    response_help = (comments.parent / "responses.tex").read_text(encoding="utf-8")
    assert "% 使用说明：" in response_help
    assert "reviewer_comments.md" in response_help
    assert "\\Response{" not in response_help


def test_revision_creates_matching_english_review_template(tmp_path: Path) -> None:
    config = _project(tmp_path, "en")
    ManuscriptProject(config.project).start_revision(confirmed=True)
    comments = config.project / "revision_01" / "response" / "reviewer_comments.md"
    text = comments.read_text(encoding="utf-8")
    assert "# Editor" in text
    assert "# Reviewer #1" in text
    assert "# Reviewer #2" in text
    assert "Use one numbered list item for each comment" in text
    assert "manuscript_revised" not in text
    response_help = (comments.parent / "responses.tex").read_text(encoding="utf-8")
    assert "% Instructions:" in response_help
    assert "not rendered in the final PDF" in response_help


def test_numbered_list_parser_assigns_internal_ids_and_preserves_general_text(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reviews.md"
    path.write_text(
        """<!-- instructions are ignored -->
# 编辑

1. 请说明研究范围。

# 审稿人 #1

该研究具有一定价值，但需要进一步修改。

1. 第一条意见第一行。
   第一条意见第二行。

2. 第二条意见。

# 审稿人 #2

1.
2.
""",
        encoding="utf-8",
    )
    blocks = parse_reviews(path)
    assert [comment.review_id for block in blocks for comment in block.comments] == [
        "E-1",
        "1-1",
        "1-2",
    ]
    assert blocks[1].general_paragraphs == ("该研究具有一定价值，但需要进一步修改。",)
    assert blocks[1].comments[0].paragraphs == (
        "第一条意见第一行。 第一条意见第二行。",
    )
    assert blocks[2].comments == ()


def test_legacy_explicit_review_format_remains_readable(tmp_path: Path) -> None:
    path = tmp_path / "legacy.md"
    path.write_text(
        "# Reviewer #1\n\n## 1-1 | manuscript_revised\n\nLegacy comment.\n",
        encoding="utf-8",
    )
    blocks = parse_reviews(path)
    assert blocks[0].comments[0].review_id == "1-1"
    assert blocks[0].comments[0].status == "manuscript_revised"


def test_review_audit_computes_statuses_and_reports_all_paths(tmp_path: Path) -> None:
    config = _project(tmp_path)
    project = ManuscriptProject(config.project)
    project.start_revision(confirmed=True)
    version = config.project / "revision_01"
    comments = version / "response" / "reviewer_comments.md"
    comments.write_text(
        """# Reviewer #1

1. First comment.
2. Second comment.
3. Third comment.
""",
        encoding="utf-8",
    )
    responses = version / "response" / "responses.tex"
    responses.write_text(
        """\\Response{1-1}{Completed response.}

\\Response{1-2}{\\ResponsePending{1-2}}

\\Response{2-1}{Orphan response.}
""",
        encoding="utf-8",
    )
    section = version / "sections" / "01_introduction.tex"
    section.write_text(
        section.read_text(encoding="utf-8")
        + "\n\\review{1-1}{Changed once.}"
        + "\n\\review{1-2}{Changed twice.}"
        + "\n\\review{9-1}{Orphan provenance.}\n",
        encoding="utf-8",
    )

    audit = audit_reviews(ProjectConfig(config.project, config.metadata), 1)
    states = {entry.review_id: entry.state for entry in audit.entries}
    assert states == {
        "1-1": "manuscript_revised",
        "1-2": "manuscript_changed_but_unanswered",
        "1-3": "unanswered",
    }
    codes = {(issue.code, issue.review_id) for issue in audit.issues}
    assert ("MISSING_RESPONSE", "1-2") in codes
    assert ("MISSING_RESPONSE", "1-3") in codes
    assert ("ORPHAN_RESPONSE", "2-1") in codes
    assert ("ORPHAN_REVIEW_REFERENCE", "9-1") in codes
    assert audit.complete == 1
    assert not audit.is_complete
    for issue in audit.issues:
        assert issue.paths
        assert all(path.is_absolute() for path in issue.paths)


def test_empty_comments_with_review_macro_produces_nonblocking_audit(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    version = config.project / "revision_01"
    section = version / "sections" / "01_introduction.tex"
    section.write_text(
        section.read_text(encoding="utf-8") + "\n\\review{1-1}{Changed text.}\n",
        encoding="utf-8",
    )
    audit = audit_reviews(ProjectConfig(config.project, config.metadata), 1)
    codes = {(issue.code, issue.review_id) for issue in audit.issues}
    assert ("COMMENTS_EMPTY", None) in codes
    assert ("ORPHAN_REVIEW_REFERENCE", "1-1") in codes
    assert audit.comment_path.name == "reviewer_comments.md"


def test_review_id_drift_is_detected_after_first_recorded_mapping(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    version = config.project / "revision_01"
    comments = version / "response" / "reviewer_comments.md"
    comments.write_text(
        "# Reviewer #1\n\n1. Alpha comment.\n2. Beta comment.\n",
        encoding="utf-8",
    )
    audit_reviews(ProjectConfig(config.project, config.metadata), 1, record_index=True)
    comments.write_text(
        "# Reviewer #1\n\n1. Beta comment.\n2. Alpha comment.\n",
        encoding="utf-8",
    )
    audit = audit_reviews(ProjectConfig(config.project, config.metadata), 1)
    assert any(issue.code == "REVIEW_ID_DRIFT" for issue in audit.issues)
    assert (config.project / "state" / "revision_01" / "review_index.yaml").is_file()
    assert not (version / "output" / "review_index.yaml").exists()


def test_legacy_review_index_migrates_out_of_user_output(tmp_path: Path) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    version = config.project / "revision_01"
    comments = version / "response" / "reviewer_comments.md"
    comments.write_text("# Reviewer #1\n\n1. Stable comment.\n", encoding="utf-8")
    state_index = config.project / "state" / "revision_01" / "review_index.yaml"
    audit_reviews(ProjectConfig(config.project, config.metadata), 1, record_index=True)
    legacy_index = version / "output" / "review_index.yaml"
    legacy_index.write_text(state_index.read_text(encoding="utf-8"), encoding="utf-8")
    state_index.unlink()

    audit_reviews(ProjectConfig(config.project, config.metadata), 1, record_index=True)

    assert state_index.is_file()
    assert not legacy_index.exists()


def test_cli_review_warning_prints_concrete_file_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    version = config.project / "revision_01"
    audit = audit_reviews(ProjectConfig(config.project, config.metadata), 1)
    result = LifecycleResult("build", "revision_01", (), audit)
    _print_lifecycle(result, config.project)
    output = capsys.readouterr().out
    assert "Review audit result: INCOMPLETE" in output
    assert "Path:" in output
    assert str(version / "response" / "reviewer_comments.md") in output


def test_cli_init_output_is_minimal_and_action_oriented(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manuscript = tmp_path / "project" / "manuscript"
    artifact = manuscript / "initial_submission" / "output" / "manuscript.pdf"
    from sci_manuscript.api import Artifact

    _print_lifecycle(
        LifecycleResult(
            "init", "initial_submission", (Artifact("Manuscript", artifact),)
        ),
        tmp_path / "project",
        language="zh",
    )
    output = capsys.readouterr().out
    assert "Initialized: initial_submission" in output
    assert "meta.yaml" in output
    assert "manuscript/initial_submission/output/manuscript.pdf" in output
    assert all(
        token not in output
        for token in ("tmp/", "reviewloc", "latexdiff", "Tectonic", "sidecar")
    )
