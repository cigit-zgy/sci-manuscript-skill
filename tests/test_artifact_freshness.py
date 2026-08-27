"""Artifact fingerprint, freshness, and manifest regression tests."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import sci_manuscript.workspace as workspace_module
from sci_manuscript.workspace import (
    build_artifact_is_current,
    write_build_manifest,
)
from test_core import _revision, _workspace


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
    assert "sci-manuscript-build-manifest/v3" in text
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


def test_response_source_change_invalidates_only_response_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _revision(_workspace(tmp_path))
    output = config.output_dir(1)
    clean = output / "manuscript_clean.pdf"
    marked = output / "manuscript_marked.pdf"
    response = output / "response_letter.pdf"
    for path in (clean, marked, response):
        path.write_bytes(path.name.encode())
    run = tmp_path / "manifest-run"
    run.mkdir()
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    write_build_manifest(config, 1, "build", (clean, marked, response), "tectonic", run)

    response_source = config.response_dir(1) / "responses.tex"
    response_source.write_text(
        response_source.read_text(encoding="utf-8") + "% response-only edit\n",
        encoding="utf-8",
    )

    assert build_artifact_is_current(config, 1, clean)
    assert build_artifact_is_current(config, 1, marked)
    assert not build_artifact_is_current(config, 1, response)


def test_response_template_change_invalidates_only_response_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _revision(_workspace(tmp_path))
    output = config.output_dir(1)
    clean = output / "manuscript_clean.pdf"
    marked = output / "manuscript_marked.pdf"
    response = output / "response_letter.pdf"
    for path in (clean, marked, response):
        path.write_bytes(path.name.encode())
    package_root = tmp_path / "package"
    template = package_root / "correspondence_templates/response/response_en.tex"
    template.parent.mkdir(parents=True)
    template.write_text("fixed response template v1\n", encoding="utf-8")
    monkeypatch.setattr("sci_manuscript.workspace.resources_root", lambda: package_root)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    run = tmp_path / "manifest-run"
    run.mkdir()
    write_build_manifest(config, 1, "build", (clean, marked, response), "tectonic", run)

    assert build_artifact_is_current(config, 1, response)
    template.write_text("fixed response template v2\n", encoding="utf-8")

    assert build_artifact_is_current(config, 1, clean)
    assert build_artifact_is_current(config, 1, marked)
    assert not build_artifact_is_current(config, 1, response)


def test_build_manifest_records_explicit_response_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _revision(_workspace(tmp_path))
    response = config.output_dir(1) / "response_letter.pdf"
    response.write_bytes(b"response")
    run = tmp_path / "manifest-run"
    run.mkdir()
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    manifest = write_build_manifest(
        config, 1, "build", (response,), "tectonic", run
    ).read_text(encoding="utf-8")

    assert "responses_source_sha256" in manifest
    assert "reviewer_comments_sha256" in manifest
    assert "response_template_sha256" in manifest
    assert "round_metadata_sha256" in manifest
    assert "marked_location_inputs_sha256" in manifest
    assert "artifact_input_digests" in manifest


def test_renderer_implementation_change_invalidates_all_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _revision(_workspace(tmp_path))
    outputs = tuple(
        config.output_dir(1) / name
        for name in (
            "manuscript_clean.pdf",
            "manuscript_marked.pdf",
            "response_letter.pdf",
        )
    )
    for output in outputs:
        output.write_bytes(output.name.encode())
    run = tmp_path / "manifest-run"
    run.mkdir()
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(workspace_module, "_implementation_digest", lambda: "v1")
    write_build_manifest(config, 1, "build", outputs, "tectonic", run)
    assert all(build_artifact_is_current(config, 1, output) for output in outputs)

    monkeypatch.setattr(workspace_module, "_implementation_digest", lambda: "v2")

    assert not any(build_artifact_is_current(config, 1, output) for output in outputs)


@pytest.mark.parametrize(
    "runtime_name",
    ("marked_runtime.tex", "location_runtime.tex"),
)
def test_revision_runtime_resource_change_invalidates_marked_and_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_name: str,
) -> None:
    config = _revision(_workspace(tmp_path))
    clean, marked, response = (
        config.output_dir(1) / name
        for name in (
            "manuscript_clean.pdf",
            "manuscript_marked.pdf",
            "response_letter.pdf",
        )
    )
    for output in (clean, marked, response):
        output.write_bytes(output.name.encode())
    package_root = tmp_path / "package"
    revision = package_root / "revision"
    revision.mkdir(parents=True)
    for name in ("marked_runtime.tex", "location_runtime.tex"):
        (revision / name).write_text(f"{name} v1\n", encoding="utf-8")
    response_template = (
        package_root / "correspondence_templates/response/response_en.tex"
    )
    response_template.parent.mkdir(parents=True)
    response_template.write_text("response template\n", encoding="utf-8")
    monkeypatch.setattr(workspace_module, "resources_root", lambda: package_root)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    run = tmp_path / "manifest-run"
    run.mkdir()
    write_build_manifest(config, 1, "build", (clean, marked, response), "tectonic", run)
    assert all(
        build_artifact_is_current(config, 1, output)
        for output in (clean, marked, response)
    )

    runtime = revision / runtime_name
    runtime.write_text(f"{runtime_name} v2\n", encoding="utf-8")

    assert build_artifact_is_current(config, 1, clean)
    assert not build_artifact_is_current(config, 1, marked)
    assert not build_artifact_is_current(config, 1, response)


def test_toolchain_identity_change_invalidates_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _workspace(tmp_path)
    output = config.output_dir(0) / "manuscript.pdf"
    output.write_bytes(b"pdf")
    run = tmp_path / "manifest-run"
    run.mkdir()
    identity = {"engine": "tectonic", "engine_version": "v1"}
    monkeypatch.setattr(
        workspace_module, "_toolchain_identity", lambda *_args: dict(identity)
    )
    monkeypatch.setattr(
        "sci_manuscript.compile.resolve_engine", lambda *_args: "tectonic"
    )
    write_build_manifest(config, 0, "build", (output,), "tectonic", run)
    assert build_artifact_is_current(config, 0, output, "tectonic")

    identity["engine_version"] = "v2"

    assert not build_artifact_is_current(config, 0, output, "tectonic")


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
