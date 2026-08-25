"""User-editable Chinese frontmatter template contracts."""

from __future__ import annotations

from sci_manuscript.templates import resources_root


def test_chinese_frontmatter_template_owns_manuscript_text() -> None:
    path = (
        resources_root()
        / "manuscript"
        / "sections"
        / "default"
        / "00_frontmatter_zh.tex"
    )
    text = path.read_text(encoding="utf-8")

    assert r"\title{" in text
    assert r"\entitle{" in text
    assert r"\begin{abstract}" in text
    assert r"\end{abstract}" in text
    assert r"\begin{englishabstract}" in text
    assert r"\end{englishabstract}" in text
    assert r"\keywords{" in text
    assert r"\enkeywords{" in text


def test_chinese_frontmatter_template_excludes_generated_metadata() -> None:
    path = (
        resources_root()
        / "manuscript"
        / "sections"
        / "default"
        / "00_frontmatter_zh.tex"
    )
    text = path.read_text(encoding="utf-8")

    for command in (
        r"\funding{",
        r"\firstauthorcn{",
        r"\firstauthoren{",
        r"\corrauthorcn{",
        r"\corrauthoren{",
    ):
        assert command not in text


def test_english_frontmatter_template_owns_all_scientific_frontmatter() -> None:
    template = (
        resources_root()
        / "manuscript"
        / "sections"
        / "default"
        / "00_frontmatter_en.tex"
    ).read_text(encoding="utf-8")
    assert r"\title{" in template
    assert r"\newcommand{\ManuscriptAbstractText}" in template
    assert r"\newcommand{\ManuscriptKeywordsText}" in template
