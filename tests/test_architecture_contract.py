"""Release architecture contracts for resources and user-owned workspaces."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_core import _workspace

from sci_manuscript.errors import WorkflowError
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

    artifacts = prepare_submission_artifacts(config, 0, run_dir, None, audit)
    second_run = tmp_path / "second_run"
    second_run.mkdir()
    prepare_submission_artifacts(config, 0, second_run, None, audit)

    assert not (submission / "package").exists()
    assert (submission / "manuscript.pdf").read_bytes() == b"clean"
    assert not (submission / "response_letter.pdf").exists()
    assert (submission / "checklist.md").is_file()
    assert (submission / "checklist.md").read_text(encoding="utf-8").count(
        "Review completeness"
    ) == 1
    assert all(path.suffix == ".pdf" for path in config.output_dir(0).iterdir())
    assert any(item.path == submission for item in artifacts)


def _custom_template(root: Path, *, malicious: bool = False) -> Path:
    root.mkdir()
    (root / "nested").mkdir()
    (root / "nested" / "style.tex").write_text("% nested\n", encoding="utf-8")
    (root / "workflow.tex").write_text(
        "\\documentclass{article}\n%%FRONTMATTER_INPUT%%\n"
        "\\begin{document}\n%%SECTION_INPUTS%%\n"
        "\\bibliographystyle{%%BIBLIOGRAPHY_STYLE%%}\n"
        "\\bibliography{%%BIBLIOGRAPHY_PATH%%}\n\\end{document}\n",
        encoding="utf-8",
    )
    source = "../escape.tex" if malicious else "body.tex"
    (root / "sections.yaml").write_text(
        "languages: [en]\n"
        "bibliography:\n  package: '% custom'\n  style: plain\n"
        "frontmatter:\n  file: 00_frontmatter.tex\n  source: frontmatter.tex\n"
        f"sections:\n  - file: 01_body.tex\n    source: {source}\n    title: Body\n",
        encoding="utf-8",
    )
    (root / "frontmatter.tex").write_text("\\title{%%TITLE_EN%%}\n", encoding="utf-8")
    (root / "body.tex").write_text(
        "\\section{%%SECTION_TITLE%%}\nBody.\n", encoding="utf-8"
    )
    return root


def test_custom_template_is_copied_once_and_rejects_path_traversal(
    tmp_path: Path,
) -> None:
    from sci_manuscript.workspace import initialize_project

    base = _workspace(tmp_path / "base")
    metadata = replace(base.metadata, publisher="custom", language="en")
    target = tmp_path / "custom-project" / "manuscript"
    template = _custom_template(tmp_path / "custom-template")
    config = initialize_project(
        ProjectConfig(target, metadata), custom_template=template
    )
    copied = config.references / "journal_template"
    assert (copied / "nested" / "style.tex").is_file()
    assert (config.round_dir(0) / "sections" / "01_body.tex").is_file()

    malicious_target = tmp_path / "malicious-project" / "manuscript"
    malicious = _custom_template(tmp_path / "malicious-template", malicious=True)
    with pytest.raises(WorkflowError, match=r"relative \.tex path"):
        initialize_project(
            ProjectConfig(malicious_target, metadata), custom_template=malicious
        )
