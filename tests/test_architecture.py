"""Repository, package-resource, and documentation contract tests."""

from __future__ import annotations

import ast
import struct
import subprocess
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "sci_manuscript"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_readme_screenshots_are_real_equal_size_pngs() -> None:
    marked = ROOT / "docs" / "images" / "marked_manuscript.png"
    response = ROOT / "docs" / "images" / "response_letter.png"
    assert marked.stat().st_size > 100_000
    assert response.stat().st_size > 50_000
    assert _png_size(marked) == _png_size(response) == (1275, 1754)


def test_runtime_resources_are_package_data() -> None:
    root = files("sci_manuscript.resources")
    required = (
        "authors.yaml",
        "revision_style.template.tex",
        "revision/marked_runtime.tex",
        "revision/location_runtime.tex",
        "reviewer_comments/reviewer_comments_en.md",
        "reviewer_comments/reviewer_comments_zh.md",
        "manuscript_preamble/common.tex",
        "manuscript_preamble/zh.tex",
        "manuscript_preamble/en.tex",
        "manuscript/sections/default/00_frontmatter_zh.tex",
        "manuscript/sections/default/01_introduction.tex",
        "manuscript/sections/default/01_introduction_zh.tex",
        "correspondence_templates/response/response_en.tex",
        "correspondence_templates/cover_letter/cover_letter_en.tex",
        "submission/cover_letter_body_en.tex",
        "submission/highlights.tex",
        "journal_templates/elsevier/elsarticle.cls",
        "journal_templates/elsevier/elsarticle-num.bst",
        "journal_templates/nature/sn-jnl.cls",
        "journal_templates/nature/sn-nature.bst",
        "journal_templates/acs/achemso.cls",
        "journal_templates/acs/achemso.dtx",
        "journal_templates/chinese/kxtbcas.cls",
        "journal_templates/chinese/kxtbcas-numeric.bst",
    )
    for relative in required:
        assert (root / relative).is_file(), relative


def test_revision_semantics_contract_is_documented() -> None:
    style = (
        ROOT / "src" / "sci_manuscript" / "resources" / "revision_style.template.tex"
    ).read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    semantics = (ROOT / "references" / "revision_semantics.md").read_text(
        encoding="utf-8"
    )
    for token in (
        r"\definecolor{RevisionAddedColor}{RGB}{0,92,153}",
        r"\definecolor{RevisionDeletedColor}{RGB}{160,160,160}",
        r"\definecolor{RevisionReviewColor}{RGB}{220,45,45}",
        r"\CJKsout",
        r"\newcommand{\RevisionDeletionThickness}{0.8pt}",
    ):
        assert token in style
    assert r"\CJKunderwave" not in style
    assert r"\CJKunderline" not in style
    assert "blue text" in readme
    assert "red text" in readme
    assert "four-layer contract" in skill
    assert "similarity(old, new) >= 0.70" in semantics
    assert "max(len(old), len(new)) <= 2000" in semantics
    assert "--math-markup=FINE" in semantics
    assert "Rendering is mutually exclusive" in semantics


def test_no_legacy_public_architecture_strings() -> None:
    paths = [
        ROOT / "README.md",
        ROOT / "SKILL.md",
        *sorted((ROOT / "references").glob("*.md")),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "SCI_MANUSCRIPT_SKILL_ROOT" not in text
    assert "scripts/run.py" not in text
    assert "\\selfadd" not in text
    assert "manuscript.yaml" not in text


def test_manuscript_package_has_no_scripts_runtime_dependency() -> None:
    source = ROOT / "src" / "sci_manuscript"
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(source.glob("*.py"))
    )
    assert "sys.path.insert" not in text
    assert ' / "scripts"' not in text


def test_correspondence_templates_are_self_contained() -> None:
    resources = ROOT / "src" / "sci_manuscript" / "resources"
    templates = (
        resources / "correspondence_templates" / "cover_letter" / "cover_letter_en.tex",
        resources / "correspondence_templates" / "cover_letter" / "cover_letter_zh.tex",
        resources / "correspondence_templates" / "response" / "response_en.tex",
        resources / "correspondence_templates" / "response" / "response_zh.tex",
    )
    for template in templates:
        text = template.read_text(encoding="utf-8")
        assert "correspondence_style" not in text
        assert "shared_correspondence" not in text
        assert "\\documentclass" in text
    assert "%%COVER_BODY%%" in templates[0].read_text(encoding="utf-8")
    assert "%%RESPONSE_BODY%%" in templates[2].read_text(encoding="utf-8")
    assert not any((resources / "response").glob("*.tex"))
    assert not (resources / "submission" / "cover_letter_en.tex").exists()
    names = {path.name for path in resources.rglob("*.tex")}
    assert "correspondence_style.tex" not in names
    assert "shared_correspondence.tex" not in names


def test_workspace_owns_canonical_project_paths() -> None:
    forbidden = (
        'round_dir(round_number) / "output"',
        'round_dir(round_number) / "response"',
        'round_dir(round_number) / "submission"',
        'version.parent / "state"',
    )
    for path in sorted(SOURCE.glob("*.py")):
        if path.name == "workspace.py":
            continue
        text = path.read_text(encoding="utf-8")
        for expression in forbidden:
            assert expression not in text, f"{path.name}: {expression}"


def test_revision_state_and_template_invariants_are_not_duplicated() -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(SOURCE.glob("*.py"))
    )
    assert "First specific comment." not in source_text
    assert "# Reviewer #1\n## 1-1 | manuscript_revised" not in source_text
    assert '_REVISION_RUNTIME_TEMPLATE = r"""' not in source_text
    assert '_LOCATION_RUNTIME = r"""' not in source_text
    assert '_LOCATION_RUNTIME = rf"""' not in source_text


def test_current_docs_have_one_revision_rendering_contract() -> None:
    paths = (
        ROOT / "README.md",
        ROOT / "SKILL.md",
        ROOT / "CHANGELOG.md",
        ROOT / "references" / "revision_semantics.md",
        ROOT / "references" / "workflow.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    obsolete = (
        "math-markup=WHOLE",
        "whole-equation structural comparison",
        "green straight underline",
        "Deletions remain red strikeout",
        "blue wave underline",
    )
    for phrase in obsolete:
        assert phrase not in text
    assert "--math-markup=FINE" in text


def test_runtime_module_import_graph_has_no_cycles() -> None:
    modules = {path.stem for path in SOURCE.glob("*.py")}
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for path in SOURCE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                dependency = node.module.split(".", 1)[0]
                if dependency in modules:
                    graph[path.stem].add(dependency)

    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            cycle = " -> ".join((*active[active.index(module) :], module))
            raise AssertionError(f"runtime import cycle: {cycle}")
        if module in visited:
            return
        active.append(module)
        for dependency in graph[module]:
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in graph:
        visit(module)


def test_repository_tracks_no_ds_store() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert not any(
        Path(line).name == ".DS_Store" for line in result.stdout.splitlines()
    )
