"""Release-hardening regressions for the 2.0 ownership and audit contracts."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from test_core import _revision, _workspace

from sci_manuscript.api import ManuscriptProject, doctor
from sci_manuscript.compile import resolve_engine, select_engine
from sci_manuscript.errors import WorkflowError
from sci_manuscript.metadata import SubmissionSettings
from sci_manuscript.provenance import extract_provenance
from sci_manuscript.review import audit_reviews, parse_reviews
from sci_manuscript.review_ids import validate_review_id_list
from sci_manuscript.submission import (
    SubmissionArtifact,
    _publish_submission_stage,
    ensure_submission_workspace,
    prepare_submission_artifacts,
)
from sci_manuscript.tex import scan_tex_commands
from sci_manuscript.workspace import (
    ProjectConfig,
    _generated_submission_paths,
    _submission_source_entries,
    finalize_revision_creation,
    load_project,
    reindex_revisions,
    source_digest,
    temporary_run,
    write_build_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hashes(root: Path) -> dict[Path, str]:
    return {
        path.relative_to(root): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


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
    ) -> Path:
        return fake_submission_source(
            _source, "cover_letter", _config, run_dir, _engine
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


def test_reindex_preserves_submission_sources_and_user_graphical_pdf(
    tmp_path: Path,
) -> None:
    r01 = _revision(_workspace(tmp_path))
    r02 = _revision(r01)
    r03 = _revision(r02)
    source_hashes: dict[int, dict[Path, str]] = {}
    response_hashes: dict[int, dict[Path, str]] = {}
    scientific_hashes: dict[int, str] = {}
    for config, label in ((r02, b"r02"), (r03, b"r03")):
        number = config.current_round
        submission = config.submission_dir(number)
        graphical = submission / "graphical_abstract"
        graphical.mkdir(parents=True, exist_ok=True)
        sources = {
            submission / "cover_letter_body.tex": label + b" cover body\n",
            submission / "highlights.tex": label + b" highlights\n",
            submission / "checklist.md": b"# checklist\n\n" + label + b" user note\n",
            graphical / "graphical_abstract.tex": label + b" graphical TeX\n",
            graphical / "source.png": label + b" user png",
            graphical / "source.jpg": label + b" user jpg",
            graphical / "source.jpeg": label + b" user jpeg",
            graphical / "graphical_abstract.pdf": label + b" user final pdf",
        }
        for path, content in sources.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        comments = config.response_dir(number) / "reviewer_comments.md"
        responses = config.response_dir(number) / "responses.tex"
        comments.write_bytes(label + b" reviewer comments\n")
        responses.write_bytes(label + b" responses\n")
        source_hashes[number] = {
            path.relative_to(submission): _sha256(path) for path in sources
        }
        response_hashes[number] = _tree_hashes(config.response_dir(number))
        scientific_hashes[number] = source_digest(
            config.round_dir(number), scientific_only=True
        )
        for name in (
            "manuscript.pdf",
            "marked_manuscript.pdf",
            "response_letter.pdf",
            "cover_letter.pdf",
            "highlights.pdf",
        ):
            (submission / name).write_bytes(b"generated")
    shutil.rmtree(r03.round_dir(1))

    with temporary_run(r03.project) as run_dir:
        reindex_revisions(r03.project, run_dir)

    for old_number, new_number in ((2, 1), (3, 2)):
        migrated = r03.submission_dir(new_number)
        assert {
            relative: _sha256(migrated / relative)
            for relative in source_hashes[old_number]
        } == source_hashes[old_number]
        assert _tree_hashes(r03.response_dir(new_number)) == response_hashes[old_number]
        assert (
            source_digest(r03.round_dir(new_number), scientific_only=True)
            == scientific_hashes[old_number]
        )
        for name in (
            "manuscript.pdf",
            "marked_manuscript.pdf",
            "response_letter.pdf",
            "cover_letter.pdf",
            "highlights.pdf",
        ):
            assert not (migrated / name).exists()
        assert r03.creation_record_path(new_number).is_file()
    archive = max((r03.project / "00_archive").glob("reindex_*"))
    archived_hashes = _tree_hashes(archive / "revision_02" / "submission")
    assert {
        relative: archived_hashes[relative] for relative in source_hashes[2]
    } == source_hashes[2]
    assert not r03.tmp_root().exists()


def test_rollback_digest_protects_submission_sources(tmp_path: Path) -> None:
    revision = _revision(_workspace(tmp_path))
    cover = revision.submission_dir(1) / "cover_letter_body.tex"
    cover.write_text("user cover\n", encoding="utf-8")

    assert (
        source_digest(revision.round_dir(1))
        != yaml.safe_load(revision.creation_record_path(1).read_text(encoding="utf-8"))[
            "protected_source_digest"
        ]
    )
    archive = revision.archive_root()
    before = tuple(archive.iterdir()) if archive.is_dir() else ()
    with pytest.raises(WorkflowError, match="protected user or scientific source"):
        ManuscriptProject(revision.project).rollback(confirmed=True)
    assert (tuple(archive.iterdir()) if archive.is_dir() else ()) == before
    assert cover.read_text(encoding="utf-8") == "user cover\n"
    assert revision.round_dir(1).is_dir()


def test_reindex_failure_restores_round_state_and_submission_sources(
    tmp_path: Path,
) -> None:
    r01 = _revision(_workspace(tmp_path))
    r02 = _revision(r01)
    r03 = _revision(r02)
    for config, marker in ((r02, "r02"), (r03, "r03")):
        cover = config.submission_dir(config.current_round) / "cover_letter_body.tex"
        cover.write_text(marker, encoding="utf-8")
    shutil.rmtree(r03.round_dir(1))
    before_rounds = {number: _tree_hashes(r03.round_dir(number)) for number in (2, 3)}
    before_states = {number: _tree_hashes(r03.state_dir(number)) for number in (2, 3)}

    with pytest.raises(WorkflowError, match="Injected"):
        with temporary_run(r03.project, keep=True) as run_dir:
            reindex_revisions(r03.project, run_dir, fail_after_swap=True)

    assert not r03.round_dir(1).exists()
    for number in (2, 3):
        assert _tree_hashes(r03.round_dir(number)) == before_rounds[number]
        assert _tree_hashes(r03.state_dir(number)) == before_states[number]
    assert list(r03.tmp_root().glob("run_*"))


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


def test_associate_editor_ids_and_heading_are_canonical(tmp_path: Path) -> None:
    path = tmp_path / "reviews.md"
    path.write_text(
        "# Associate Editor\n## Main comment\n## Specific comments\n1. AE item\n",
        encoding="utf-8",
    )
    blocks = parse_reviews(path)
    assert blocks[0].comments[0].review_id == "AE-1"
    assert validate_review_id_list("AE-1,1-1") == ("AE-1", "1-1")


def test_review_index_distinguishes_changed_and_removed_comments(
    tmp_path: Path,
) -> None:
    revision = _revision(_workspace(tmp_path))
    comments = revision.response_dir(1) / "reviewer_comments.md"
    comments.write_text(
        "# Reviewer #1\n## Main comment\n## Specific comments\n"
        "1. First text.\n2. Second text.\n",
        encoding="utf-8",
    )
    audit_reviews(revision, 1, record_index=True)
    comments.write_text(
        "# Reviewer #1\n## Main comment\n## Specific comments\n1. Changed text.\n",
        encoding="utf-8",
    )
    audit = audit_reviews(revision, 1)
    codes = {issue.code for issue in audit.issues}
    assert "REVIEW_COMMENT_CHANGED" in codes
    assert "REVIEW_COMMENT_REMOVED" in codes


def test_engine_contract_includes_traditional_latex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ProjectConfig(tmp_path / "manuscript", _workspace(tmp_path).metadata)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert resolve_engine(config, "latex") == "latex"
    result = doctor(engine="latex")
    assert result.ready


def test_doctor_auto_uses_the_runtime_engine_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: None if name == "tectonic" else f"/usr/bin/{name}",
    )
    assert select_engine("auto") == "latex"
    result = doctor(engine="auto")
    assert result.ready
    assert any(check.name == "latexmk and driver" for check in result.checks)


def test_creation_digest_is_stable_for_generated_checklist_line(tmp_path: Path) -> None:
    revision = _revision(_workspace(tmp_path))
    checklist = revision.submission_dir(1) / "checklist.md"
    checklist.write_text("user note\n", encoding="utf-8")
    finalize_revision_creation(revision)
    before = source_digest(revision.round_dir(1))
    checklist.write_text(
        "user note\n\n- Review completeness: **COMPLETE**.\n", encoding="utf-8"
    )
    assert source_digest(revision.round_dir(1)) == before


def test_tex_scanner_ignores_comments_and_parses_nested_fields() -> None:
    text = (
        "% \\review{1-1}{disabled}\n"
        "\\review{AE-1}{active {nested} body}\n"
        "% \\input{disabled}\n\\input{sections/active}\n"
    )
    reviews = scan_tex_commands(text, ("review",), field_count=2)
    inputs = scan_tex_commands(text, ("input", "include"), field_count=1)
    assert reviews[0].fields == ("AE-1", "active {nested} body")
    assert inputs[0].fields == ("sections/active",)


def test_escaped_review_control_word_is_not_provenance() -> None:
    text = r"\\review{1-1}{literal documentation text}"
    provenance = extract_provenance(text)
    assert provenance.text == text
    assert provenance.review_spans == ()


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
        ManuscriptProject(revision.project).build()
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


def test_successful_build_manifest_contains_hashes_without_private_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _workspace(tmp_path)
    output = config.output_dir(0) / "manuscript.pdf"
    output.write_bytes(b"pdf")
    run = tmp_path / "manifest-run"
    run.mkdir()
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    path = write_build_manifest(config, 0, "build", (output,), "tectonic", run)
    text = path.read_text(encoding="utf-8")
    assert "sci-manuscript-build-manifest/v1" in text
    assert hashlib.sha256(b"pdf").hexdigest() in text
    assert str(tmp_path) not in text

    submission_pdf = config.submission_dir(0) / "manuscript.pdf"
    submission_pdf.write_bytes(b"submission pdf")
    submission_manifest = write_build_manifest(
        config, 0, "submission", (output,), "tectonic", run
    )
    submission_text = submission_manifest.read_text(encoding="utf-8")
    assert "initial_submission/submission/manuscript.pdf" in submission_text
    assert hashlib.sha256(b"submission pdf").hexdigest() in submission_text


def test_failed_manifest_update_preserves_previous_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _workspace(tmp_path)
    output = config.output_dir(0) / "manuscript.pdf"
    output.write_bytes(b"pdf")
    manifest = config.build_manifest_path(0)
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"previous successful manifest\n")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected")

    monkeypatch.setattr("sci_manuscript.workspace.os.replace", fail_replace)

    with pytest.raises(OSError, match="injected"):
        write_build_manifest(config, 0, "build", (output,), "tectonic", tmp_path)

    assert manifest.read_bytes() == b"previous successful manifest\n"
    assert not manifest.with_suffix(".yaml.new").exists()


def test_tool_version_failure_is_recorded_as_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    from sci_manuscript.workspace import _tool_version

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 2, "", "bad"),
    )
    assert _tool_version("tool") == "unknown"
