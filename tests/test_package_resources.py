"""Installed package-resource, typing, and renderer-freeze contracts."""

from __future__ import annotations

import ast
import hashlib
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

import sci_manuscript

ROOT = Path(__file__).resolve().parents[1]
STYLE_SHA256 = "490884f07113dcc8d2e6cd611a9aa53a9777f7333b2de7a0aef515d00fbdcf38"
RUNTIME_SHA256 = "75ed945995a1d687d66e0059496eff72b998728f22edb4491d3d86ac9aa977d8"


def test_critical_runtime_and_publisher_resources_are_importable() -> None:
    resources = files("sci_manuscript.resources")
    required = (
        "authors.yaml",
        "revision_style.tex",
        "project_run.py",
        "manuscript/preamble.tex",
        "response/response_en.tex",
        "response/response_zh.tex",
        "submission/cover_letter_en.tex",
        "submission/highlights.tex",
        "journal_templates/elsevier/elsarticle.cls",
        "journal_templates/elsevier/elsarticle-num.bst",
        "journal_templates/nature/sn-jnl.cls",
        "journal_templates/nature/sn-nature.bst",
        "journal_templates/acs/achemso.cls",
        "journal_templates/acs/achemso.dtx",
        "journal_templates/chinese/kxtbcas.cls",
    )
    for relative in required:
        item = resources
        for part in relative.split("/"):
            item = item.joinpath(part)
        assert item.is_file(), relative


def test_revision_style_and_runtime_visual_semantics_are_frozen() -> None:
    resources = files("sci_manuscript.resources")
    style = resources.joinpath("revision_style.tex").read_bytes()
    assert hashlib.sha256(style).hexdigest() == STYLE_SHA256

    path = ROOT / "src" / "sci_manuscript" / "_runtime" / "diff.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    runtime = None
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "REVISION_RUNTIME"
            for target in node.targets
        ):
            runtime = ast.literal_eval(node.value)
            break
    assert isinstance(runtime, str)
    assert hashlib.sha256(runtime.encode()).hexdigest() == RUNTIME_SHA256


def test_public_package_is_typed_and_version_comes_from_distribution_metadata() -> None:
    package = files("sci_manuscript")
    assert package.joinpath("py.typed").is_file()
    assert sci_manuscript.__version__ == version("sci-manuscript-skill")
    assert "__version__" in sci_manuscript.__all__
    assert "UpgradeResult" in sci_manuscript.__all__
    assert "_runtime" not in sci_manuscript.__all__


def test_package_runtime_has_no_repo_or_sys_path_fallback() -> None:
    package_root = ROOT / "src" / "sci_manuscript"
    python_sources = [
        path
        for path in package_root.rglob("*.py")
        if "resources" not in path.relative_to(package_root).parts
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in python_sources)
    assert "sys.path.insert" not in combined
    assert "sys.path.append" not in combined
    assert ' / "scripts"' not in combined
    assert "SCI_MANUSCRIPT_SKILL_ROOT" not in combined


def test_generated_project_wrapper_depends_only_on_installed_package() -> None:
    wrapper = (
        files("sci_manuscript.resources")
        .joinpath("project_run.py")
        .read_text(encoding="utf-8")
    )
    assert "from sci_manuscript.cli import main" in wrapper
    assert "SCI_MANUSCRIPT_SKILL_ROOT" not in wrapper
    assert "sys.path" not in wrapper
    assert str(ROOT) not in wrapper
