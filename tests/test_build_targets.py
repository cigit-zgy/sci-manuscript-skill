"""Round selection, target dependencies, and timing interface contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_core import _revision, _workspace

import sci_manuscript.api as api_module
import sci_manuscript.compile as compile_module
from sci_manuscript.api import BuildTarget, ManuscriptProject
from sci_manuscript.compile import CompileResult
from sci_manuscript.diff import MarkedResult
from sci_manuscript.errors import WorkflowError
from sci_manuscript.timing import BuildTelemetry
from sci_manuscript.workspace import (
    ProjectConfig,
    ensure_historical_round_state,
    load_project,
    write_build_manifest,
)


def _reviewed_revision(tmp_path: Path) -> ProjectConfig:
    reviews = tmp_path / "reviews.md"
    reviews.write_text(
        "# Reviewer #1\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Please revise the manuscript.\n",
        encoding="utf-8",
    )
    return _revision(_workspace(tmp_path), reviews)


def _stub_build_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, dict[str, object]]]:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_clean(
        config: ProjectConfig,
        round_number: int,
        run_dir: Path,
        _engine: str | None,
        _telemetry: BuildTelemetry | None = None,
    ) -> Path:
        calls.append(("clean", {}))
        build = run_dir / "clean_build"
        build.mkdir(parents=True)
        (build / "manuscript.aux").write_text("", encoding="utf-8")
        (build / "manuscript.bbl").write_text(
            "\\begin{thebibliography}{0}\n\\end{thebibliography}\n",
            encoding="utf-8",
        )
        (build / "manuscript.compiler.log").write_text("", encoding="utf-8")
        name = "manuscript.pdf" if round_number == 0 else "manuscript_clean.pdf"
        output = config.output_dir(round_number) / name
        output.write_bytes(b"clean")
        return output

    def fake_marked(
        config: ProjectConfig,
        round_number: int,
        run_dir: Path,
        _engine: str | None,
        **kwargs: object,
    ) -> MarkedResult:
        calls.append(("marked", kwargs))
        build = run_dir / "marked_build"
        build.mkdir(parents=True, exist_ok=True)
        (build / "manuscript_marked.compiler.log").write_text("", encoding="utf-8")
        aux = build / "manuscript_marked.aux"
        aux.write_text("", encoding="utf-8")
        output = config.output_dir(round_number) / "manuscript_marked.pdf"
        if kwargs.get("reuse_marked_pdf") is None:
            output.write_bytes(b"marked")
        locations = {"1-1": "Line 1"} if kwargs.get("include_locations") else {}
        return MarkedResult(output, locations, (), aux)

    def fake_response(
        config: ProjectConfig,
        round_number: int,
        locations: dict[str, str],
        _run_dir: Path,
        _engine: str | None,
        _telemetry: BuildTelemetry | None = None,
    ) -> Path:
        calls.append(("response", {"locations": locations}))
        output = config.output_dir(round_number) / "response_letter.pdf"
        output.write_bytes(b"response")
        return output

    monkeypatch.setattr(api_module, "build_clean_manuscript", fake_clean)
    monkeypatch.setattr(api_module, "build_marked_manuscript", fake_marked)
    monkeypatch.setattr(api_module, "build_response", fake_response)
    monkeypatch.setattr(api_module, "snapshot_bibliography", lambda *_a, **_k: None)
    monkeypatch.setattr(api_module, "write_build_manifest", lambda *_a, **_k: Path())
    return calls


def test_initial_submission_default_builds_only_manuscript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _workspace(tmp_path)
    calls = _stub_build_pipeline(monkeypatch)

    result = ManuscriptProject(config.project).build()

    assert [name for name, _kwargs in calls] == ["clean"]
    assert [item.label for item in result.artifacts] == ["Manuscript"]


def test_revision_default_builds_only_marked_fast_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _revision(_workspace(tmp_path))
    calls = _stub_build_pipeline(monkeypatch)

    result = ManuscriptProject(config.project).build()

    assert [name for name, _kwargs in calls] == ["marked"]
    kwargs = calls[0][1]
    assert kwargs["validate_clean"] is False
    assert kwargs["include_locations"] is False
    assert [item.label for item in result.artifacts] == ["Marked manuscript"]


def test_clean_target_skips_diff_location_and_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _revision(_workspace(tmp_path))
    calls = _stub_build_pipeline(monkeypatch)

    ManuscriptProject(config.project).build(target="clean")

    assert [name for name, _kwargs in calls] == ["clean"]


def test_response_target_builds_stale_marked_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _reviewed_revision(tmp_path)
    calls = _stub_build_pipeline(monkeypatch)
    monkeypatch.setattr(api_module, "build_artifact_is_current", lambda *_a: False)

    ManuscriptProject(config.project).build(target="response")

    assert [name for name, _kwargs in calls] == ["marked", "response"]
    assert calls[0][1]["include_locations"] is True
    assert calls[0][1]["reuse_marked_pdf"] is None


def test_response_target_reuses_current_marked_pdf_without_recompiling_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _reviewed_revision(tmp_path)
    marked = config.output_dir(1) / "manuscript_marked.pdf"
    marked.write_bytes(b"current marked")
    calls = _stub_build_pipeline(monkeypatch)
    monkeypatch.setattr(api_module, "build_artifact_is_current", lambda *_a: True)

    result = ManuscriptProject(config.project).build(target="response")

    assert [name for name, _kwargs in calls] == ["marked", "response"]
    assert calls[0][1]["reuse_marked_pdf"] == marked
    assert [item.label for item in result.artifacts] == ["Response letter"]


def test_all_target_executes_clean_marked_location_and_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _reviewed_revision(tmp_path)
    calls = _stub_build_pipeline(monkeypatch)

    result = ManuscriptProject(config.project).build(target="all")

    assert [name for name, _kwargs in calls] == ["clean", "marked", "response"]
    assert calls[1][1]["validate_clean"] is True
    assert calls[1][1]["include_locations"] is True
    assert {item.label for item in result.artifacts} == {
        "Clean manuscript",
        "Marked manuscript",
        "Response letter",
    }


def test_stale_selective_build_removes_other_pdfs_and_output_debug_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _revision(_workspace(tmp_path))
    output = config.output_dir(1)
    (output / "manuscript_clean.pdf").write_bytes(b"stale clean")
    (output / "response_letter.pdf").write_bytes(b"stale response")
    (output / "diff_audit.json").write_text("{}\n", encoding="utf-8")
    _stub_build_pipeline(monkeypatch)

    ManuscriptProject(config.project).build()

    assert {path.name for path in output.iterdir()} == {"manuscript_marked.pdf"}


def test_current_selective_build_retains_valid_pdfs_but_purges_debug_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _revision(_workspace(tmp_path))
    output = config.output_dir(1)
    (output / "manuscript_clean.pdf").write_bytes(b"current clean")
    (output / "response_letter.pdf").write_bytes(b"current response")
    (output / "highlight_audit.json").write_text("{}\n", encoding="utf-8")
    _stub_build_pipeline(monkeypatch)
    monkeypatch.setattr(api_module, "build_artifact_is_current", lambda *_a: True)

    ManuscriptProject(config.project).build()

    assert {path.name for path in output.iterdir()} == {
        "manuscript_clean.pdf",
        "manuscript_marked.pdf",
        "response_letter.pdf",
    }


def test_selected_historical_round_does_not_change_active_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r02 = _revision(_revision(_workspace(tmp_path)))
    calls = _stub_build_pipeline(monkeypatch)
    monkeypatch.setattr(
        api_module,
        "ensure_manuscript_sources",
        lambda *_a: (_ for _ in ()).throw(AssertionError("historical mutation")),
    )

    result = ManuscriptProject(r02.project).build(round="revision_01")

    assert result.version == "revision_01"
    assert [name for name, _kwargs in calls] == ["marked"]
    assert load_project(r02.project).current_round == 2


def test_explicit_initial_submission_builds_historical_manuscript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r01 = _revision(_workspace(tmp_path))
    calls = _stub_build_pipeline(monkeypatch)

    result = ManuscriptProject(r01.project).build(round="initial_submission")

    assert result.version == "initial_submission"
    assert [name for name, _kwargs in calls] == ["clean"]
    assert load_project(r01.project).current_round == 1


def test_start_revision_freezes_parent_scientific_state(tmp_path: Path) -> None:
    config = _workspace(tmp_path)

    ManuscriptProject(config.project).start_revision(confirmed=True)

    frozen = config.state_dir(0) / "round_state.yaml"
    assert frozen.is_file()
    text = frozen.read_text(encoding="utf-8")
    assert "sci-manuscript-round-state/v1" in text
    assert "scientific_source_sha256" in text
    assert "metadata_sha256" in text
    assert "bibliography_snapshot_sha256" in text
    assert "effective_authors_sha256" in text


def test_historical_build_preserves_frozen_state_and_bibliography_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r01 = _revision(_workspace(tmp_path))
    _stub_build_pipeline(monkeypatch)
    frozen = r01.state_dir(0) / "round_state.yaml"
    bibliography = r01.bibliography_snapshot_path(0)
    before = (frozen.read_bytes(), bibliography.read_bytes())

    ManuscriptProject(r01.project).build(round="initial_submission")

    assert (frozen.read_bytes(), bibliography.read_bytes()) == before


def test_historical_source_edit_is_rejected_before_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r01 = _revision(_workspace(tmp_path))
    calls = _stub_build_pipeline(monkeypatch)
    source = r01.round_dir(0) / "sections" / "01_introduction.tex"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8"
    )

    with pytest.raises(WorkflowError, match="HISTORICAL_ROUND_STATE_MISMATCH"):
        ManuscriptProject(r01.project).build(round="initial_submission")

    assert calls == []


def test_historical_bibliography_snapshot_edit_is_rejected_before_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r01 = _revision(_workspace(tmp_path))
    calls = _stub_build_pipeline(monkeypatch)
    bibliography = r01.bibliography_snapshot_path(0)
    bibliography.write_text(
        bibliography.read_text(encoding="utf-8") + "\n% changed\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError, match="HISTORICAL_ROUND_STATE_MISMATCH"):
        ManuscriptProject(r01.project).build(round="initial_submission")

    assert calls == []


def test_active_round_remains_editable_with_frozen_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r01 = _revision(_workspace(tmp_path))
    calls = _stub_build_pipeline(monkeypatch)
    source = r01.round_dir(1) / "sections" / "01_introduction.tex"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nactive edit\n", encoding="utf-8"
    )

    ManuscriptProject(r01.project).build(target="clean")

    assert [name for name, _kwargs in calls] == ["clean"]


def test_legacy_manifest_bootstraps_historical_round_state(tmp_path: Path) -> None:
    r00 = _workspace(tmp_path)
    output = r00.output_dir(0) / "manuscript.pdf"
    output.write_bytes(b"legacy pdf")
    run = tmp_path / "legacy-manifest"
    run.mkdir()
    write_build_manifest(r00, 0, "build", (output,), "tectonic", run)
    r01 = _revision(r00)
    child_output = r01.output_dir(1) / "manuscript_marked.pdf"
    child_output.write_bytes(b"legacy child pdf")
    write_build_manifest(r01, 1, "build", (child_output,), "tectonic", run)
    frozen = r01.round_state_path(0)
    frozen.unlink()

    migrated = ensure_historical_round_state(r01, 0)

    assert migrated == frozen
    assert "sci-manuscript-round-state/v1" in migrated.read_text(encoding="utf-8")


def test_missing_round_lists_available_rounds(tmp_path: Path) -> None:
    config = _revision(_workspace(tmp_path))

    with pytest.raises(WorkflowError) as caught:
        ManuscriptProject(config.project).build(round="revision_03")

    message = str(caught.value)
    assert 'Round "revision_03" does not exist.' in message
    assert "- initial_submission" in message
    assert "- revision_01" in message


def test_response_preflight_lists_missing_requirements_and_available_targets(
    tmp_path: Path,
) -> None:
    config = _reviewed_revision(tmp_path)
    (config.response_dir(1) / "responses.tex").unlink()

    with pytest.raises(WorkflowError) as caught:
        ManuscriptProject(config.project).build(target="response")

    message = str(caught.value)
    assert 'target "response" is not buildable' in message
    assert "response/responses.tex is missing" in message
    assert "Available targets:" in message
    assert "- marked" in message


@pytest.mark.parametrize("target", ("marked", "response"))
def test_initial_submission_rejects_revision_only_targets(
    tmp_path: Path,
    target: BuildTarget,
) -> None:
    config = _workspace(tmp_path)

    with pytest.raises(WorkflowError, match="unavailable for initial_submission"):
        ManuscriptProject(config.project).build(target=target)


def test_timing_report_accumulates_stages_and_invocations() -> None:
    telemetry = BuildTelemetry()
    with telemetry.measure("preflight"):
        telemetry.latex_invocations += 2
        telemetry.bibliography_invocations += 1
        telemetry.bibliography_cache_hits += 1
        telemetry.latexdiff_invocations += 1

    report = telemetry.report()

    assert dict(report.stages)["preflight"] >= 0
    assert report.latex_invocations == 2
    assert report.bibliography_invocations == 1
    assert report.bibliography_cache_hits == 1
    assert report.latexdiff_invocations == 1


def test_bibliography_cache_is_content_keyed_and_invalidates_on_input_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _workspace(tmp_path)
    source_dir = tmp_path / "staged"
    source_dir.mkdir()
    source = source_dir / "manuscript.tex"
    flattened = "\\begin{document}\\cite{a}\\bibliography{references}\\end{document}"
    source.write_text(flattened, encoding="utf-8")
    bibliography = source_dir / "references.bib"
    bibliography.write_text("@article{a,title={A}}\n", encoding="utf-8")
    cache = config.tmp_root() / "cache" / "bibliography"
    compile_calls = 0

    def fake_compile(
        staged: Path,
        build_dir: Path,
        _config: ProjectConfig,
        _engine: str | None,
        *,
        keep_intermediates: bool,
        telemetry: BuildTelemetry | None = None,
    ) -> CompileResult:
        del keep_intermediates, telemetry
        nonlocal compile_calls
        compile_calls += 1
        build_dir.mkdir(parents=True)
        bbl = build_dir / f"{staged.stem}.bbl"
        bbl.write_text(f"bibliography {compile_calls}\n", encoding="utf-8")
        pdf = build_dir / f"{staged.stem}.pdf"
        pdf.write_bytes(b"pdf")
        return CompileResult(pdf, "")

    monkeypatch.setattr(compile_module, "compile_tex", fake_compile)
    first = compile_module.materialize_bibliography(
        source, flattened, tmp_path / "build-1", config, "tectonic", None, cache
    )
    second = compile_module.materialize_bibliography(
        source, flattened, tmp_path / "build-2", config, "tectonic", None, cache
    )
    bibliography.write_text("@article{a,title={Changed}}\n", encoding="utf-8")
    third = compile_module.materialize_bibliography(
        source, flattened, tmp_path / "build-3", config, "tectonic", None, cache
    )

    assert first == second == "bibliography 1\n"
    assert third == "bibliography 2\n"
    assert compile_calls == 2
    assert cache.is_relative_to(config.tmp_root())
    assert not any(config.output_dir(0).glob("*.json"))
