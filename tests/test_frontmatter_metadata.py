"""Bilingual manuscript metadata and Chinese frontmatter contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject, cli
from sci_manuscript.metadata import (
    ManuscriptMetadata,
    SubmissionSettings,
    generate_metadata,
    load_author_library,
    load_meta,
    render_publisher_metadata,
    resolve_authors,
    save_meta,
)
from sci_manuscript.templates import resources_root
from sci_manuscript.workspace import ProjectConfig


def _bilingual_metadata() -> ManuscriptMetadata:
    return ManuscriptMetadata(
        title="面向智能体操作的结构化对象层",
        article_type="观点",
        language="zh",
        journal_name="科学通报",
        publisher="chinese",
        round_number=0,
        parent_round=None,
        first_authors=("zhao_guangyao",),
        corresponding_authors=("liu_hong",),
        other_authors=(),
        submission=SubmissionSettings(False, False, False),
        author_order=("zhao_guangyao", "liu_hong"),
        title_zh="面向智能体操作的结构化对象层",
        title_en="A structured object layer for AI-agent operation",
        abstract_zh="中文摘要。",
        abstract_en="English abstract.",
        keywords_zh="污水处理；智能体",
        keywords_en="wastewater treatment; AI agent",
        funding="国家自然科学基金项目（52500063）",
    )


def test_new_bilingual_meta_schema_loads_order_and_corresponding(
    tmp_path: Path,
) -> None:
    path = tmp_path / "meta.yaml"
    path.write_text(
        """revision:
  round: r00
  name: initial_submission
  parent:
manuscript:
  title:
    zh: 中文标题
    en: English title
  abstract:
    zh: 中文摘要。
    en: English abstract.
  keywords:
    zh: 关键词一；关键词二
    en: keyword one; keyword two
  funding: 基金项目
  language: zh
  article_type: 观点
journal:
  name: 科学通报
  publisher: chinese
authors:
  order: [zhao_guangyao, liu_hong]
  corresponding: [liu_hong]
submission:
  cover_letter: false
  highlights: false
  graphical_abstract: false
correspondence: {}
""",
        encoding="utf-8",
    )

    metadata = load_meta(path)

    assert metadata.title == "中文标题"
    assert metadata.title_zh == "中文标题"
    assert metadata.title_en == "English title"
    assert metadata.abstract_zh == "中文摘要。"
    assert metadata.abstract_en == "English abstract."
    assert metadata.author_ids == ("zhao_guangyao", "liu_hong")
    assert metadata.first_authors == ("zhao_guangyao",)
    assert metadata.corresponding_authors == ("liu_hong",)


def test_bilingual_metadata_and_author_bios_render_for_chinese_publisher() -> None:
    metadata = _bilingual_metadata()
    library = load_author_library(resources_root() / "authors.yaml")
    rendered = render_publisher_metadata(
        metadata,
        resolve_authors(metadata, library),
    )

    assert r"\title{面向智能体操作的结构化对象层}" in rendered
    assert r"\entitle{A structured object layer for AI-agent operation}" in rendered
    assert r"\cnabstract{中文摘要。}" in rendered
    assert r"\enabstract{English abstract.}" in rendered
    assert r"\cnkeywords{污水处理；智能体}" in rendered
    assert r"\enkeywords{wastewater treatment; AI agent}" in rendered
    assert r"\funding{国家自然科学基金项目（52500063）}" in rendered
    assert (
        r"\firstauthorcn{赵光耀（1991--），男，博士，助理研究员，"
        r"主要研究方向为污水处理模型，zhaoguangyao@cigit.ac.cn}"
    ) in rendered
    assert (
        r"\corrauthoren{Hong Liu (1970--), PhD, Professor, specializing in water "
        r"pollution control and intelligent wastewater treatment, "
        r"liuhong@cigit.ac.cn}"
    ) in rendered


def test_save_meta_preserves_comments_with_bilingual_schema(tmp_path: Path) -> None:
    path = tmp_path / "meta.yaml"
    save_meta(path, _bilingual_metadata())
    text = path.read_text(encoding="utf-8")
    text = text.replace("    en:", "    # User English-title note.\n    en:", 1)
    path.write_text(text, encoding="utf-8")

    save_meta(path, _bilingual_metadata())

    updated = path.read_text(encoding="utf-8")
    assert "# User English-title note." in updated
    assert "order:" in updated
    assert "corresponding:" in updated


def test_publisher_metadata_is_generated_only_in_runtime_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manuscript"
    round_dir = root / "initial_submission"
    references = root / "references"
    round_dir.mkdir(parents=True)
    references.mkdir()
    save_meta(round_dir / "meta.yaml", _bilingual_metadata())
    (references / "authors.yaml").write_bytes(
        (resources_root() / "authors.yaml").read_bytes()
    )
    runtime = tmp_path / "run"

    generate_metadata(root, round_dir, runtime)

    assert (runtime / "publisher_metadata.tex").is_file()
    assert not (round_dir / "publisher_metadata.tex").exists()


def test_minimal_init_creates_annotated_draft_without_compiling(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "draft project"

    assert cli.main(["init", "--project", str(project)]) == 0

    manuscript = project / "manuscript"
    meta = manuscript / "initial_submission" / "meta.yaml"
    assert meta.is_file()
    assert "title:" in meta.read_text(encoding="utf-8")
    assert "abstract:" in meta.read_text(encoding="utf-8")
    assert "order:" in meta.read_text(encoding="utf-8")
    assert not (manuscript / "initial_submission" / "manuscript.tex").exists()
    assert not (manuscript / "references" / "authors.yaml").exists()
    assert "Please edit meta.yaml before build." in capsys.readouterr().out

    meta.write_text(
        """revision:
  round: r00
  name: initial_submission
  parent:
manuscript:
  title:
    zh: 中文标题
    en: English title
  abstract:
    zh: 中文摘要。
    en: English abstract.
  keywords:
    zh: 关键词
    en: keyword
  funding:
  language: zh
  article_type: 观点
journal:
  name: 科学通报
  publisher: chinese
authors:
  order: [zhao_guangyao, liu_hong]
  corresponding: [liu_hong]
submission:
  cover_letter: false
  highlights: false
  graphical_abstract: false
correspondence: {}
""",
        encoding="utf-8",
    )

    def fake_build(
        config: ProjectConfig,
        round_number: int,
        run_dir: Path,
        engine: str | None,
    ) -> Path:
        del run_dir, engine
        source = config.round_dir(round_number) / "manuscript.tex"
        assert source.is_file()
        output = config.output_dir(round_number) / "manuscript.pdf"
        output.write_bytes(b"pdf")
        return output

    monkeypatch.setattr("sci_manuscript.api.build_clean_manuscript", fake_build)
    ManuscriptProject(manuscript).build()

    frontmatter = manuscript / "initial_submission" / "sections" / "00_frontmatter.tex"
    assert frontmatter.is_file()
    assert not any(
        command in frontmatter.read_text(encoding="utf-8")
        for command in (r"\entitle", r"\cnabstract", r"\firstauthorcn")
    )
