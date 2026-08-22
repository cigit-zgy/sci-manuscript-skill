"""Global and explicit author-library behavior tests."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pytest

from sci_manuscript import cli
from sci_manuscript.cli import main
from sci_manuscript.errors import ManuscriptError
from sci_manuscript.metadata import (
    CONFIG_DIRECTORY_ENV,
    CorrespondenceSettings,
    ManuscriptMetadata,
    MetadataError,
    SubmissionSettings,
    configure_author_library,
    configured_author_library_path,
    load_author_library,
    render_author_metadata,
    resolve_author_library_path,
    resolve_authors,
    resolve_signing_author,
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
    with pytest.raises(MetadataError, match="email"):
        resolve_authors(invalid, library)


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


def test_global_library_is_configured_resolved_and_copied(
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
        resolve_author_library_path(),
    )
    copied = initialized.references / "authors.yaml"
    assert copied.read_bytes() == source.read_bytes()
    assert resolve_authors(_metadata(), load_author_library(copied)).authors


def test_explicit_library_overrides_global(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_DIRECTORY_ENV, str(tmp_path / "config"))
    configure_author_library(_library(tmp_path / "global.yaml"))
    explicit = _library(tmp_path / "explicit.yaml", author_id="explicit_author")
    assert resolve_author_library_path(explicit) == explicit.resolve()


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
    assert library.authors["song_cheng"].email == ""
    assert library.affiliations["1"].name_zh == ""
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
        first_author=[],
        corresponding_author=[],
        other_author=[],
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
        first_author=[],
        corresponding_author=[],
        other_author=[],
    )
    selected = cli._selected_authors(args)
    assert selected == (("author_one",), ("author_one",), ("author_two",))
    output = capsys.readouterr().out
    assert "1. author_one" in output
    assert "Anonymous One / 匿名甲" in output
