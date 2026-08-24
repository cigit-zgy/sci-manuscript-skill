"""Release architecture contracts for resources and user-owned workspaces."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sci_manuscript.metadata import (
    ManuscriptMetadata,
    SubmissionSettings,
    load_meta,
    save_meta,
)
from sci_manuscript.review import ReviewAuditResult
from sci_manuscript.submission import prepare_submission_artifacts
from sci_manuscript.templates import resources_root
from sci_manuscript.workspace import ProjectConfig, initialize_project


def _authors(path: Path) -> Path:
    path.write_text(
        """affiliations:
  institute:
    name_en: Anonymous Institute, Example City, Country
    name_zh: 示例研究机构
authors:
  author_one:
    name_en: Anonymous One
    name_zh: 匿名甲
    email: one@example.invalid
    affiliations: [institute]
""",
        encoding="utf-8",
    )
    return path


def _metadata() -> ManuscriptMetadata:
    return ManuscriptMetadata(
        title="Architecture Contract",
        article_type="Research Article",
        language="en",
        journal_name="Example Journal",
        publisher="elsevier",
        round_number=0,
        parent_round=None,
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        other_authors=(),
        submission=SubmissionSettings(False, False, False),
    )


def _project(tmp_path: Path) -> ProjectConfig:
    root = tmp_path / "project" / "manuscript"
    return initialize_project(
        ProjectConfig(root, _metadata()),
        _authors(tmp_path / "authors.yaml"),
    )


def test_canonical_packaged_architecture_resources_exist() -> None:
    resources = resources_root()
    for publisher in ("chinese", "elsevier", "nature", "acs"):
        assert (resources / "journal_templates" / publisher).is_dir()
    for name in ("common.tex", "zh.tex", "en.tex"):
        assert (resources / "manuscript_preamble" / name).is_file()
    assert (resources / "revision_style.template.tex").is_file()


def test_initialized_user_project_contains_no_latex_infrastructure(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)
    version = config.round_dir(0)
    assert not (version / "preamble").exists()
    assert not (version / "manuscript_preamble").exists()
    assert not (config.project / "journal_templates").exists()
    forbidden_names = {"workflow.tex", "sections.yaml"}
    assert not any(
        path.suffix in {".cls", ".bst"} or path.name in forbidden_names
        for path in config.project.rglob("*")
    )
    assert {path.name for path in config.references.iterdir()} == {
        "authors.yaml",
        "references.bib",
        "revision_style.tex",
    }


def test_meta_round_trip_preserves_user_comments(tmp_path: Path) -> None:
    config = _project(tmp_path)
    path = config.round_dir(0) / "meta.yaml"
    generated = path.read_text(encoding="utf-8")
    assert "# Funding acknowledgements" in generated
    customized = generated.replace(
        "  funding:", "  # Keep this user planning note.\n  funding:", 1
    )
    path.write_text(customized, encoding="utf-8")

    metadata = replace(load_meta(path), article_type="Perspective")
    save_meta(path, metadata)

    updated = path.read_text(encoding="utf-8")
    assert "# Keep this user planning note." in updated
    assert "article_type: Perspective" in updated


def test_submission_is_flat_and_output_contains_only_pdfs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _project(tmp_path)

    import sci_manuscript.submission as submission_module

    def fake_clean(
        config: ProjectConfig,
        round_number: int,
        run_dir: Path,
        engine: str | None,
    ) -> Path:
        del run_dir, engine
        output = config.output_dir(round_number) / "manuscript_clean.pdf"
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(b"clean")
        return output

    monkeypatch.setattr(submission_module, "build_clean_manuscript", fake_clean)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    submission = config.submission_dir(0)
    submission.mkdir(exist_ok=True)
    (submission / "response_letter.pdf").write_bytes(b"stale")
    audit = ReviewAuditResult(tmp_path / "comments", tmp_path / "responses", (), ())

    artifacts = prepare_submission_artifacts(config, 0, run_dir, None, False, audit)
    second_run = tmp_path / "second_run"
    second_run.mkdir()
    prepare_submission_artifacts(config, 0, second_run, None, False, audit)

    assert not (submission / "package").exists()
    assert (submission / "manuscript.pdf").read_bytes() == b"clean"
    assert not (submission / "response_letter.pdf").exists()
    assert (submission / "checklist.md").is_file()
    assert (submission / "checklist.md").read_text(encoding="utf-8").count(
        "Review completeness"
    ) == 1
    assert all(path.suffix == ".pdf" for path in config.output_dir(0).iterdir())
    assert any(item.path == submission for item in artifacts)
