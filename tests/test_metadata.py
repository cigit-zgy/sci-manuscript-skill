"""Workflow metadata and author-biography selection contracts."""

# ruff: noqa: RUF001

from __future__ import annotations

from pathlib import Path

import pytest
from sci_manuscript.authors import load_author_library, resolve_authors
from sci_manuscript.metadata import (
    ManuscriptMetadata,
    MetadataError,
    SubmissionSettings,
    load_meta,
    render_publisher_metadata,
    save_meta,
)
from sci_manuscript.templates import resources_root


def _obsolete_role_schema() -> str:
    first = "_".join(("first", "author"))
    corresponding = "_".join(("corresponding", "author"))
    other = "_".join(("other", "author"))
    return (
        f"  {first}: [zhao_guangyao]\n"
        f"  {corresponding}: [liu_hong]\n"
        f"  {other}: [yin_fengjun]"
    )


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
  publisher: kxtbcas
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


@pytest.mark.parametrize("field", ("title", "abstract", "keywords"))
def test_manuscript_scientific_frontmatter_fields_are_rejected(
    tmp_path: Path,
    field: str,
) -> None:
    path = tmp_path / "obsolete-frontmatter.yaml"
    _write_meta(
        path,
        "  first: [zhao_guangyao]\n  corresponding: [liu_hong]\n  other: []",
    )
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "  article_type: 观点\n", f"  article_type: 观点\n  {field}: 旧字段\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(MetadataError, match="Unsupported manuscript keys"):
        load_meta(path)


@pytest.mark.parametrize(
    ("publisher", "language"),
    (
        ("chinese", "en"),
        ("elsevier", "zh"),
        ("nature", "zh"),
        ("acs", "zh"),
    ),
)
def test_publisher_language_matrix_is_explicit(
    tmp_path: Path,
    publisher: str,
    language: str,
) -> None:
    path = tmp_path / "unsupported-combination.yaml"
    _write_meta(
        path,
        "  first: [zhao_guangyao]\n  corresponding: [liu_hong]\n  other: []",
    )
    text = path.read_text(encoding="utf-8")
    text = text.replace("  language: zh", f"  language: {language}")
    text = text.replace("  publisher: kxtbcas", f"  publisher: {publisher}")
    path.write_text(text, encoding="utf-8")

    with pytest.raises(MetadataError, match=r"accepted language"):
        load_meta(path)


def test_custom_publisher_is_a_canonical_option(tmp_path: Path) -> None:
    path = tmp_path / "custom-publisher.yaml"
    _write_meta(
        path,
        "  first: [zhao_guangyao]\n  corresponding: [liu_hong]\n  other: []",
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "  publisher: kxtbcas", "  publisher: custom"
        ),
        encoding="utf-8",
    )

    assert load_meta(path).publisher == "custom"


@pytest.mark.parametrize(
    "authors",
    (
        "  order: [zhao_guangyao, yin_fengjun, liu_hong]\n  corresponding: [liu_hong]",
        _obsolete_role_schema(),
    ),
)
def test_noncanonical_authors_schemas_are_rejected(
    tmp_path: Path,
    authors: str,
) -> None:
    path = tmp_path / "obsolete.yaml"
    _write_meta(path, authors)

    with pytest.raises(MetadataError, match=r"Canonical authors schema|Detected a v1"):
        load_meta(path)


@pytest.mark.parametrize(
    "authors",
    (
        "  first: zhao_guangyao\n  corresponding: [liu_hong]\n  other: [yin_fengjun]",
        "  first: [zhao_guangyao]\n  corresponding: liu_hong\n  other: [yin_fengjun]",
        "  first: [zhao_guangyao]\n  corresponding: [liu_hong]\n  other: yin_fengjun",
    ),
)
def test_author_roles_must_be_lists(tmp_path: Path, authors: str) -> None:
    path = tmp_path / "scalar.yaml"
    _write_meta(path, authors)

    with pytest.raises(MetadataError, match=r"must be .*list"):
        load_meta(path)


def test_funding_and_selected_multiple_author_biographies_render() -> None:
    metadata = ManuscriptMetadata(
        title="",
        article_type="观点",
        language="zh",
        journal_name="科学通报",
        publisher="kxtbcas",
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


def test_biography_selection_rejects_other_only_author(tmp_path: Path) -> None:
    path = tmp_path / "other-biography.yaml"
    _write_meta(
        path,
        "  first: [zhao_guangyao]\n  corresponding: [liu_hong]\n  other: [song_cheng]",
    )
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "    - zhao_guangyao\n    - liu_hong",
            "    - song_cheng",
        ),
        encoding="utf-8",
    )

    with pytest.raises(MetadataError, match="first or corresponding authors"):
        load_meta(path)
