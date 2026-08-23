"""Regression tests for marked-manuscript line decoration semantics."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "src" / "sci_manuscript" / "resources" / "revision_style.tex"


def test_chinese_revision_marks_include_cjk_punctuation() -> None:
    """Starred xeCJKfntef forms must decorate punctuation instead of skipping it."""
    style = STYLE.read_text(encoding="utf-8")
    assert r"\CJKunderwave*[" in style
    assert r"\CJKsout*[" in style
    assert r"\CJKunderline*[" in style
