"""Global and explicit author-library behavior tests."""

# ruff: noqa: RUF001 -- exact Chinese correspondence-address fixtures.

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pytest

from sci_manuscript import cli
from sci_manuscript.authors import (
    CONFIG_DIRECTORY_ENV,
    AuthorRecord,
    AuthorSelection,
    configure_author_library,
    configured_author_library_path,
    load_author_library,
    resolve_author_library_path,
    resolve_authors,
    resolve_signing_author,
)
from sci_manuscript.cli import main
from sci_manuscript.errors import ManuscriptError
from sci_manuscript.metadata import (
    CorrespondenceSettings,
    ManuscriptMetadata,
    MetadataError,
    SubmissionSettings,
    render_author_metadata,
)
from sci_manuscript.workspace import ProjectConfig, initialize_project


def _library(path: Path, *, author_id: str = "author_one") -> Path:
    path.write_text(
        f"""affiliations:
  institute:
    name_en: Anonymous Institute
    address: Example City
authors:
  {author_id}:
    name_en: Anonymous One
    name_zh: 匿名甲
    email: one@example.invalid
    affiliations: [institute]
  author_two:
    name_en: Anonymous Two
    name_zh: 匿名乙
    affiliations: [institute]
""",
        encoding="utf-8",
    )
    return path


def _metadata(*, other: tuple[str, ...] = ("author_two",)) -> ManuscriptMetadata:
    return ManuscriptMetadata(
        title="Author Test",
        article_type="Research Article",
        language="en",
        journal_name="Example Journal",
        publisher="elsevier",
        round_number=0,
        parent_round=None,
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        other_authors=other,
        submission=SubmissionSettings(),
    )


def _multi_library(path: Path) -> Path:
    path.write_text(
        """affiliations:
  first:
    name_en: First Institute, City 100001, Country
    name_zh: 第一研究院，城市 100001
  second:
    name_en: Second Institute, City 100002, Country
    name_zh: 第二研究院，城市 100002
authors:
  author_one:
    name_en: Author One
    name_zh: 作者甲
    email: one@example.invalid
    affiliations: [first, second]
  author_two:
    name_en: Author Two
    name_zh: 作者乙
    email: two@example.invalid
    correspondence_address: Explicit Address, City 200002
    affiliations: [second]
  author_three:
    name_en: Author Three
    name_zh: 作者丙
    email: three@example.invalid
    affiliations: [first]
  non_corresponding:
    name_en: Other Author
    name_zh: 其他作者
    affiliations: [second]
""",
        encoding="utf-8",
    )
    return path


def _multi_metadata(count: int) -> ManuscriptMetadata:
    corresponding = ("author_three", "author_one", "author_two")[:count]
    return replace(
        _metadata(),
        first_authors=("author_one",),
        other_authors=("non_corresponding", "author_two", "author_three"),
        corresponding_authors=corresponding,
    )


def test_email_is_optional_but_corresponding_email_is_required(tmp_path: Path) -> None:
    library = load_author_library(_library(tmp_path / "authors.yaml"))
    selection = resolve_authors(_metadata(), library)
    assert selection.authors[1].email == ""
    invalid = replace(
        _metadata(),
        first_authors=("author_two",),
        corresponding_authors=("author_two",),
        other_authors=(),
    )
    with pytest.raises(MetadataError) as error:
        resolve_authors(invalid, library)
    message = str(error.value)
    assert 'Missing email for corresponding author "Anonymous Two".' in message
    assert f"Source: author metadata ({library.source})." in message
    assert "Missing field: email." in message


@pytest.mark.parametrize("count", (1, 2, 3))
def test_response_correspondence_supports_one_to_three_authors(
    tmp_path: Path, count: int
) -> None:
    library = load_author_library(_multi_library(tmp_path / "authors.yaml"))
    metadata = _multi_metadata(count)
    selection = resolve_authors(metadata, library)
    rendered = render_author_metadata(metadata, selection)

    expected_ids = tuple(
        author.author_id
        for author in selection.authors
        if author.author_id in set(metadata.corresponding_authors)
    )
    assert tuple(author.author_id for author in selection.corresponding_authors) == (
        expected_ids
    )
    assert rendered.count(r"\vspace{0.55\baselineskip}") == 2 * (count - 1)
    assert rendered.count(r"\vspace{0.25\baselineskip}") == 2 * count * 2


def test_corresponding_authors_follow_manuscript_order_and_skip_other_authors(
    tmp_path: Path,
) -> None:
    library = load_author_library(_multi_library(tmp_path / "authors.yaml"))
    metadata = _multi_metadata(3)
    selection = resolve_authors(metadata, library)

    assert tuple(author.author_id for author in selection.authors) == (
        "author_one",
        "non_corresponding",
        "author_two",
        "author_three",
    )
    assert tuple(author.author_id for author in selection.corresponding_authors) == (
        "author_one",
        "author_two",
        "author_three",
    )


def test_response_correspondence_uses_explicit_address_then_first_affiliation(
    tmp_path: Path,
) -> None:
    library = load_author_library(_multi_library(tmp_path / "authors.yaml"))
    metadata = _multi_metadata(3)
    rendered = render_author_metadata(metadata, resolve_authors(metadata, library))
    zh = rendered.split(r"\newcommand{\CorrespondenceAuthorsZh}{%", 1)[1].split(
        "\n}", 1
    )[0]
    en = rendered.split(r"\newcommand{\CorrespondenceAuthorsEn}{%", 1)[1].split(
        "\n}", 1
    )[0]

    assert "作者甲" in zh
    assert "通讯地址：第一研究院，城市 100001" in zh
    assert "作者乙" in zh
    assert "通讯地址：Explicit Address, City 200002" in zh
    assert "Correspondence address: First Institute, City 100001, Country" in en
    assert "Correspondence address: Explicit Address, City 200002" in en
    assert (
        "Second Institute" not in en.split("Author One", 1)[1].split("Author Two", 1)[0]
    )


def test_response_correspondence_renders_locale_labels_and_no_final_gap(
    tmp_path: Path,
) -> None:
    library = load_author_library(_multi_library(tmp_path / "authors.yaml"))
    metadata = _multi_metadata(3)
    rendered = render_author_metadata(metadata, resolve_authors(metadata, library))
    zh = rendered.split(r"\newcommand{\CorrespondenceAuthorsZh}{%", 1)[1].split(
        "\n}", 1
    )[0]
    en = rendered.split(r"\newcommand{\CorrespondenceAuthorsEn}{%", 1)[1].split(
        "\n}", 1
    )[0]

    assert zh.count("通讯地址：") == 3
    assert zh.count("邮箱：") == 3
    assert en.count("Correspondence address: ") == 3
    assert en.count("E-mail: ") == 3
    assert zh.rstrip().endswith("three@example.invalid}")
    assert en.rstrip().endswith("three@example.invalid}")


def test_missing_correspondence_address_is_actionable() -> None:
    author = AuthorRecord(
        "missing_address",
        "缺地址作者",
        "Missing Address",
        "missing@example.invalid",
        (),
    )
    selection = AuthorSelection((author,), (), (author,), (author,), {})

    with pytest.raises(
        MetadataError,
        match='Missing correspondence address for corresponding author "Missing Address"',
    ):
        render_author_metadata(_metadata(other=()), selection)


def test_unknown_affiliation_and_selected_author_are_rejected(tmp_path: Path) -> None:
    path = _library(tmp_path / "authors.yaml")
    path.write_text(path.read_text().replace("[institute]", "[missing]", 1))
    with pytest.raises(MetadataError, match="missing affiliations"):
        load_author_library(path)
    library = load_author_library(_library(path))
    with pytest.raises(MetadataError, match="missing"):
        resolve_authors(_metadata(other=("unknown_author",)), library)


def test_duplicate_author_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        """affiliations:
  institute:
    name_en: Anonymous Institute
authors:
  duplicate:
    name_en: First
    name_zh: 甲
    affiliations: [institute]
  duplicate:
    name_en: Second
    name_zh: 乙
    affiliations: [institute]
""",
        encoding="utf-8",
    )
    with pytest.raises(MetadataError, match="duplicate key"):
        load_author_library(path)


def test_global_library_is_configured_without_project_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config"
    monkeypatch.setenv(CONFIG_DIRECTORY_ENV, str(config))
    source = _library(tmp_path / "authors.yaml")
    installed = configure_author_library(source)
    assert installed == config / "authors.yaml"
    assert resolve_author_library_path() == installed
    manuscript = tmp_path / "project" / "manuscript"
    initialized = initialize_project(
        ProjectConfig(manuscript, _metadata()),
    )
    assert not (initialized.references / "authors.yaml").exists()
    assert resolve_authors(
        _metadata(), load_author_library(resolve_author_library_path())
    ).authors


def test_init_cli_has_no_explicit_author_library_option() -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(
            ["init", "--project", "/tmp/example", "--authors", "/tmp/authors.yaml"]
        )


def test_bundled_public_library_is_the_final_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(CONFIG_DIRECTORY_ENV, str(tmp_path / "empty-config"))
    assert not configured_author_library_path().exists()
    bundled = resolve_author_library_path()
    library = load_author_library(bundled)
    assert tuple(library.authors) == (
        "zhao_guangyao",
        "yin_fengjun",
        "wu_di",
        "song_cheng",
        "liu_hong",
    )
    assert library.authors["song_cheng"].email == "songcheng@cigit.ac.cn"
    assert library.authors["zhao_guangyao"].bio_zh == (
        "赵光耀（1991--），男，博士，助理研究员，主要研究方向为污水处理模型，"
        "zhaoguangyao@cigit.ac.cn"
    )
    assert library.authors["liu_hong"].bio_en == (
        "Hong Liu (1970--), PhD, Professor, specializing in water pollution "
        "control and intelligent wastewater treatment, liuhong@cigit.ac.cn"
    )
    affiliation_1 = library.affiliations["1"]
    affiliation_2 = library.affiliations["2"]
    assert affiliation_1.name_zh == "中国科学院重庆绿色智能技术研究院，重庆 400714"
    assert affiliation_2.name_zh == "三峡实验室，重庆400714"
    assert affiliation_1.address == ""
    assert affiliation_2.address == ""
    assert affiliation_1.name_en == (
        "Chongqing Institute of Green and Intelligent Technology, "
        "Chinese Academy of Sciences, Chongqing 400714, China"
    )
    assert affiliation_2.name_en == ("Three Gorges Laboratory, Chongqing 400714, China")
    assert main(["authors", "list"]) == 0
    assert "song_cheng: Cheng Song / 宋诚" in capsys.readouterr().out


def test_bundled_library_never_auto_selects_all_authors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_DIRECTORY_ENV, str(tmp_path / "empty-config"))
    monkeypatch.setattr(cli.sys, "stdin", argparse.Namespace(isatty=lambda: False))
    args = argparse.Namespace(
        authors=None,
        first=[],
        corresponding=[],
        other=[],
    )
    with pytest.raises(ManuscriptError, match=r"first-author|corresponding-author"):
        cli._selected_authors(args)


def test_signing_author_rules(tmp_path: Path) -> None:
    library = load_author_library(_library(tmp_path / "authors.yaml"))
    library.authors["author_two"] = replace(
        library.authors["author_two"], email="two@example.invalid"
    )
    single = resolve_authors(_metadata(other=()), library)
    assert resolve_signing_author(_metadata(other=()), single) == single.authors[0]
    multiple_metadata = replace(
        _metadata(other=()),
        corresponding_authors=("author_one", "author_two"),
    )
    multiple = resolve_authors(multiple_metadata, library)
    with pytest.raises(MetadataError, match="signing_author"):
        resolve_signing_author(
            multiple_metadata, multiple, require_explicit_multiple=True
        )
    selected = replace(
        multiple_metadata,
        correspondence=CorrespondenceSettings(signing_author="author_two"),
    )
    signer = resolve_signing_author(selected, multiple)
    assert signer is not None
    assert signer.author_id == "author_two"


def test_correspondence_metadata_is_data_driven(tmp_path: Path) -> None:
    library = load_author_library(_library(tmp_path / "authors.yaml"))
    metadata = replace(
        _metadata(other=()),
        correspondence=CorrespondenceSettings(
            manuscript_id="MS-2026-001",
            editor_name="Anonymous Editor",
            editor_title="Handling Editor",
            signing_author="author_one",
        ),
    )
    rendered = render_author_metadata(metadata, resolve_authors(metadata, library))
    assert r"\newcommand{\ManuscriptID}{MS-2026-001}" in rendered
    assert r"\newcommand{\EditorName}{Anonymous Editor}" in rendered
    assert r"\newcommand{\EditorTitle}{Handling Editor}" in rendered
    assert r"\newcommand{\CorrespondenceAuthorName}{Anonymous One}" in rendered


def test_author_without_affiliation_has_actionable_metadata_error(
    tmp_path: Path,
) -> None:
    path = _library(tmp_path / "authors.yaml")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "affiliations: [institute]", "affiliations: []", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(MetadataError, match="affiliations must be a non-empty list"):
        load_author_library(path)


def test_authors_cli_configure_list_and_show(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(CONFIG_DIRECTORY_ENV, str(tmp_path / "config"))
    source = _library(tmp_path / "authors.yaml")
    assert main(["authors", "configure", str(source)]) == 0
    assert main(["authors", "list"]) == 0
    assert main(["authors", "show", "author_one"]) == 0
    output = capsys.readouterr().out
    assert "author_one: Anonymous One / 匿名甲" in output
    assert "Email: one@example.invalid" in output


def test_interactive_init_lists_and_selects_author_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(CONFIG_DIRECTORY_ENV, str(tmp_path / "config"))
    configure_author_library(_library(tmp_path / "authors.yaml"))
    monkeypatch.setattr(cli.sys, "stdin", argparse.Namespace(isatty=lambda: True))
    answers = iter(("author_one", "author_one", "author_two"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    args = argparse.Namespace(
        authors=None,
        first=[],
        corresponding=[],
        other=[],
    )
    selected = cli._selected_authors(args)
    assert selected == (("author_one",), ("author_one",), ("author_two",))
    output = capsys.readouterr().out
    assert "1. author_one" in output
    assert "Anonymous One / 匿名甲" in output
