"""Bilingual manuscript metadata and Chinese frontmatter contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject, cli
from sci_manuscript.authors import load_author_library, resolve_authors
from sci_manuscript.metadata import (
    ManuscriptMetadata,
    SubmissionSettings,
    generate_metadata,
    load_meta,
    render_publisher_metadata,
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
        funding=("国家自然科学基金项目（52500063）",),
        author_biographies=("zhao_guangyao", "liu_hong"),
    )


def test_workflow_meta_schema_loads_roles_and_frontmatter_selection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "meta.yaml"
    path.write_text(
        """revision:
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
  first: [zhao_guangyao]
  corresponding: [liu_hong]
  other: []
frontmatter:
  funding: [基金项目]
  author_biographies: [zhao_guangyao, liu_hong]
submission:
  cover_letter: false
  highlights: false
  graphical_abstract: false
correspondence: {}
""",
        encoding="utf-8",
    )

    metadata = load_meta(path)

    assert metadata.title == ""
    assert metadata.author_ids == ("zhao_guangyao", "liu_hong")
    assert metadata.first_authors == ("zhao_guangyao",)
    assert metadata.corresponding_authors == ("liu_hong",)
    assert metadata.funding == ("基金项目",)
    assert metadata.author_biographies == ("zhao_guangyao", "liu_hong")


def test_bilingual_metadata_and_author_bios_render_for_chinese_publisher() -> None:
    metadata = _bilingual_metadata()
    library = load_author_library(resources_root() / "authors.yaml")
    rendered = render_publisher_metadata(
        metadata,
        resolve_authors(metadata, library),
    )

    assert r"\title{" not in rendered
    assert r"\entitle{" not in rendered
    assert r"\cnabstract{" not in rendered
    assert r"\enabstract{" not in rendered
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
    text = text.replace("  funding:", "  # User funding note.\n  funding:", 1)
    path.write_text(text, encoding="utf-8")

    save_meta(path, _bilingual_metadata())

    updated = path.read_text(encoding="utf-8")
    assert "# User funding note." in updated
    assert "first:" in updated
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
    sections = round_dir / "sections"
    sections.mkdir()
    (sections / "00_frontmatter.tex").write_text(
        "\\title{源文件中的中文标题}\n\\entitle{English Source Title}\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "run"

    generate_metadata(round_dir, runtime)

    assert (runtime / "publisher_metadata.tex").is_file()
    author_metadata = (runtime / "author_metadata.tex").read_text(encoding="utf-8")
    assert r"\newcommand{\ManuscriptTitle}{源文件中的中文标题}" in author_metadata
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
    assert "\n  title:" not in meta.read_text(encoding="utf-8")
    assert "\n  abstract:" not in meta.read_text(encoding="utf-8")
    assert "first:" in meta.read_text(encoding="utf-8")
    assert "author_biographies:" in meta.read_text(encoding="utf-8")
    assert not (manuscript / "initial_submission" / "manuscript.tex").exists()
    assert not (manuscript / "references" / "authors.yaml").exists()
    assert "Please edit meta.yaml before build." in capsys.readouterr().out

    meta.write_text(
        """revision:
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
  first: [zhao_guangyao]
  corresponding: [liu_hong]
  other: []
frontmatter:
  funding: []
  author_biographies: [zhao_guangyao, liu_hong]
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
        del engine
        source = config.round_dir(round_number) / "manuscript.tex"
        assert source.is_file()
        build_dir = run_dir / "clean_build"
        build_dir.mkdir(parents=True)
        (build_dir / "manuscript.aux").write_text(
            "\\citation{replace_me}\n", encoding="utf-8"
        )
        output = config.output_dir(round_number) / "manuscript.pdf"
        output.write_bytes(b"pdf")
        return output

    monkeypatch.setattr("sci_manuscript.api.build_clean_manuscript", fake_build)
    monkeypatch.setattr(
        "sci_manuscript.api.write_build_manifest",
        lambda *_args, **_kwargs: tmp_path / "mock-build-manifest.yaml",
    )
    ManuscriptProject(manuscript).build()

    frontmatter = manuscript / "initial_submission" / "sections" / "00_frontmatter.tex"
    assert frontmatter.is_file()
    frontmatter_text = frontmatter.read_text(encoding="utf-8")
    assert r"\title{" in frontmatter_text
    assert r"\entitle{" in frontmatter_text
    assert r"\begin{abstract}" in frontmatter_text
    assert r"\begin{englishabstract}" in frontmatter_text
    assert r"\firstauthorcn" not in frontmatter_text
