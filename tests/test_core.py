"""Architecture and lifecycle regression tests."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject, initialize_manuscript
from sci_manuscript.api import LifecycleResult
from sci_manuscript.metadata import (
    ManuscriptMetadata,
    SubmissionSettings,
    load_author_library,
    load_meta,
    resolve_authors,
)
from sci_manuscript.response import parse_reviews, validate_review_id_list
from sci_manuscript.workspace import (
    ProjectConfig,
    WorkflowError,
    finalize_revision_creation,
    initialize_project,
    reindex_revisions,
    resources_root,
    source_digest,
    start_revision,
    temporary_run,
)


def _metadata(publisher: str = "elsevier", language: str = "en") -> ManuscriptMetadata:
    return ManuscriptMetadata(
        title="Anonymous Lifecycle Test",
        article_type="Research Article",
        language=language,
        journal_name="Example Journal",
        publisher=publisher,
        round_number=0,
        parent_round=None,
        first_authors=("first_author",),
        corresponding_authors=("first_author", "corresponding_author"),
        other_authors=("other_author",),
        submission=SubmissionSettings(),
    )


def _workspace(tmp_path: Path, publisher: str = "elsevier") -> ProjectConfig:
    root = tmp_path / "existing project" / "manuscript"
    root.parent.mkdir(parents=True)
    (root.parent / "unrelated.txt").write_text("preserve", encoding="utf-8")
    return initialize_project(ProjectConfig(root, _metadata(publisher)))


def _revision(config: ProjectConfig, reviews: Path | None = None) -> ProjectConfig:
    with temporary_run(config.project) as run_dir:
        child = start_revision(config, config.current_round + 1, run_dir, reviews)
        from sci_manuscript.response import init_response

        init_response(child, child.current_round)
        finalize_revision_creation(child)
    return child


def test_public_api_is_stable() -> None:
    from sci_manuscript import __all__

    assert "ManuscriptProject" in __all__
    assert "initialize_manuscript" in __all__
    assert "workspace" not in __all__


def test_workspace_contract_and_meta(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    root = config.project
    assert (root.parent / "unrelated.txt").read_text() == "preserve"
    assert not (root / "run.py").exists()
    assert not (root / "tmp").exists()
    assert {path.name for path in (root / "references").iterdir()} == {
        "authors.yaml",
        "references.bib",
        "revision_style.tex",
    }
    initial = root / "initial_submission"
    assert (initial / "meta.yaml").is_file()
    assert not (initial / "manuscript.yaml").exists()
    assert "Document class" in (initial / "manuscript.tex").read_text()
    assert load_meta(initial / "meta.yaml").first_authors == ("first_author",)
    with pytest.raises(WorkflowError, match="overwrite"):
        initialize_project(config)


def test_author_library_is_role_free_and_allows_overlap() -> None:
    path = resources_root() / "authors.yaml"
    text = path.read_text(encoding="utf-8")
    assert "role:" not in text
    library = load_author_library(path)
    selection = resolve_authors(_metadata(), library)
    assert selection.first_authors[0] in selection.corresponding_authors
    assert selection.authors[0].author_id == "first_author"


def test_revision_contract_and_parent_integrity(tmp_path: Path) -> None:
    r00 = _workspace(tmp_path)
    before = source_digest(r00.round_dir(0), scientific_only=True)
    r01 = _revision(r00)
    assert before == source_digest(r00.round_dir(0), scientific_only=True)
    assert r01.round_dir(1).name == "revision_01"
    assert load_meta(r01.round_dir(1) / "meta.yaml").parent_round == 0
    assert (r01.round_dir(1) / "revision_creation.yaml").is_file()
    assert not (r01.round_dir(1) / "references").exists()
    assert not any((r01.round_dir(1) / "output").iterdir())
    assert not any((r01.round_dir(1) / "submission").iterdir())
    r02 = _revision(r01)
    assert r02.round_dir(2).name == "revision_02"
    assert not (r02.project / "tmp").exists()


def test_rollback_success_and_refusal(tmp_path: Path) -> None:
    project = ManuscriptProject(_revision(_workspace(tmp_path)).project)
    result = project.rollback(confirmed=True)
    assert result.version == "initial_submission"
    assert result.artifacts[0].path.is_dir()
    r01 = _revision(ProjectConfig(project.root, _metadata()))
    section = r01.round_dir(1) / "sections" / "01_introduction.tex"
    section.write_text(section.read_text() + "\nUser edit.\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="source has changed"):
        ManuscriptProject(project.root).rollback(confirmed=True)


def test_reindex_success_preserves_scientific_bytes(tmp_path: Path) -> None:
    r01 = _revision(_workspace(tmp_path))
    r02 = _revision(r01)
    old = r02.round_dir(2)
    digest = source_digest(old, scientific_only=True)
    shutil.rmtree(r02.round_dir(1))
    with temporary_run(r02.project) as run_dir:
        mapping = reindex_revisions(r02.project, run_dir)
    assert mapping == (("revision_02", "revision_01"),)
    assert source_digest(r02.round_dir(1), scientific_only=True) == digest
    assert load_meta(r02.round_dir(1) / "meta.yaml").round_number == 1
    assert any((r02.project / "00_archive").iterdir())


def test_reindex_injected_failure_restores_original(tmp_path: Path) -> None:
    r02 = _revision(_revision(_workspace(tmp_path)))
    shutil.rmtree(r02.round_dir(1))
    before = hashlib.sha256((r02.round_dir(2) / "meta.yaml").read_bytes()).hexdigest()
    with pytest.raises(WorkflowError, match="Injected"):
        with temporary_run(r02.project) as run_dir:
            reindex_revisions(r02.project, run_dir, fail_after_swap=True)
    assert r02.round_dir(2).is_dir()
    assert not r02.round_dir(1).exists()
    assert (
        hashlib.sha256((r02.round_dir(2) / "meta.yaml").read_bytes()).hexdigest()
        == before
    )


def test_review_parser_ids_status_and_paragraphs(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews.md"
    reviews.write_text(
        "# Editor\n\n## E-1 | response_only\n\nFirst paragraph.\n\n"
        "Second paragraph with 10% and A_B.\n\n# Reviewer #1\n\n"
        "## 1-1 | manuscript_revised\n\nRevise this.\n",
        encoding="utf-8",
    )
    blocks = parse_reviews(reviews)
    assert [comment.review_id for block in blocks for comment in block.comments] == [
        "E-1",
        "1-1",
    ]
    assert blocks[0].comments[0].paragraphs == (
        "First paragraph.",
        "Second paragraph with 10% and A_B.",
    )
    assert blocks[0].comments[0].status == "response_only"
    assert validate_review_id_list("1-1,2-3") == ("1-1", "2-3")
    with pytest.raises(WorkflowError):
        validate_review_id_list("E-0")


def test_multi_id_review_location_registry(tmp_path: Path) -> None:
    from sci_manuscript.diff import _calculate_locations

    (tmp_path / "manuscript_marked.reviewloc").write_text(
        "1-1,2-3|1\nE-1|2\n", encoding="utf-8"
    )
    (tmp_path / "manuscript_marked.aux").write_text(
        "\\newlabel{review:1:start}{{7}{1}}\n"
        "\\newlabel{review:1:end}{{8}{1}}\n"
        "\\newlabel{review:2:start}{{12}{1}}\n"
        "\\newlabel{review:2:end}{{12}{1}}\n",
        encoding="utf-8",
    )
    assert _calculate_locations(tmp_path) == {
        "1-1": "Lines 7--8",
        "2-3": "Lines 7--8",
        "E-1": "Line 12",
    }


def test_init_api_returns_structured_result(tmp_path: Path) -> None:
    result = initialize_manuscript(
        tmp_path / "API Project 中文",
        title="API Test",
        journal="Example Journal",
        publisher="elsevier",
        language="en",
        article_type="Research Article",
        first_authors=("first_author",),
        corresponding_authors=("corresponding_author",),
        engine="tectonic",
    )
    assert isinstance(result, LifecycleResult)
    assert result.artifacts[0].path.is_file()
    manuscript = tmp_path / "API Project 中文" / "manuscript"
    before = source_digest(manuscript / "initial_submission", scientific_only=True)
    ManuscriptProject(manuscript).build(engine="tectonic")
    assert before == source_digest(
        manuscript / "initial_submission", scientific_only=True
    )
    assert not (manuscript / "tmp").exists()
