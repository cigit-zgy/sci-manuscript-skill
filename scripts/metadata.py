"""Validate project metadata and render shared LaTeX author commands."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


class MetadataError(RuntimeError):
    """Raised when manuscript or author-library metadata is invalid."""


try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - environment boundary
    raise MetadataError(
        "PyYAML is required. Install the dependencies declared in pyproject.toml."
    ) from exc


PUBLISHERS = ("elsevier", "nature", "acs", "chinese")


@dataclass(frozen=True)
class AuthorRecord:
    """One complete author record from the project author library."""

    name: str
    name_zh: str
    email: str
    role: str
    affiliations: tuple[str, ...]


@dataclass(frozen=True)
class AffiliationRecord:
    """One affiliation address referenced by author records."""

    key: str
    name_en: str
    address: str


@dataclass(frozen=True)
class AuthorLibrary:
    """Validated project-local author and affiliation database."""

    authors: dict[str, AuthorRecord]
    affiliations: tuple[AffiliationRecord, ...]


@dataclass(frozen=True)
class SubmissionSettings:
    """Round-local switches for optional submission materials."""

    cover_letter: bool
    highlights: bool
    graphical_abstract: bool


@dataclass(frozen=True)
class ManuscriptMetadata:
    """The sole persistent configuration for one manuscript version."""

    title: str
    article_type: str
    language: str
    journal_name: str
    publisher: str
    round_number: int
    parent_round: int | None
    submission: SubmissionSettings
    author_names: tuple[str, ...]


@dataclass(frozen=True)
class AuthorSelection:
    """Resolved authors and corresponding author for one manuscript version."""

    authors: tuple[AuthorRecord, ...]
    affiliations: tuple[AffiliationRecord, ...]
    corresponding_author: AuthorRecord


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MetadataError(f"Required YAML file is missing: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MetadataError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise MetadataError(f"YAML root must be a mapping: {path}")
    return data


def _mapping(value: Any, location: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise MetadataError(f"{location} must be a mapping.")
    return value


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MetadataError(f"{location} must be a non-empty string.")
    return value.strip()


def _boolean(value: Any, location: str) -> bool:
    if not isinstance(value, bool):
        raise MetadataError(f"{location} must be true or false.")
    return value


def _round_number(value: Any, location: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.startswith("r"):
        raise MetadataError(f"{location} must be null or a round such as r0.")
    suffix = value[1:]
    if not suffix.isdigit() or (suffix.startswith("0") and suffix != "0"):
        raise MetadataError(f"{location} must be null or a round such as r0.")
    return int(suffix)


def _author_names(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise MetadataError("authors must be a non-empty list of author names.")
    names = tuple(_text(item, f"authors[{index}]") for index, item in enumerate(value))
    if len(set(names)) != len(names):
        raise MetadataError("authors must not contain duplicate names.")
    return names


def load_manuscript(path: Path) -> ManuscriptMetadata:
    """Load and validate one version's ``manuscript.yaml``."""
    data = _read_yaml(path)
    expected = {"manuscript", "journal", "revision", "submission", "authors"}
    unexpected = set(data) - expected
    if unexpected:
        raise MetadataError(
            f"Unsupported manuscript.yaml keys: {', '.join(sorted(unexpected))}."
        )
    manuscript = _mapping(data.get("manuscript"), "manuscript")
    journal = _mapping(data.get("journal"), "journal")
    revision = _mapping(data.get("revision"), "revision")
    submission = _mapping(data.get("submission"), "submission")
    current = _round_number(revision.get("id"), "revision.id")
    if current is None:
        raise MetadataError("revision.id cannot be null.")
    parent = _round_number(revision.get("parent"), "revision.parent")
    if current == 0 and parent is not None:
        raise MetadataError("R0 must have revision.parent: null.")
    if current > 0 and parent != current - 1:
        raise MetadataError(f"R{current} must declare revision.parent: r{current - 1}.")
    language = _text(manuscript.get("language"), "manuscript.language")
    if language not in {"en", "zh"}:
        raise MetadataError("manuscript.language must be en or zh.")
    publisher = _text(journal.get("publisher"), "journal.publisher").lower()
    if publisher not in PUBLISHERS:
        available = ", ".join(PUBLISHERS)
        raise MetadataError(f"journal.publisher must be one of: {available}.")
    return ManuscriptMetadata(
        title=_text(manuscript.get("title"), "manuscript.title"),
        article_type=_text(manuscript.get("article_type"), "manuscript.article_type"),
        language=language,
        journal_name=_text(journal.get("name"), "journal.name"),
        publisher=publisher,
        round_number=current,
        parent_round=parent,
        submission=SubmissionSettings(
            cover_letter=_boolean(
                submission.get("cover_letter"), "submission.cover_letter"
            ),
            highlights=_boolean(submission.get("highlights"), "submission.highlights"),
            graphical_abstract=_boolean(
                submission.get("graphical_abstract"),
                "submission.graphical_abstract",
            ),
        ),
        author_names=_author_names(data.get("authors")),
    )


def save_manuscript(path: Path, metadata: ManuscriptMetadata) -> None:
    """Write an annotated, deterministic manuscript configuration."""
    sections = (
        (
            "Manuscript",
            {
                "manuscript": {
                    "title": metadata.title,
                    "article_type": metadata.article_type,
                    "language": metadata.language,
                }
            },
        ),
        (
            "Journal template",
            {
                "journal": {
                    "name": metadata.journal_name,
                    "publisher": metadata.publisher,
                }
            },
        ),
        (
            "Revision",
            {
                "revision": {
                    "id": f"r{metadata.round_number}",
                    "parent": (
                        None
                        if metadata.parent_round is None
                        else f"r{metadata.parent_round}"
                    ),
                }
            },
        ),
        (
            "Submission",
            {
                "submission": {
                    "cover_letter": metadata.submission.cover_letter,
                    "highlights": metadata.submission.highlights,
                    "graphical_abstract": metadata.submission.graphical_abstract,
                }
            },
        ),
        ("Authors", {"authors": list(metadata.author_names)}),
    )
    pieces: list[str] = []
    for title, section in sections:
        pieces.extend(
            [
                "# =====================================",
                f"# {title}",
                "# =====================================",
                "",
                yaml.safe_dump(
                    section,
                    allow_unicode=True,
                    sort_keys=False,
                ).rstrip(),
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.new")
    temporary.write_text("\n".join(pieces), encoding="utf-8")
    os.replace(temporary, path)


def with_revision(
    metadata: ManuscriptMetadata,
    round_number: int,
) -> ManuscriptMetadata:
    """Return metadata for the immediate child revision."""
    return replace(
        metadata,
        round_number=round_number,
        parent_round=round_number - 1,
    )


def load_author_library(path: Path) -> AuthorLibrary:
    """Load and validate a project-local author library."""
    data = _read_yaml(path)
    unexpected = set(data) - {"authors", "affiliations"}
    if unexpected:
        raise MetadataError(
            f"Unsupported authors.yaml keys: {', '.join(sorted(unexpected))}."
        )
    raw_authors = _mapping(data.get("authors"), "authors")
    raw_affiliations = _mapping(data.get("affiliations"), "affiliations")
    affiliations = tuple(
        AffiliationRecord(
            key=str(raw_key),
            name_en=_text(
                _mapping(item, f"affiliations.{raw_key}").get("name_en"),
                f"affiliations.{raw_key}.name_en",
            ),
            address=_text(
                _mapping(item, f"affiliations.{raw_key}").get("address"),
                f"affiliations.{raw_key}.address",
            ),
        )
        for raw_key, item in raw_affiliations.items()
    )
    if not affiliations:
        raise MetadataError("affiliations must not be empty.")
    authors: dict[str, AuthorRecord] = {}
    for raw_name, item in raw_authors.items():
        name = _text(raw_name, "authors key")
        record = _mapping(item, f"authors.{name}")
        role = _text(record.get("role"), f"authors.{name}.role")
        if role not in {"author", "corresponding_author"}:
            raise MetadataError(
                f"authors.{name}.role must be author or corresponding_author."
            )
        raw_keys = record.get("affiliations")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise MetadataError(
                f"authors.{name}.affiliations must be a non-empty list."
            )
        authors[name] = AuthorRecord(
            name=_text(record.get("name_en", name), f"authors.{name}.name_en"),
            name_zh=_text(record.get("name_zh", name), f"authors.{name}.name_zh"),
            email=_text(record.get("email"), f"authors.{name}.email"),
            role=role,
            affiliations=tuple(str(key) for key in raw_keys),
        )
    if not authors:
        raise MetadataError("authors must not be empty.")
    affiliation_keys = {record.key for record in affiliations}
    for name, author in authors.items():
        missing = set(author.affiliations) - affiliation_keys
        if missing:
            raise MetadataError(
                f"Author {name!r} references missing affiliations: "
                f"{', '.join(sorted(missing))}."
            )
    return AuthorLibrary(authors=authors, affiliations=affiliations)


def resolve_authors(
    metadata: ManuscriptMetadata,
    library: AuthorLibrary,
) -> AuthorSelection:
    """Resolve selected names and validate the corresponding-author invariant."""
    missing = [name for name in metadata.author_names if name not in library.authors]
    if missing:
        raise MetadataError(
            "Selected authors are missing from references/authors.yaml: "
            + ", ".join(missing)
        )
    authors = tuple(library.authors[name] for name in metadata.author_names)
    corresponding = [
        author for author in authors if author.role == "corresponding_author"
    ]
    if len(corresponding) != 1:
        raise MetadataError(
            "Selected authors must include exactly one corresponding_author."
        )
    used_keys = {key for author in authors for key in author.affiliations}
    affiliations = tuple(
        record for record in library.affiliations if record.key in used_keys
    )
    return AuthorSelection(authors, affiliations, corresponding[0])


def _latex_escape(value: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _author_label(author: AuthorRecord, language: str) -> str:
    markers = list(author.affiliations)
    if author.role == "corresponding_author":
        markers.append("*")
    name = author.name_zh if language == "zh" else author.name
    return f"{_latex_escape(name)}$^{{{','.join(markers)}}}$"


def render_author_metadata(
    metadata: ManuscriptMetadata,
    selection: AuthorSelection,
) -> str:
    """Render reusable LaTeX manuscript and correspondence metadata."""
    names_en = ", ".join(_latex_escape(item.name) for item in selection.authors)
    names_zh = "、".join(_latex_escape(item.name_zh) for item in selection.authors)
    corresponding = selection.corresponding_author
    affiliation_lines = [
        f"$^{{{item.key}}}${_latex_escape(item.name_en)}, {_latex_escape(item.address)}"
        for item in selection.affiliations
    ]
    separator = "\N{FULLWIDTH COMMA}\n" if metadata.language == "zh" else ",\n"
    author_lines = separator.join(
        _author_label(item, metadata.language) for item in selection.authors
    )
    affiliation_block = "\\\\\n\\small ".join(affiliation_lines)
    corresponding_name = (
        r"\CorrespondingAuthorNameZh"
        if metadata.language == "zh"
        else r"\CorrespondingAuthorName"
    )
    corresponding_label = (
        "通讯作者" if metadata.language == "zh" else "Corresponding author"
    )
    return "\n".join(
        [
            "% Generated from manuscript.yaml and authors.yaml. Do not edit.",
            f"\\newcommand{{\\ManuscriptTitle}}{{{_latex_escape(metadata.title)}}}",
            f"\\newcommand{{\\JournalName}}{{{_latex_escape(metadata.journal_name)}}}",
            f"\\newcommand{{\\ArticleType}}{{{_latex_escape(metadata.article_type)}}}",
            f"\\newcommand{{\\SelectedAuthorNames}}{{{names_en}}}",
            f"\\newcommand{{\\SelectedAuthorNamesZh}}{{{names_zh}}}",
            "\\newcommand{\\CorrespondingAuthorName}"
            f"{{{_latex_escape(corresponding.name)}}}",
            "\\newcommand{\\CorrespondingAuthorNameZh}"
            f"{{{_latex_escape(corresponding.name_zh)}}}",
            "\\newcommand{\\CorrespondingAuthorEmail}"
            f"{{{_latex_escape(corresponding.email)}}}",
            "\\author{%",
            author_lines + r"\\[0.6em]",
            r"\parbox{0.92\textwidth}{\centering\small",
            f"{affiliation_block}\\\\[0.4em]",
            f"$^*${corresponding_label}: "
            f"{corresponding_name}\\ (\\CorrespondingAuthorEmail)}}",
            "}",
            "",
        ]
    )


def generate_author_metadata(round_dir: Path) -> AuthorSelection:
    """Generate version-local LaTeX metadata from version-local YAML inputs."""
    metadata = load_manuscript(round_dir / "manuscript.yaml")
    references = round_dir / "references"
    library = load_author_library(references / "authors.yaml")
    selection = resolve_authors(metadata, library)
    target = references / "author_metadata.tex"
    temporary = target.with_suffix(".tex.new")
    temporary.write_text(
        render_author_metadata(metadata, selection),
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return selection
