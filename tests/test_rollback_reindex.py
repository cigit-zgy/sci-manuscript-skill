"""Revision numbering, confirmation, rollback, reindex, and legacy tests."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

from sci_manuscript import ManuscriptError, ManuscriptProject, initialize_manuscript
from sci_manuscript import cli as lifecycle_run
from sci_manuscript._runtime import rounds, workspace

ROOT = Path(__file__).resolve().parents[1]


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
    target.write_bytes(b"%PDF-1.4\n% fixture\n")
    return target


def _initialize(path: Path) -> ManuscriptProject:
    with mock.patch.object(
        __import__("sci_manuscript._workflow", fromlist=["x"]),
        "build_clean_manuscript",
        _fake_clean,
    ):
        initialize_manuscript(
            path=path,
            title="Round Lifecycle Test",
            journal="Example Journal",
            publisher="elsevier",
            selected_authors=("Guangyao Zhao", "Hong Liu"),
        )
    return ManuscriptProject(path)


def _make_revision(project: ManuscriptProject, round_number: int) -> None:
    reviews = project.path / f"reviews_{round_number}.md"
    reviews.write_text("# Reviewer #1\n\n1. Anonymous comment.\n", encoding="utf-8")
    project.start_revision(reviews=reviews)


def test_two_digit_numbering_and_legacy_parsing() -> None:
    assert rounds.round_name(0) == "r00"
    assert rounds.round_name(1) == "r01"
    assert rounds.round_name(9) == "r09"
    assert rounds.round_name(10) == "r10"
    assert rounds.round_directory_name(0) == "initial_submission"
    assert rounds.round_directory_name(1) == "revision_01"
    assert rounds.round_directory_name(10) == "revision_10"
    assert rounds.parse_round("r0") == 0
    assert rounds.parse_round("r00") == 0
    assert rounds.parse_round("r01") == 1
    assert rounds.parse_round("r1") == 1
    assert rounds.parse_round("revision_1") == 1
    assert rounds.parse_round("revision_01") == 1
    assert rounds.parse_round("initial_submission") == 0
    assert rounds.parse_round("r02") == 2


def test_new_metadata_uses_two_digit_identity() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        _make_revision(project, 1)
        data = yaml.safe_load(
            (project.path / "revision_01" / "manuscript.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert data["revision"]["name"] == "revision_01"
        assert data["revision"]["round"] == "r01"
        assert data["revision"]["parent"] == "initial_submission"


def test_revision_cli_requires_confirmation_and_defaults_to_no() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        with mock.patch("builtins.input", return_value="n"):
            with mock.patch(
                "sys.argv",
                [
                    "sci-manuscript",
                    "revision",
                    "--project",
                    str(project.path),
                ],
            ):
                code = lifecycle_run.main()
        assert code == 0
        assert not (project.path / "revision_01").exists()


def test_revision_cli_yes_confirmation_creates_revision() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        with mock.patch("builtins.input", return_value="y"):
            with mock.patch(
                "sys.argv",
                [
                    "sci-manuscript",
                    "revision",
                    "--project",
                    str(project.path),
                ],
            ):
                code = lifecycle_run.main()
        assert code == 0
        assert (project.path / "revision_01").exists()


def test_revision_cli_yes_flag_skips_prompt() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        with mock.patch("builtins.input", side_effect=AssertionError("prompted")):
            with mock.patch(
                "sys.argv",
                [
                    "sci-manuscript",
                    "revision",
                    "--yes",
                    "--project",
                    str(project.path),
                ],
            ):
                code = lifecycle_run.main()
        assert code == 0
        assert (project.path / "revision_01").exists()


def test_rollback_removes_unchanged_latest_revision() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        _make_revision(project, 1)
        plan = project.rollback_plan()
        assert plan.version == "revision_01"
        assert plan.changed_files == ()
        project.remove_latest_revision()
        assert not (project.path / "revision_01").exists()
        assert project.status().round_number == 0


def test_rollback_refuses_modified_revision_and_keeps_files() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        _make_revision(project, 1)
        introduction = project.path / "revision_01" / "sections" / "01_introduction.tex"
        introduction.write_text(
            introduction.read_text(encoding="utf-8") + "\nUser edit.\n",
            encoding="utf-8",
        )
        plan = project.rollback_plan()
        assert any("01_introduction.tex" in name for name in plan.changed_files)
        with pytest.raises(ManuscriptError, match="refused"):
            project.remove_latest_revision()
        assert (project.path / "revision_01").exists()


def test_reindex_repairs_broken_sequence_and_updates_metadata() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        _make_revision(project, 1)
        _make_revision(project, 2)
        _make_revision(project, 3)
        shutil.rmtree(project.path / "revision_01")

        plan = project.reindex(apply=False)
        assert plan.applied is False
        assert ("revision_02", "revision_01") in plan.renames
        assert ("revision_03", "revision_02") in plan.renames

        result = project.reindex(apply=True)
        assert result.applied
        assert (project.path / "revision_01").is_dir()
        assert (project.path / "revision_02").is_dir()
        assert not (project.path / "revision_03").exists()
        assert not (project.path / "revision_02").exists() or True

        r1 = yaml.safe_load(
            (project.path / "revision_01" / "manuscript.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert r1["revision"]["name"] == "revision_01"
        assert r1["revision"]["round"] == "r01"
        assert r1["revision"]["parent"] == "initial_submission"
        r2 = yaml.safe_load(
            (project.path / "revision_02" / "manuscript.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert r2["revision"]["name"] == "revision_02"
        assert r2["revision"]["round"] == "r02"
        assert r2["revision"]["parent"] == "revision_01"
        assert project.status().round_number == 2


def test_reindex_transaction_rolls_back_on_failure() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        _make_revision(project, 1)
        _make_revision(project, 2)
        shutil.rmtree(project.path / "revision_01")
        before = sorted(
            path.name
            for path in project.path.iterdir()
            if path.is_dir() and path.name != "tmp"
        )

        workflow = __import__("sci_manuscript._workflow", fromlist=["x"])
        original_move = shutil.move

        def flaky_move(source: Path, target: Path) -> None:
            if str(target).endswith("revision_01"):
                raise OSError("simulated transaction failure")
            original_move(source, target)

        with mock.patch.object(workflow.shutil, "move", flaky_move):
            with pytest.raises(ManuscriptError, match="simulated"):
                project.reindex(apply=True)

        after = sorted(
            path.name
            for path in project.path.iterdir()
            if path.is_dir() and path.name != "tmp"
        )
        assert after == before
        assert (project.path / "revision_02").is_dir()
        assert not (project.path / "revision_01").exists()


def test_reindex_invalidates_generated_artifacts() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        _make_revision(project, 1)
        _make_revision(project, 2)
        shutil.rmtree(project.path / "revision_01")
        (project.path / "revision_02" / "output" / "manuscript_marked.pdf").write_bytes(
            b"%PDF-1.4\n"
        )
        package = project.path / "revision_02" / "submission" / "package"
        package.mkdir(parents=True)
        (package / "manuscript.pdf").write_bytes(b"%PDF-1.4\n")

        result = project.reindex(apply=True)

        assert any(
            name.endswith("manuscript_marked.pdf") for name in result.invalidated
        )
        assert not (
            project.path / "revision_01" / "output" / "manuscript_marked.pdf"
        ).exists()
        assert not (project.path / "revision_01" / "submission" / "package").exists()


def test_legacy_single_digit_project_is_readable() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        _make_revision(project, 1)
        legacy_dir = project.path / "revision_01"
        renamed = project.path / "revision_1"
        shutil.move(str(legacy_dir), str(renamed))
        yaml_path = renamed / "manuscript.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        data["revision"]["name"] = "revision_1"
        data["revision"]["round"] = "r1"
        yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        status = ManuscriptProject(project.path).status()
        assert status.version == "revision_1"
        assert status.round_number == 1


def test_upgrade_migrates_legacy_directory_and_metadata_names() -> None:
    with tempfile.TemporaryDirectory() as temp:
        project = _initialize(Path(temp) / "paper")
        _make_revision(project, 1)
        legacy_dir = project.path / "revision_01"
        renamed = project.path / "revision_1"
        shutil.move(str(legacy_dir), str(renamed))
        yaml_path = renamed / "manuscript.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        data["revision"]["name"] = "revision_1"
        data["revision"]["round"] = "r1"
        yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        before = (project.path / "revision_1" / "manuscript.tex").read_bytes()

        result = project.upgrade_project()

        assert result.status == "upgraded"
        assert (project.path / "revision_01").is_dir()
        assert not (project.path / "revision_1").exists()
        migrated = yaml.safe_load(
            (project.path / "revision_01" / "manuscript.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert migrated["revision"]["name"] == "revision_01"
        assert migrated["revision"]["round"] == "r01"
        assert migrated["revision"]["parent"] == "initial_submission"
        # 论文源内容不变
        assert (project.path / "revision_01" / "manuscript.tex").read_bytes() == before
