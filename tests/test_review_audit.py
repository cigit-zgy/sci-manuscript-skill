"""Reviewer-comment input and cross-source audit regression tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject
from sci_manuscript.api import LifecycleResult
from sci_manuscript.cli import _print_lifecycle
from sci_manuscript.diff import MarkedResult
from sci_manuscript.metadata import (
    ManuscriptMetadata,
    SubmissionSettings,
    load_meta,
    save_meta,
)
from sci_manuscript.response import audit_reviews, parse_response_entries, parse_reviews
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
    assert text.count("## 主意见") == 3
    assert text.count("## 具体意见") == 3
    assert "1." in text
    instructions = text.split("<!--", 1)[1].split("-->", 1)[0]
    assert "\n\n" not in instructions
    for hidden_term in ("E-1", "1-1", "audit", "response linkage"):
        assert hidden_term not in text
    blocks = parse_reviews(comments)
    assert all(not block.general_paragraphs for block in blocks)
    assert all(not block.comments for block in blocks)
    assert result.artifacts[0].label == "Reviewer comments"
    assert result.artifacts[0].path == comments
    response_help = (comments.parent / "responses.tex").read_text(encoding="utf-8")
    assert "% 使用说明：" in response_help
    assert "reviewer_comments.md" in response_help
    assert parse_response_entries(comments.parent / "responses.tex") == {
        "1-1": "",
        "2-1": "",
    }
    assert "\\ResponsePending" not in response_help


def test_revision_creates_matching_english_review_template(tmp_path: Path) -> None:
    config = _project(tmp_path, "en")
    ManuscriptProject(config.project).start_revision(confirmed=True)
    comments = config.project / "revision_01" / "response" / "reviewer_comments.md"
    text = comments.read_text(encoding="utf-8")
    assert "# Editor" in text
    assert "# Reviewer #1" in text
    assert "# Reviewer #2" in text
    assert text.count("## Main comment") == 3
    assert text.count("## Specific comments") == 3
    instructions = text.split("<!--", 1)[1].split("-->", 1)[0]
    assert "\n\n" not in instructions
    for hidden_term in ("comment ID", "E-1", "1-1", "audit", "response linkage"):
        assert hidden_term not in text
    blocks = parse_reviews(comments)
    assert all(not block.general_paragraphs for block in blocks)
    assert all(not block.comments for block in blocks)
    response_help = (comments.parent / "responses.tex").read_text(encoding="utf-8")
    assert "% Instructions:" in response_help
    assert "not rendered in the final PDF" in response_help
    assert parse_response_entries(comments.parent / "responses.tex") == {
        "1-1": "",
        "2-1": "",
    }
    assert "\\ResponsePending" not in response_help


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


def test_labeled_summary_and_comment_sections_remain_internal_structure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reviews.md"
    path.write_text(
        """# 编辑

## 主意见

编辑整体意见。

## 具体意见

1. 编辑意见一。
2. 编辑意见二。

# 审稿人 #1

## 主意见

Reviewer summary.

## 具体意见

1. Reviewer comment one.
2. Reviewer comment two.
""",
        encoding="utf-8",
    )

    blocks = parse_reviews(path)

    assert blocks[0].general_paragraphs == ("编辑整体意见。",)
    assert [comment.review_id for comment in blocks[0].comments] == ["E-1", "E-2"]
    assert blocks[1].general_paragraphs == ("Reviewer summary.",)
    assert [comment.review_id for comment in blocks[1].comments] == ["1-1", "1-2"]


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

\\Response{1-2}{}

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
    assert ("EMPTY_RESPONSE", "1-2") in codes
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


@pytest.mark.parametrize("pending_id", ("2-1", "invalid"))
def test_malformed_pending_marker_produces_nonblocking_response_issue(
    tmp_path: Path,
    pending_id: str,
) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    version = config.project / "revision_01"
    comments = version / "response" / "reviewer_comments.md"
    comments.write_text(
        "# Reviewer #1\n\n1. First comment.\n",
        encoding="utf-8",
    )
    responses = version / "response" / "responses.tex"
    responses.write_text(
        f"\\Response{{1-1}}{{\\ResponsePending{{{pending_id}}}}}\n",
        encoding="utf-8",
    )

    audit = audit_reviews(ProjectConfig(config.project, config.metadata), 1)

    issue = next(item for item in audit.issues if item.code == "RESPONSES_INVALID")
    assert issue.paths == (responses.resolve(),)
    assert not audit.is_complete


def test_submission_skips_untrusted_response_pdf_but_publishes_manuscripts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    version = config.project / "revision_01"
    metadata = replace(
        load_meta(version / "meta.yaml"),
        submission=SubmissionSettings(False, False, False),
    )
    save_meta(version / "meta.yaml", metadata)
    comments = version / "response" / "reviewer_comments.md"
    comments.write_text("# Reviewer #1\n\n1. First comment.\n", encoding="utf-8")
    responses = version / "response" / "responses.tex"
    responses.write_text(
        "\\Response{1-1}{\\ResponsePending{2-1}}\n",
        encoding="utf-8",
    )

    import sci_manuscript.submission as submission_module

    def fake_clean(
        config: ProjectConfig,
        round_number: int,
        run_dir: Path,
        engine: str | None,
    ) -> Path:
        del engine
        output = config.output_dir(round_number) / "manuscript_clean.pdf"
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(b"clean")
        build = run_dir / "clean_build"
        build.mkdir()
        (build / "manuscript.compiler.log").write_text("", encoding="utf-8")
        return output

    def fake_marked(
        config: ProjectConfig,
        round_number: int,
        run_dir: Path,
        engine: str | None,
    ) -> MarkedResult:
        del engine
        output = config.output_dir(round_number) / "manuscript_marked.pdf"
        output.write_bytes(b"marked")
        build = run_dir / "marked_build"
        build.mkdir()
        (build / "manuscript_marked.compiler.log").write_text("", encoding="utf-8")
        return MarkedResult(output, {})

    def fake_layout(clean: str, marked: str, report: Path) -> Path:
        del clean, marked
        report.write_text("Result: PASS\n", encoding="utf-8")
        return report

    monkeypatch.setattr(submission_module, "build_clean_manuscript", fake_clean)
    monkeypatch.setattr(submission_module, "build_marked_manuscript", fake_marked)
    monkeypatch.setattr(submission_module, "validate_revision_layout", fake_layout)
    monkeypatch.setattr(
        submission_module,
        "build_response",
        lambda *args, **kwargs: pytest.fail("malformed responses must not compile"),
    )

    result = ManuscriptProject(config.project).prepare_submission()

    assert result.review_audit is not None
    assert any(
        issue.code == "RESPONSES_INVALID" for issue in result.review_audit.issues
    )
    submission = version / "submission"
    assert not (submission / "package").exists()
    assert (submission / "manuscript.pdf").is_file()
    assert (submission / "marked_manuscript.pdf").is_file()
    assert not (submission / "response_letter.pdf").exists()
    assert "INCOMPLETE" in (submission / "checklist.md").read_text(encoding="utf-8")
    assert {path.name for path in config.output_dir(1).iterdir()} == {
        "manuscript_clean.pdf",
        "manuscript_marked.pdf",
    }
    assert all(path.suffix == ".pdf" for path in config.output_dir(1).iterdir())


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
    comments = version / "response" / "reviewer_comments.md"
    comments.write_text("# Reviewer #1\n\n1. First comment.\n", encoding="utf-8")
    responses = version / "response" / "responses.tex"
    responses.write_text("\\Response{1-1}{}\n", encoding="utf-8")
    audit = audit_reviews(ProjectConfig(config.project, config.metadata), 1)
    result = LifecycleResult("build", "revision_01", (), audit)
    _print_lifecycle(result, config.project)
    output = capsys.readouterr().out
    assert "Review response audit:" in output
    assert "Unreplied comments:" in output
    assert "1-1 (EMPTY_RESPONSE)" in output
    assert "Please complete these responses before submission." in output
    assert "Review audit result: INCOMPLETE" in output
    assert "Path:" in output
    assert str(comments) in output


def test_missing_empty_and_orphan_responses_have_distinct_issue_codes(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    version = config.project / "revision_01"
    comments = version / "response" / "reviewer_comments.md"
    comments.write_text(
        "# Reviewer #1\n\n1. Missing.\n2. Empty.\n",
        encoding="utf-8",
    )
    responses = version / "response" / "responses.tex"
    responses.write_text(
        "\\Response{1-2}{}\n\\Response{2-1}{Orphan.}\n",
        encoding="utf-8",
    )

    audit = audit_reviews(ProjectConfig(config.project, config.metadata), 1)

    codes = {(issue.code, issue.review_id) for issue in audit.issues}
    assert ("MISSING_RESPONSE", "1-1") in codes
    assert ("EMPTY_RESPONSE", "1-2") in codes
    assert ("ORPHAN_RESPONSE", "2-1") in codes
    for issue in audit.issues:
        assert issue.paths
        assert all(path.is_absolute() for path in issue.paths)


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
