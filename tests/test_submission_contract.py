"""Submission-source, ownership, and atomic-publication contracts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
import sci_manuscript.submission as submission_module
import sci_manuscript.workspace as workspace_module
import yaml
from sci_manuscript.api import ManuscriptProject
from sci_manuscript.compile import CompileResult, TeXStateFiles
from sci_manuscript.diff import MarkedResult
from sci_manuscript.errors import WorkflowError
from sci_manuscript.metadata import (
    CorrespondenceSettings,
    SubmissionSettings,
    save_meta,
)
from sci_manuscript.submission import (
    SubmissionArtifact,
    _publish_submission_stage,
    ensure_submission_workspace,
    prepare_submission_artifacts,
)
from sci_manuscript.workspace import (
    ProjectConfig,
    _generated_submission_paths,
    _submission_source_entries,
    load_project,
)
from test_core import _revision, _workspace


def _submission_config(tmp_path: Path, settings: SubmissionSettings) -> ProjectConfig:
    original = _workspace(tmp_path)
    metadata = replace(
        original.metadata,
        corresponding_authors=("author_one",),
        submission=settings,
    )
    return ProjectConfig(original.project, metadata)


def _stub_submission_compilers(
    monkeypatch: pytest.MonkeyPatch, config: ProjectConfig
) -> None:
    clean = config.output_dir(0) / "manuscript.pdf"
    clean.write_bytes(b"clean pdf")

    def fake_submission_source(
        _source: Path,
        name: str,
        _config: ProjectConfig,
        run_dir: Path,
        _engine: str | None,
        _author_library_path: Path,
    ) -> Path:
        target = run_dir / "package_stage" / f"{name}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
        return target

    def fake_cover(
        _source: Path,
        _config: ProjectConfig,
        run_dir: Path,
        _engine: str | None,
        _author_library_path: Path,
    ) -> Path:
        return fake_submission_source(
            _source,
            "cover_letter",
            _config,
            run_dir,
            _engine,
            _author_library_path,
        )

    monkeypatch.setattr(
        "sci_manuscript.submission.build_clean_manuscript",
        lambda *_args, **_kwargs: clean,
    )
    monkeypatch.setattr(
        "sci_manuscript.submission._compile_submission_source",
        fake_submission_source,
    )
    monkeypatch.setattr("sci_manuscript.submission._compile_cover_letter", fake_cover)


def test_submission_workspace_uses_body_name_and_pending_markers(
    tmp_path: Path,
) -> None:
    config = _workspace(tmp_path)
    submission = ensure_submission_workspace(config, 0)
    assert (submission / "cover_letter_body.tex").is_file()
    assert not (submission / "cover_letter.tex").exists()
    assert "\\guidance{" in (submission / "cover_letter_body.tex").read_text()
    assert (
        "SCI_MANUSCRIPT_PENDING: highlights"
        in (submission / "highlights.tex").read_text()
    )
    assert (
        "SCI_MANUSCRIPT_PENDING: graphical_abstract"
        in (submission / "graphical_abstract" / "graphical_abstract.tex").read_text()
    )


@pytest.mark.parametrize(
    "relative",
    (
        Path("response/response_letter.tex"),
        Path("submission/package"),
        Path("revision_creation.yaml"),
    ),
)
def test_v1_workspace_paths_are_rejected_with_archive_first_message(
    tmp_path: Path, relative: Path
) -> None:
    config = _workspace(tmp_path)
    legacy = config.round_dir(0) / relative
    if relative.suffix:
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("legacy", encoding="utf-8")
    else:
        legacy.mkdir(parents=True)

    with pytest.raises(WorkflowError, match="Detected a v1 workspace") as error:
        load_project(config.project)

    assert "Archive the workspace" in str(error.value)
    assert "CHANGELOG" in str(error.value)


def test_default_highlights_pending_blocks_but_disabled_highlights_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enabled = _submission_config(
        tmp_path / "enabled", SubmissionSettings(False, True, False)
    )
    ensure_submission_workspace(enabled, 0)
    with pytest.raises(WorkflowError, match="Highlights are still pending"):
        prepare_submission_artifacts(enabled, 0, tmp_path / "blocked-run", None, None)

    disabled = _submission_config(
        tmp_path / "disabled", SubmissionSettings(False, False, False)
    )
    ensure_submission_workspace(disabled, 0)
    _stub_submission_compilers(monkeypatch, disabled)
    artifacts = prepare_submission_artifacts(
        disabled, 0, tmp_path / "disabled-run", None, None
    )
    assert not (disabled.submission_dir(0) / "highlights.pdf").exists()
    assert any(item.label == "Submission checklist" for item in artifacts)


def test_completed_highlights_pass_and_unresolved_token_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _submission_config(tmp_path, SubmissionSettings(False, True, False))
    submission = ensure_submission_workspace(config, 0)
    highlights = submission / "highlights.tex"
    highlights.write_text("Completed highlight: %%UNRESOLVED%%\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="unresolved placeholders"):
        prepare_submission_artifacts(config, 0, tmp_path / "token-run", None, None)

    highlights.write_text("Completed highlight.\n", encoding="utf-8")
    _stub_submission_compilers(monkeypatch, config)
    prepare_submission_artifacts(config, 0, tmp_path / "complete-run", None, None)
    assert (submission / "highlights.pdf").read_bytes() == b"highlights"


def test_graphical_abstract_pending_disabled_final_pdf_and_edited_tex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pending = _submission_config(
        tmp_path / "pending", SubmissionSettings(False, False, True)
    )
    ensure_submission_workspace(pending, 0)
    with pytest.raises(WorkflowError, match="Graphical abstract is still pending"):
        prepare_submission_artifacts(pending, 0, tmp_path / "pending-run", None, None)

    supplied = _submission_config(
        tmp_path / "supplied", SubmissionSettings(False, False, True)
    )
    supplied_dir = ensure_submission_workspace(supplied, 0)
    final_pdf = supplied_dir / "graphical_abstract" / "graphical_abstract.pdf"
    final_pdf.write_bytes(b"user final")
    _stub_submission_compilers(monkeypatch, supplied)
    prepare_submission_artifacts(supplied, 0, tmp_path / "supplied-run", None, None)
    assert final_pdf.read_bytes() == b"user final"

    edited = _submission_config(
        tmp_path / "edited", SubmissionSettings(False, False, True)
    )
    edited_dir = ensure_submission_workspace(edited, 0)
    source = edited_dir / "graphical_abstract" / "graphical_abstract.tex"
    source.write_text("Edited graphical source.\n", encoding="utf-8")
    _stub_submission_compilers(monkeypatch, edited)
    prepare_submission_artifacts(edited, 0, tmp_path / "edited-run", None, None)
    assert (
        edited_dir / "graphical_abstract" / "graphical_abstract.pdf"
    ).read_bytes() == b"graphical_abstract"


@pytest.mark.parametrize(
    ("selected_round", "expected_name", "unexpected_name"),
    (
        (1, "First Author", "Changed External Author"),
        (2, "Changed External Author", "First Author"),
    ),
)
def test_submission_metadata_uses_frozen_authors_only_for_historical_rounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_round: int,
    expected_name: str,
    unexpected_name: str,
) -> None:
    initial = _workspace(tmp_path)
    save_meta(
        initial.round_dir(0) / "meta.yaml",
        replace(
            initial.metadata,
            correspondence=CorrespondenceSettings(signing_author="author_one"),
        ),
    )
    r02 = _revision(_revision(load_project(initial.project)))
    config = load_project(r02.project, selected_round)
    external = workspace_module.author_library_source_for_round(r02, 2)
    external_text = external.read_text(encoding="utf-8")
    assert "First Author" in external_text
    changed_external = yaml.safe_load(
        external_text.replace("First Author", "Changed External Author", 1)
    )
    if selected_round == 1:
        changed_external["authors"]["author_one"]["email"] = ""
    external.write_text(
        yaml.safe_dump(changed_external, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    submission = ensure_submission_workspace(config, selected_round)
    (submission / "cover_letter_body.tex").write_text(
        "Completed cover letter.\n", encoding="utf-8"
    )
    (submission / "highlights.tex").write_text(
        "Completed highlights.\n", encoding="utf-8"
    )
    graphical = submission / "graphical_abstract" / "graphical_abstract.tex"
    graphical.write_text("Completed graphical abstract.\n", encoding="utf-8")
    captured_metadata: list[str] = []

    def fake_clean(
        selected: ProjectConfig,
        round_number: int,
        run_dir: Path,
        _engine: str | None,
    ) -> Path:
        build = run_dir / "clean_build"
        build.mkdir(parents=True, exist_ok=True)
        (build / "manuscript.compiler.log").write_text("", encoding="utf-8")
        output = selected.output_dir(round_number) / "manuscript_clean.pdf"
        output.write_bytes(b"clean")
        return output

    def fake_marked(
        selected: ProjectConfig,
        round_number: int,
        run_dir: Path,
        _engine: str | None,
    ) -> MarkedResult:
        build = run_dir / "marked_build"
        build.mkdir(parents=True, exist_ok=True)
        (build / "manuscript_marked.compiler.log").write_text("", encoding="utf-8")
        output = selected.output_dir(round_number) / "manuscript_marked.pdf"
        output.write_bytes(b"marked")
        return MarkedResult(output, {})

    def fake_compile(
        source: Path,
        build_dir: Path,
        _config: ProjectConfig,
        _engine: str | None,
    ) -> CompileResult:
        captured_metadata.append(
            (source.parent / "author_metadata.tex").read_text(encoding="utf-8")
        )
        build_dir.mkdir(parents=True, exist_ok=True)
        pdf = build_dir / f"{source.stem}.pdf"
        pdf.write_bytes(b"submission source")
        return CompileResult(pdf, "", TeXStateFiles.discover(build_dir, source.stem))

    monkeypatch.setattr(submission_module, "build_clean_manuscript", fake_clean)
    monkeypatch.setattr(submission_module, "build_marked_manuscript", fake_marked)
    monkeypatch.setattr(submission_module, "compile_tex", fake_compile)
    monkeypatch.setattr(
        submission_module,
        "validate_revision_layout",
        lambda *_args: tmp_path / "layout.txt",
    )

    prepare_submission_artifacts(
        config,
        selected_round,
        tmp_path / f"submission-run-{selected_round}",
        None,
        None,
    )

    assert len(captured_metadata) == 3
    assert all(expected_name in text for text in captured_metadata)
    assert all(unexpected_name not in text for text in captured_metadata)


def test_atomic_submission_publication_restores_old_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _workspace(tmp_path)
    submission = config.submission_dir(0)
    submission.mkdir(exist_ok=True)
    old = {
        submission / "manuscript.pdf": b"old manuscript",
        submission / "highlights.pdf": b"old highlights",
    }
    for path, content in old.items():
        path.write_bytes(content)
    unrelated = submission / ".user.new"
    unrelated.write_bytes(b"user-owned hidden file")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "manuscript.pdf").write_bytes(b"new manuscript")
    (stage / "highlights.pdf").write_bytes(b"new highlights")
    run = tmp_path / "run"
    run.mkdir()
    real_replace = __import__("os").replace
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected publication failure")
        real_replace(source, target)

    monkeypatch.setattr("sci_manuscript.submission.os.replace", fail_second)
    with pytest.raises(OSError, match="injected"):
        _publish_submission_stage(
            config,
            0,
            stage,
            {Path("manuscript.pdf"), Path("highlights.pdf")},
            run,
        )
    assert {path: path.read_bytes() for path in old} == old
    assert set(submission.rglob(".*.new")) == {unrelated}
    assert unrelated.read_bytes() == b"user-owned hidden file"


def test_failed_build_preserves_previous_response_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = _revision(_workspace(tmp_path))
    response = revision.output_dir(1) / "response_letter.pdf"
    response.write_bytes(b"previous response")

    def fail_clean(*_args: object, **_kwargs: object) -> Path:
        raise WorkflowError("injected clean build failure")

    monkeypatch.setattr("sci_manuscript.api.build_clean_manuscript", fail_clean)
    with pytest.raises(WorkflowError, match="injected clean build failure"):
        ManuscriptProject(revision.project).build(target="clean")
    assert response.read_bytes() == b"previous response"


def test_modified_registered_graphical_pdf_becomes_user_source(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    submission = config.submission_dir(0)
    graphical = submission / "graphical_abstract" / "graphical_abstract.pdf"
    graphical.parent.mkdir(parents=True)
    graphical.write_bytes(b"generated")
    state = config.generated_artifacts_path(0)
    state.parent.mkdir(parents=True)
    state.write_text(
        yaml.safe_dump(
            {
                "schema": "sci-manuscript-generated-artifacts/v1",
                "paths": ["graphical_abstract/graphical_abstract.pdf"],
                "sha256": {
                    "graphical_abstract/graphical_abstract.pdf": hashlib.sha256(
                        b"generated"
                    ).hexdigest()
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert graphical.relative_to(submission) in _generated_submission_paths(
        config.round_dir(0)
    )

    graphical.write_bytes(b"user replacement")

    assert graphical.relative_to(submission) not in _generated_submission_paths(
        config.round_dir(0)
    )
    assert graphical in _submission_source_entries(config.round_dir(0))


@pytest.mark.parametrize(
    "unsafe_path",
    ("../../outside.pdf", "/tmp/outside.pdf"),
)
def test_generated_artifact_registry_rejects_unsafe_paths(
    tmp_path: Path, unsafe_path: str
) -> None:
    config = _workspace(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"user data")
    registry = config.generated_artifacts_path(0)
    registry.parent.mkdir(parents=True)
    registry.write_text(
        yaml.safe_dump(
            {
                "schema": "sci-manuscript-generated-artifacts/v1",
                "paths": [unsafe_path],
                "sha256": {unsafe_path: hashlib.sha256(b"user data").hexdigest()},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError, match="Invalid generated artifact registry"):
        _generated_submission_paths(config.round_dir(0))

    assert outside.read_bytes() == b"user data"


def test_failed_marked_build_restores_all_previous_build_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = _revision(_workspace(tmp_path))
    output = revision.output_dir(1)
    previous = {
        output / "manuscript_clean.pdf": b"old clean",
        output / "manuscript_marked.pdf": b"old marked",
        output / "response_letter.pdf": b"old response",
    }
    for path, content in previous.items():
        path.write_bytes(content)

    def publish_new_clean(*_args: object, **_kwargs: object) -> Path:
        clean = output / "manuscript_clean.pdf"
        clean.write_bytes(b"new clean")
        return clean

    monkeypatch.setattr("sci_manuscript.api.build_clean_manuscript", publish_new_clean)
    monkeypatch.setattr(
        "sci_manuscript.api.build_marked_manuscript",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            WorkflowError("injected marked build failure")
        ),
    )

    with pytest.raises(WorkflowError, match="injected marked build failure"):
        ManuscriptProject(revision.project).build()

    assert {path: path.read_bytes() for path in previous} == previous


def test_failed_submission_manifest_restores_previous_final_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _workspace(tmp_path)
    output = config.output_dir(0)
    submission = config.submission_dir(0)
    registry = config.generated_artifacts_path(0)
    registry.parent.mkdir(parents=True)
    previous = {
        output / "manuscript.pdf": b"old output",
        submission / "manuscript.pdf": b"old package",
        submission / "checklist.md": b"old checklist\n",
        registry: b"old registry\n",
    }
    for path, content in previous.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def publish_then_return(
        _config: ProjectConfig,
        _round_number: int,
        run_dir: Path,
        _engine: str | None,
        _audit: object,
    ) -> list[SubmissionArtifact]:
        build_dir = run_dir / "clean_build"
        build_dir.mkdir(parents=True)
        (build_dir / "manuscript.aux").write_text(
            "\\citation{replace_me}\n", encoding="utf-8"
        )
        (output / "manuscript.pdf").write_bytes(b"new output")
        (submission / "manuscript.pdf").write_bytes(b"new package")
        (submission / "checklist.md").write_bytes(b"new checklist\n")
        registry.write_bytes(b"new registry\n")
        return [SubmissionArtifact("Clean manuscript", output / "manuscript.pdf")]

    monkeypatch.setattr(
        "sci_manuscript.api.prepare_submission_artifacts", publish_then_return
    )
    monkeypatch.setattr(
        "sci_manuscript.api.write_build_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected manifest failure")
        ),
    )

    with pytest.raises(OSError, match="injected manifest failure"):
        ManuscriptProject(config.project).prepare_submission()

    assert {path: path.read_bytes() for path in previous} == previous
