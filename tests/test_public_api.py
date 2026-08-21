"""Public API, CLI parity, and no-autonomous-edit regression tests."""

from __future__ import annotations

import contextlib
import hashlib
import io
import shutil
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]

import sci_manuscript
from sci_manuscript import (
    Artifact,
    ManuscriptProject,
    cli,
    initialize_manuscript,
)
from sci_manuscript import workflow as _workflow
from sci_manuscript.workflow import project as workspace


def test_public_exports_exclude_runtime_internals() -> None:
    """Only stable lifecycle operations and result records are exported."""
    assert "ManuscriptProject" in sci_manuscript.__all__
    assert "initialize_manuscript" in sci_manuscript.__all__
    assert "_flatten_tex" not in sci_manuscript.__all__
    assert "compile_tex" not in sci_manuscript.__all__


def _fake_clean(
    config: workspace.ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str | None = None,
) -> Path:
    del run_dir, engine
    round_dir = config.round_dir(round_number)
    output = round_dir / "output"
    output.mkdir(exist_ok=True)
    name = "manuscript.pdf" if round_number == 0 else "manuscript_clean.pdf"
    target = output / name
    target.write_bytes(b"%PDF-1.4\n% anonymous test fixture\n")
    return target


def _initialize(path: Path) -> None:
    with mock.patch.object(workflow.build, "build_clean_manuscript", _fake_clean):
        initialize_manuscript(
            path=path,
            title="Anonymous Lifecycle Example",
            journal="Example Journal",
            publisher="elsevier",
            language="en",
            selected_authors=("Guangyao Zhao", "Hong Liu"),
        )


def _tex_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    manuscript_sources = [
        directory / "manuscript.tex",
        directory / "preamble.tex",
        *sorted((directory / "sections").rglob("*.tex")),
        *sorted((directory / "figures").rglob("*.tex")),
        *sorted((directory / "tables").rglob("*.tex")),
    ]
    for path in manuscript_sources:
        if not path.is_file():
            continue
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_public_api_initialization_status_check_and_zotero() -> None:
    """High-level lifecycle calls return typed project artifacts."""
    with tempfile.TemporaryDirectory() as temp:
        project_path = Path(temp) / "paper"
        _initialize(project_path)
        project = ManuscriptProject(project_path)

        status = project.status()
        check = project.check()
        zotero = project.setup_zotero()

        assert status.version == "initial_submission"
        assert status.round_number == 0
        assert check.passed
        assert {artifact.label for artifact in zotero.artifacts} == {
            "Bibliography target",
            "Setup guide",
        }


def test_start_revision_preserves_all_parent_tex_hashes() -> None:
    """Starting a revision creates infrastructure without editing its parent."""
    with tempfile.TemporaryDirectory() as temp:
        project_path = Path(temp) / "paper"
        _initialize(project_path)
        reviews = Path(temp) / "reviews.md"
        reviews.write_text(
            "# Reviewer #1\n\n1. Please clarify this point.\n",
            encoding="utf-8",
        )
        parent = project_path / "initial_submission"
        before = _tex_digest(parent)

        result = ManuscriptProject(project_path).start_revision(reviews=reviews)

        assert result.version == "revision_01"
        assert result.parent == "initial_submission"
        assert _tex_digest(parent) == before
        assert result.artifacts[0].path.is_file()


def test_build_and_cli_report_the_same_artifact() -> None:
    """The CLI formats paths returned by the same public build operation."""
    with tempfile.TemporaryDirectory() as temp:
        project_path = Path(temp) / "paper"
        _initialize(project_path)
        project = ManuscriptProject(project_path)
        with mock.patch.object(workflow.build, "build_clean_manuscript", _fake_clean):
            api_result = project.build()
            arguments = cli.build_parser().parse_args(
                ["build", "--project", str(project_path)]
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = cli.execute(arguments)

        relative = (
            api_result.artifacts[0].path.relative_to(project_path.resolve()).as_posix()
        )
        assert exit_code == 0
        assert relative in output.getvalue()
        assert api_result.artifacts[0].path.is_file()


def test_build_all_returns_every_existing_final_artifact() -> None:
    """The public all operation exposes complete structured artifact output."""
    with tempfile.TemporaryDirectory() as temp:
        project_path = Path(temp) / "paper"
        _initialize(project_path)
        package = project_path / "initial_submission" / "submission" / "package"
        output = project_path / "initial_submission" / "output"
        package.mkdir(parents=True)
        output.mkdir(exist_ok=True)
        clean = output / "manuscript.pdf"
        cover = package / "cover_letter.pdf"
        clean.write_bytes(b"pdf")
        cover.write_bytes(b"pdf")
        artifacts = (
            Artifact("Clean manuscript", clean),
            Artifact("Cover letter", cover),
            Artifact("Submission package", package),
        )
        with mock.patch.object(
            workflow.submission, "_prepare_submission", return_value=artifacts
        ):
            result = ManuscriptProject(project_path).build_all()

        assert result.artifacts == artifacts
        assert all(artifact.path.exists() for artifact in result.artifacts)


@pytest.mark.skipif(
    any(
        shutil.which(tool) is None
        for tool in ("tectonic", "latexdiff", "pdftotext", "pdftoppm")
    ),
    reason="complete LaTeX toolchain is required for lifecycle E2E",
)
def test_real_public_api_r0_r1_r2_and_cli_parity() -> None:
    """Run the real adjacent lifecycle and prove revision creation is source-safe."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        project_path = root / "anonymous-paper"
        initialize_manuscript(
            path=project_path,
            title="Anonymous Lifecycle Example",
            journal="Example Journal",
            publisher="elsevier",
            language="en",
            selected_authors=("Guangyao Zhao", "Hong Liu"),
        )
        project = ManuscriptProject(project_path, engine="tectonic")
        assert project.build().artifacts[0].path.is_file()

        for round_number in (1, 2):
            parent_name = (
                "initial_submission"
                if round_number == 1
                else f"revision_{round_number - 1:02d}"
            )
            parent = project_path / parent_name
            before = _tex_digest(parent)
            reviews = root / f"reviews_{round_number}.md"
            reviews.write_text(
                "# Reviewer #1\n\n1. Please clarify the anonymous example.\n",
                encoding="utf-8",
            )
            result = project.start_revision(reviews=reviews)
            assert _tex_digest(parent) == before
            version = project_path / result.version
            introduction = version / "sections" / "01_introduction.tex"
            introduction.write_text(
                introduction.read_text(encoding="utf-8")
                + f"\n\\review{{1-1}}{{Anonymous revision {round_number} text.}}\n",
                encoding="utf-8",
            )
            response = version / "response" / "response_letter.tex"
            response.write_text(
                response.read_text(encoding="utf-8").replace(
                    r"\ResponsePending{1-1}",
                    "Thank you. The user-approved anonymous text was applied.",
                ),
                encoding="utf-8",
            )
            before_build = _tex_digest(version)
            built = project.build_all()
            assert _tex_digest(version) == before_build
            names = {artifact.path.name for artifact in built.artifacts}
            assert {
                "manuscript_clean.pdf",
                "manuscript_marked.pdf",
                "response_letter.pdf",
                "cover_letter.pdf",
                "highlights.pdf",
                "graphical_abstract.pdf",
            }.issubset(names)

        latest = project_path / "revision_02"
        before_cli = _tex_digest(latest)
        cli_result = subprocess.run(
            [sys.executable, "-m", "sci_manuscript", "all", "--project", "."],
            cwd=project_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        assert cli_result.returncode == 0, cli_result.stderr
        assert _tex_digest(latest) == before_cli
        for artifact in project.build_all().artifacts:
            relative = artifact.path.relative_to(project_path.resolve()).as_posix()
            assert relative in cli_result.stdout
        assert not any((project_path / "tmp").iterdir())
