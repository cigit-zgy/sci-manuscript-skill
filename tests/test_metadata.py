"""Workflow metadata and author-biography selection contracts."""

# ruff: noqa: RUF001

from __future__ import annotations

from pathlib import Path

from sci_manuscript.metadata import (
    ManuscriptMetadata,
    SubmissionSettings,
    load_author_library,
    load_meta,
    render_publisher_metadata,
    resolve_authors,
    save_meta,
)
from sci_manuscript.templates import resources_root


def _write_meta(path: Path, authors: str) -> None:
    path.write_text(
        f"""revision:
  round: r00
  name: initial_submission
  parent:
manuscript:
  language: zh
  article_type: 观点
journal:
  name: 科学通报
  publisher: chinese
authors:
{authors}
frontmatter:
  funding:
    - 国家自然科学基金项目（52500063）
    - 重庆市自然科学基金项目
  author_biographies:
    - zhao_guangyao
    - liu_hong
submission:
  cover_letter: false
  highlights: false
  graphical_abstract: false
correspondence: {{}}
""",
        encoding="utf-8",
    )


def test_canonical_meta_contains_workflow_fields_without_manuscript_text(
    tmp_path: Path,
) -> None:
    path = tmp_path / "meta.yaml"
    _write_meta(
        path,
        "  first: [zhao_guangyao, yin_fengjun]\n"
        "  corresponding: [zhao_guangyao, liu_hong]\n"
        "  other: [wu_di, song_cheng]",
    )

    metadata = load_meta(path)

    assert metadata.first_authors == ("zhao_guangyao", "yin_fengjun")
    assert metadata.corresponding_authors == ("zhao_guangyao", "liu_hong")
    assert metadata.other_authors == ("wu_di", "song_cheng")
    assert metadata.author_ids == (
        "zhao_guangyao",
        "yin_fengjun",
        "wu_di",
        "song_cheng",
        "liu_hong",
    )
    assert metadata.funding == (
        "国家自然科学基金项目（52500063）",
        "重庆市自然科学基金项目",
    )
    assert metadata.author_biographies == ("zhao_guangyao", "liu_hong")

    saved = tmp_path / "saved.yaml"
    save_meta(saved, metadata)
    text = saved.read_text(encoding="utf-8")
    assert "  title:" not in text
    assert "  abstract:" not in text
    assert "  keywords:" not in text
    assert "  first:" in text
    assert "  other:" in text
    assert "  order:" not in text


def test_released_order_schema_remains_readable(tmp_path: Path) -> None:
    path = tmp_path / "legacy.yaml"
    _write_meta(
        path,
        "  order: [zhao_guangyao, yin_fengjun, liu_hong]\n  corresponding: [liu_hong]",
    )

    metadata = load_meta(path)

    assert metadata.author_ids == (
        "zhao_guangyao",
        "yin_fengjun",
        "liu_hong",
    )
    assert metadata.first_authors == ("zhao_guangyao",)
    assert metadata.corresponding_authors == ("liu_hong",)
    assert metadata.other_authors == ("yin_fengjun",)


def test_funding_and_selected_multiple_author_biographies_render() -> None:
    metadata = ManuscriptMetadata(
        title="",
        article_type="观点",
        language="zh",
        journal_name="科学通报",
        publisher="chinese",
        round_number=0,
        parent_round=None,
        first_authors=("zhao_guangyao",),
        corresponding_authors=("zhao_guangyao", "liu_hong"),
        other_authors=(),
        submission=SubmissionSettings(False, False, False),
        funding=("国家自然科学基金项目（52500063）",),
        author_biographies=("zhao_guangyao", "liu_hong"),
    )
    library = load_author_library(resources_root() / "authors.yaml")

    rendered = render_publisher_metadata(
        metadata,
        resolve_authors(metadata, library),
    )

    assert r"\funding{国家自然科学基金项目（52500063）}" in rendered
    assert "赵光耀（1991--）" in rendered
    assert "Guangyao Zhao (1991--)" in rendered
    assert "刘鸿（1970--）" in rendered
    assert "Hong Liu (1970--)" in rendered
    assert r"\title{" not in rendered
    assert r"\entitle{" not in rendered
    assert r"\cnabstract{" not in rendered
    assert r"\enabstract{" not in rendered
