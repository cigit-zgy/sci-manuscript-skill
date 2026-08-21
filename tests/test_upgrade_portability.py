"""Project-format migration, portability, and source-integrity regressions."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

from sci_manuscript import workflow
from sci_manuscript import (
    ManuscriptError,
    ManuscriptProject,
    workflow as _workflow,
    initialize_manuscript,
)
from sci_manuscript.metadata import manuscript as metadata
from sci_manuscript.workflow import project as workspace

ROOT = Path(__file__).resolve().parents[1]
LEGACY_WRAPPER = ROOT / "tests" / "fixtures" / "legacy_run_v3_1.txt"


def _fake_clean(
    config: workspace.ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str | None = None,
) -> Path:
    del run_dir, engine
    output = config.round_dir(round_number) / "output"
    output.mkdir(exist_ok=True)
    target = output / (
        "manuscript.pdf" if round_number == 0 else "manuscript_clean.pdf"
    )
    target.write_bytes(b"%PDF-1.4\n% portability fixture\n")
    return target


def _initialize(path: Path) -> ManuscriptProject:
    with mock.patch.object(workflow.build, "build_clean_manuscript", _fake_clean):
        initialize_manuscript(
            path=path,
            title="Portable Anonymous Manuscript",
            journal="Example Journal",
            publisher="elsevier",
            selected_authors=("Guangyao Zhao", "Hong Liu"),
        )
    return ManuscriptProject(path)


def _make_legacy(project: Path) -> None:
    for path in sorted(project.glob("*/manuscript.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data.pop("workflow")
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_upgrade_recognized_legacy_wrapper_preserves_every_scientific_source() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project_path = Path(temp) / "Legacy Project 测试"
        project = _initialize(project_path)
        reviews = Path(temp) / "reviews.md"
        reviews.write_text("# Reviewer #1\n\n1. Anonymous comment.\n", encoding="utf-8")
        project.start_revision(reviews)
        _make_legacy(project_path)
        before = workspace.scientific_source_hashes(project_path)

        result = project.upgrade_project()

        assert result.status == "upgraded"
        assert result.from_format == 0
        assert result.to_format == metadata.CURRENT_PROJECT_FORMAT
        assert workspace.scientific_source_hashes(project_path) == before
        assert not list(project_path.rglob("*.bak"))
        assert not (project_path / "run.py").exists()
        for path in sorted(project_path.glob("*/manuscript.yaml")):
            loaded = metadata.load_manuscript(path)
            assert loaded.format_version == metadata.CURRENT_PROJECT_FORMAT
            assert loaded.created_with


def test_upgrade_is_noop_for_current_project() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "current")
        result = project.upgrade_project()
        assert result.status == "already_current"
        assert result.artifacts == ()


def test_upgrade_syncs_legacy_revision_style_and_preserves_sources() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project_path = Path(temp) / "Style Upgrade"
        project = _initialize(project_path)
        legacy_style = ROOT / "tests" / "fixtures" / "legacy_revision_style_v31.tex"
        style_target = project_path / "references" / "revision_style.tex"
        style_target.write_text(
            legacy_style.read_text(encoding="utf-8"), encoding="utf-8"
        )
        before = workspace.scientific_source_hashes(project_path)

        result = project.upgrade_project()

        assert result.status == "upgraded"
        assert result.from_format == metadata.CURRENT_PROJECT_FORMAT
        assert result.to_format == metadata.CURRENT_PROJECT_FORMAT
        packaged = ROOT / "src" / "resources" / "revision_style.tex"
        assert style_target.read_text(encoding="utf-8") == packaged.read_text(
            encoding="utf-8"
        )
        assert workspace.scientific_source_hashes(project_path) == before


def test_upgrade_refuses_user_customized_revision_style() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project_path = Path(temp) / "Custom Style"
        project = _initialize(project_path)
        style_target = project_path / "references" / "revision_style.tex"
        style_target.write_text(
            "\\definecolor{RevisionAddedColor}{RGB}{1,2,3}\n"
            "\\newcommand{\\RevisionAddedUnderline}[1]{#1}\n",
            encoding="utf-8",
        )
        before = style_target.read_text(encoding="utf-8")

        with pytest.raises(ManuscriptError, match="user-customized"):
            project.upgrade_project()

        assert style_target.read_text(encoding="utf-8") == before
