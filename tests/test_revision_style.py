"""Regression tests for marked-manuscript line decoration semantics."""

from __future__ import annotations

from pathlib import Path

from sci_manuscript.diff import REVISION_RUNTIME


ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "src" / "sci_manuscript" / "resources" / "revision" / "style.tex"


def test_chinese_deletion_marks_include_cjk_punctuation() -> None:
    """Only deletion retains a punctuation-continuous CJK line decoration."""
    style = STYLE.read_text(encoding="utf-8")
    assert r"\CJKsout*[" in style
    assert r"\CJKunderwave" not in style
    assert r"\CJKunderline" not in style


def test_revision_colors_and_deletion_weight_contract() -> None:
    style = STYLE.read_text(encoding="utf-8")
    assert r"\newcommand{\RevisionDeletionThickness}{0.8pt}" in style
    assert style.count(r"\RevisionDeletionThickness") == 3
    assert r"\RevisionRuleThickness" not in style
    assert r"\RevisionWaveSymbol" not in style
    assert r"\definecolor{RevisionAddedColor}{RGB}{0,92,153}" in style
    assert r"\definecolor{RevisionReviewColor}{RGB}{220,45,45}" in style
    assert r"\definecolor{RevisionDeletedColor}{RGB}{160,160,160}" in style


def test_math_revision_runtime_uses_color_only_additions_and_struck_deletions() -> None:
    assert r"\RevisionAddedFont\color{RevisionAddedColor}#1" in REVISION_RUNTIME
    assert r"\RevisionReviewFont\color{RevisionReviewColor}#1" in REVISION_RUNTIME
    assert r"\RevisionMathStrikeout{RevisionDeletedColor}{#1}" in REVISION_RUNTIME
    assert r"\RevisionDeletionThickness" in REVISION_RUNTIME
    assert r"\RevisionMathWave" not in REVISION_RUNTIME
    assert r"\RevisionMathUnderline" not in REVISION_RUNTIME
    assert r"\RevisionAddedUnderline" not in REVISION_RUNTIME
    assert r"\RevisionReviewUnderline" not in REVISION_RUNTIME
