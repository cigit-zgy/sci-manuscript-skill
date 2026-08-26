"""Regression tests for marked-manuscript line decoration semantics."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

from sci_manuscript import compile as manuscript_compile
from sci_manuscript import workspace
from sci_manuscript.diff import REVISION_RUNTIME, _validate_reference_style_contract
from sci_manuscript.errors import WorkflowError


ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "src" / "sci_manuscript" / "resources" / "revision_style.template.tex"
COMMON = (
    ROOT / "src" / "sci_manuscript" / "resources" / "manuscript_preamble" / "common.tex"
)
LOCATION_RUNTIME = (
    ROOT / "src" / "sci_manuscript" / "resources" / "revision" / "location_runtime.tex"
)


def test_revision_style_has_no_deletion_contract() -> None:
    style = STYLE.read_text(encoding="utf-8")
    assert "RevisionDeleted" not in style
    assert "CJKsout" not in style
    assert "sout" not in style


def test_reviewer_color_uses_dvips_named_rubine_red() -> None:
    common = COMMON.read_text(encoding="utf-8")
    assert r"\newcommand{\RevisionReviewerColor}{RubineRed}" in common
    assert "definecolor{SciRevisionReviewer" not in common


def test_author_color_uses_dvips_named_forest_green() -> None:
    common = COMMON.read_text(encoding="utf-8")
    assert "ForestGreen" in REVISION_RUNTIME
    assert "definecolor{SciRevisionAuthor" not in common


def test_reference_link_color_uses_canonical_rgb_blue() -> None:
    common = COMMON.read_text(encoding="utf-8")
    assert r"\definecolor{SciLinkBlue}{RGB}{0,0,255}" in common
    assert "citecolor=SciLinkBlue" in common
    assert "urlcolor=SciLinkBlue" in common
    assert "ProcessBlue" not in common


def test_staged_manuscript_enables_dvipsnames_before_documentclass() -> None:
    source = "% comment\n\\documentclass{article}\n\\begin{document}\n"
    staged = manuscript_compile.enable_dvips_named_colors(source)
    assert staged.startswith(
        "% comment\n\\PassOptionsToPackage{dvipsnames}{xcolor}\n"
        "\\documentclass{article}"
    )
    assert manuscript_compile.enable_dvips_named_colors(staged) == staged


def test_dvips_named_colors_compile_with_tectonic(tmp_path: Path) -> None:
    tectonic = shutil.which("tectonic")
    if tectonic is None:
        pytest.skip("tectonic is not installed")
    source = tmp_path / "named-colors.tex"
    source.write_text(
        r"""\PassOptionsToPackage{dvipsnames}{xcolor}
\documentclass{article}
\usepackage{xcolor}
\definecolor{SciLinkBlue}{RGB}{0,0,255}
\begin{document}
\textcolor{RubineRed}{Reviewer}
\textcolor{ForestGreen}{Author}
\textcolor{SciLinkBlue}{Citation}
\end{document}
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [tectonic, "-X", "compile", str(source)],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert source.with_suffix(".pdf").is_file()


def test_formal_color_contract_has_no_xcolor_mixes() -> None:
    formal = (
        COMMON.read_text(encoding="utf-8")
        + STYLE.read_text(encoding="utf-8")
        + REVISION_RUNTIME
    )
    for name in ("red", "green", "blue"):
        assert f"{name}!" not in formal


def test_project_style_cannot_redefine_semantic_colors() -> None:
    style = STYLE.read_text(encoding="utf-8")
    assert "definecolor{SciRevision" not in style
    assert "definecolor{SciLinkBlue" not in style
    assert "RevisionAddedColor" not in style
    assert "RevisionReviewColor" not in style


def test_runtime_uses_addition_only_color() -> None:
    assert r"\RevisionAddedFont\color{ForestGreen}#1" in REVISION_RUNTIME
    assert r"\RevisionReviewFont\color{\RevisionReviewerColor}#1" in REVISION_RUNTIME
    assert r"\begingroup\color{ForestGreen}" in REVISION_RUNTIME
    assert r"\begingroup\color{\RevisionReviewerColor}" in REVISION_RUNTIME
    assert r"\DIFdel" not in REVISION_RUNTIME
    assert "RevisionDeleted" not in REVISION_RUNTIME


def test_runtime_keeps_every_citation_link_blue_without_ownership_colors() -> None:
    assert r"\SCISetCitationColor{SciLinkBlue}\color{SciLinkBlue}#1" in REVISION_RUNTIME
    assert "ProcessBlue" not in REVISION_RUNTIME
    assert r"\SCIAuthorCitation" not in REVISION_RUNTIME
    assert r"\SCIReviewCitation" not in REVISION_RUNTIME


def test_clean_contract_sets_citation_and_url_blue_without_internal_link_override() -> (
    None
):
    common = COMMON.read_text(encoding="utf-8")
    assert "citecolor=SciLinkBlue" in common
    assert "urlcolor=SciLinkBlue" in common
    assert "linkcolor=" not in common


def test_marked_runtime_has_no_citation_or_url_black_override() -> None:
    assert "citecolor=black" not in REVISION_RUNTIME
    assert "urlcolor=black" not in REVISION_RUNTIME
    assert "SCIReferenceBlack" not in REVISION_RUNTIME


def test_location_runtime_preserves_visual_style_and_only_emits_line_labels() -> None:
    location = LOCATION_RUNTIME.read_text(encoding="utf-8")
    assert r"\DeclareRobustCommand{\SciReviewLineStart}[1]{\linelabel{#1}}" in location
    assert r"\DeclareRobustCommand{\SciReviewLineEnd}[1]{\linelabel{#1}}" in location
    assert r"\SCISetCitationColor" not in location
    assert r"\SCIReferenceLink" not in location
    assert r"\color" not in location
    assert "ReviewLocationColor" not in location


def test_clean_marked_reference_style_validator_passes() -> None:
    _validate_reference_style_contract()


def _legacy_style(*, custom_color: str = "0,92,153", extra: str = "") -> str:
    return rf"""% Marked-manuscript semantic contract:
%   ordinary latexdiff addition = blue text
%   deletion                    = light-gray strikeout
% Deleted text
% Deleted text color.
\definecolor{{RevisionAddedColor}}{{RGB}}{{{custom_color}}}
\definecolor{{RevisionDeletedColor}}{{RGB}}{{160,160,160}}
\newcommand{{\RevisionDeletionThickness}}{{0.8pt}}
\newcommand{{\RevisionDeletedStrikeout}}[1]{{\sout{{#1}}}}
\definecolor{{RevisionReviewColor}}{{RGB}}{{220,45,45}}
\newcommand{{\RevisionAddedBackground}}[1]{{#1}}
\newcommand{{\RevisionDeletedBackground}}[1]{{#1}}
\newcommand{{\RevisionReviewBackground}}[1]{{#1}}
\newcommand{{\RevisionAddedFont}}{{}}
\newcommand{{\RevisionDeletedFont}}{{}}
\newcommand{{\RevisionReviewFont}}{{}}
{extra}"""


def test_old_revision_style_is_archived_and_safely_migrated(tmp_path: Path) -> None:
    style = tmp_path / "references" / "revision_style.tex"
    style.parent.mkdir()
    old = _legacy_style()
    style.write_text(old, encoding="utf-8")

    archive = workspace.migrate_revision_style_file(style, tmp_path / "00_archive")

    migrated = style.read_text(encoding="utf-8")
    assert archive is not None
    digest = hashlib.sha256(old.encode("utf-8")).hexdigest()[:12]
    assert archive == (
        tmp_path
        / "00_archive"
        / f"resource_migration_{digest}"
        / "references"
        / "revision_style.tex"
    )
    assert archive.read_text(encoding="utf-8") == old
    assert "RevisionAddedColor" not in migrated
    assert "RevisionDeleted" not in migrated
    assert "RevisionReviewColor" not in migrated
    assert "deletion" not in migrated.lower()
    assert r"\RevisionAddedBackground" in migrated
    assert r"\RevisionReviewFont" in migrated


def test_revision_style_migration_preserves_unrelated_user_edit(tmp_path: Path) -> None:
    style = tmp_path / "revision_style.tex"
    style.write_text(
        _legacy_style(extra=r"\newcommand{\UserFontChoice}{\sffamily}"),
        encoding="utf-8",
    )

    workspace.migrate_revision_style_file(style, tmp_path / "00_archive")

    assert r"\newcommand{\UserFontChoice}{\sffamily}" in style.read_text(
        encoding="utf-8"
    )


def test_current_revision_style_migration_is_noop(tmp_path: Path) -> None:
    style = tmp_path / "revision_style.tex"
    current = STYLE.read_text(encoding="utf-8")
    style.write_text(current, encoding="utf-8")

    assert workspace.migrate_revision_style_file(style, tmp_path / "00_archive") is None
    assert style.read_text(encoding="utf-8") == current
    assert not (tmp_path / "00_archive").exists()


def test_customized_legacy_revision_colors_stop_with_actionable_error(
    tmp_path: Path,
) -> None:
    style = tmp_path / "revision_style.tex"
    style.write_text(_legacy_style(custom_color="12,34,56"), encoding="utf-8")

    with pytest.raises(WorkflowError, match="REVISION_STYLE_MIGRATION_UNSUPPORTED"):
        workspace.migrate_revision_style_file(style, tmp_path / "00_archive")

    assert style.read_text(encoding="utf-8") == _legacy_style(custom_color="12,34,56")
    assert not (tmp_path / "00_archive").exists()
