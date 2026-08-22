"""Validate project metadata and render publisher-specific author commands."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from .errors import ManuscriptError


class MetadataError(ManuscriptError):
    """Raised when ``meta.yaml`` or ``authors.yaml`` is invalid."""


PUBLISHER_TEMPLATES = {
    "elsevier": "elsarticle",
    "nature": "sn-jnl",
    "acs": "achemso",
    "chinese": "kxtbcas",
}
PUBLISHERS = (*PUBLISHER_TEMPLATES, "custom")
ROUND_PATTERN = re.compile(r"^r(\d{2,})$")
CONFIG_DIRECTORY_ENV = "SCI_MANUSCRIPT_CONFIG_DIR"


@dataclass(frozen=True)
class AuthorRecord:
    """One author from the manuscript-level author library."""

    author_id: str
    name_zh: str
    name_en: str
    email: str
    affiliations: tuple[str, ...]


@dataclass(frozen=True)
class AffiliationRecord:
    """One complete bilingual affiliation."""

    affiliation_id: str
    name_zh: str
    name_en: str
    address: str


@dataclass(frozen=True)
class AuthorLibrary:
    """Validated author and affiliation database."""

    authors: dict[str, AuthorRecord]
    affiliations: dict[str, AffiliationRecord]


@dataclass(frozen=True)
class SubmissionSettings:
    """Round-local switches for optional submission material."""

    cover_letter: bool = True
    highlights: bool = True
    graphical_abstract: bool = True


@dataclass(frozen=True)
class CorrespondenceSettings:
    """Optional journal correspondence metadata for one manuscript round."""

    manuscript_id: str = ""
    editor_name: str = ""
    editor_title: str = ""
    signing_author: str = ""


@dataclass(frozen=True)
class ManuscriptMetadata:
    """The complete editable configuration for one manuscript version."""

    title: str
    article_type: str
    language: str
    journal_name: str
    publisher: str
    round_number: int
    parent_round: int | None
    first_authors: tuple[str, ...]
    corresponding_authors: tuple[str, ...]
    other_authors: tuple[str, ...]
    submission: SubmissionSettings = SubmissionSettings()
    correspondence: CorrespondenceSettings = CorrespondenceSettings()

    @property
    def author_ids(self) -> tuple[str, ...]:
        """Return publication order while preserving permitted role overlap."""
        ordered = (
            *self.first_authors,
            *self.other_authors,
            *self.corresponding_authors,
        )
        return tuple(dict.fromkeys(ordered))

    @property
    def journal_template(self) -> str:
        """Return the selected built-in class or the custom marker."""
        return PUBLISHER_TEMPLATES.get(self.publisher, "custom")


@dataclass(frozen=True)
class AuthorSelection:
    """Resolved authors and their used affiliations."""

    authors: tuple[AuthorRecord, ...]
    affiliations: tuple[AffiliationRecord, ...]
    first_authors: tuple[AuthorRecord, ...]
    corresponding_authors: tuple[AuthorRecord, ...]
    affiliation_numbers: dict[str, int]


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def user_config_directory() -> Path:
    """Return the single operating-system user configuration directory."""
    explicit = os.environ.get(CONFIG_DIRECTORY_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "sci-manuscript"
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        return (
            Path(base).expanduser().resolve() / "sci-manuscript"
            if base
            else Path.home() / "AppData" / "Roaming" / "sci-manuscript"
        )
    base = os.environ.get("XDG_CONFIG_HOME")
    return (
        Path(base).expanduser().resolve() / "sci-manuscript"
        if base
        else Path.home() / ".config" / "sci-manuscript"
    )


def configured_author_library_path() -> Path:
    """Return the canonical user-level author library path."""
    return user_config_directory() / "authors.yaml"


def resolve_author_library_path(explicit: str | Path | None = None) -> Path:
    """Resolve explicit, user-level, then bundled public author data."""
    if explicit is not None:
        selected = Path(explicit).expanduser().resolve()
        if not selected.is_file():
            raise MetadataError(f"Author library is missing: {selected}")
        return selected
    configured = configured_author_library_path()
    if configured.is_file():
        return configured
    bundled = Path(str(files("sci_manuscript.resources") / "authors.yaml"))
    if not bundled.is_file():
        raise MetadataError("Bundled author library is missing from the installation.")
    return bundled


def configure_author_library(source: str | Path) -> Path:
    """Validate and atomically install one reusable user author library."""
    selected = Path(source).expanduser().resolve()
    load_author_library(selected)
    target = configured_author_library_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".yaml.new")
    try:
        temporary.write_bytes(selected.read_bytes())
        os.replace(temporary, target)
    except OSError as exc:
        if temporary.exists():
            temporary.unlink()
        raise MetadataError(f"Cannot configure author library: {target}") from exc
    return target


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MetadataError(f"YAML file is missing: {path}")
    try:
        data = yaml.load(
            path.read_text(encoding="utf-8"),
            Loader=_UniqueKeyLoader,
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise MetadataError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise MetadataError(f"YAML root must be a mapping: {path}")
    return data


def _mapping(value: Any, location: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise MetadataError(f"{location} must be a mapping.")
    return value


def _text(value: Any, location: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value.strip():
        requirement = "a string" if optional else "a non-empty string"
        raise MetadataError(f"{location} must be {requirement}.")
    return value.strip()


def _boolean(value: Any, location: str) -> bool:
    if not isinstance(value, bool):
        raise MetadataError(f"{location} must be true or false.")
    return value


def _round(value: Any, location: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise MetadataError(f"{location} must use r00, r01, r02, ...")
    match = ROUND_PATTERN.fullmatch(value)
    if match is None:
        raise MetadataError(f"{location} must use r00, r01, r02, ...")
    return int(match.group(1))


def _author_group(value: Any, location: str, *, required: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (required and not value):
        requirement = "a non-empty list" if required else "a list"
        raise MetadataError(f"{location} must be {requirement} of author IDs.")
    ids = tuple(_text(item, f"{location}[{index}]") for index, item in enumerate(value))
    if len(ids) != len(set(ids)):
        raise MetadataError(f"{location} must not contain duplicate author IDs.")
    return ids


def round_name(round_number: int) -> str:
    """Return a fixed-width semantic revision identifier."""
    if round_number < 0:
        raise MetadataError("Round numbers must be non-negative.")
    return f"r{round_number:02d}"


def revision_directory_name(round_number: int) -> str:
    """Return the directory for one semantic revision."""
    if round_number < 0:
        raise MetadataError("Round numbers must be non-negative.")
    return "initial_submission" if round_number == 0 else f"revision_{round_number:02d}"


def load_meta(path: Path) -> ManuscriptMetadata:
    """Load and validate one version's ``meta.yaml``."""
    data = _read_yaml(path)
    expected = {
        "revision",
        "manuscript",
        "journal",
        "authors",
        "submission",
        "correspondence",
    }
    unexpected = set(data) - expected
    if unexpected:
        raise MetadataError(
            f"Unsupported meta.yaml keys: {', '.join(sorted(unexpected))}."
        )
    revision = _mapping(data.get("revision"), "revision")
    manuscript = _mapping(data.get("manuscript"), "manuscript")
    journal = _mapping(data.get("journal"), "journal")
    authors = _mapping(data.get("authors"), "authors")
    current = _round(revision.get("round"), "revision.round")
    assert current is not None
    expected_name = revision_directory_name(current)
    if _text(revision.get("name"), "revision.name") != expected_name:
        raise MetadataError(f"revision.name must be {expected_name!r}.")
    parent = _round(revision.get("parent"), "revision.parent", nullable=True)
    if current == 0 and parent is not None:
        raise MetadataError("r00 must have revision.parent: null.")
    if current > 0 and parent != current - 1:
        raise MetadataError(
            f"{round_name(current)} must declare parent {round_name(current - 1)}."
        )
    language = _text(manuscript.get("language"), "manuscript.language")
    if language not in {"en", "zh"}:
        raise MetadataError("manuscript.language must be en or zh.")
    publisher = _text(journal.get("publisher"), "journal.publisher").lower()
    if publisher not in PUBLISHERS:
        raise MetadataError(
            f"journal.publisher must be one of: {', '.join(PUBLISHERS)}."
        )
    raw_submission = data.get("submission")
    if raw_submission is None:
        submission = SubmissionSettings()
    else:
        settings = _mapping(raw_submission, "submission")
        submission = SubmissionSettings(
            _boolean(settings.get("cover_letter", True), "submission.cover_letter"),
            _boolean(settings.get("highlights", True), "submission.highlights"),
            _boolean(
                settings.get("graphical_abstract", True),
                "submission.graphical_abstract",
            ),
        )
    raw_correspondence = data.get("correspondence")
    if raw_correspondence is None:
        correspondence = CorrespondenceSettings()
    else:
        settings = _mapping(raw_correspondence, "correspondence")
        unexpected_correspondence = set(settings) - {
            "manuscript_id",
            "editor_name",
            "editor_title",
            "signing_author",
        }
        if unexpected_correspondence:
            raise MetadataError(
                "Unsupported correspondence keys: "
                + ", ".join(sorted(unexpected_correspondence))
            )
        correspondence = CorrespondenceSettings(
            manuscript_id=_text(
                settings.get("manuscript_id"),
                "correspondence.manuscript_id",
                optional=True,
            ),
            editor_name=_text(
                settings.get("editor_name"),
                "correspondence.editor_name",
                optional=True,
            ),
            editor_title=_text(
                settings.get("editor_title"),
                "correspondence.editor_title",
                optional=True,
            ),
            signing_author=_text(
                settings.get("signing_author"),
                "correspondence.signing_author",
                optional=True,
            ),
        )
        if (
            correspondence.signing_author
            and correspondence.signing_author
            not in _author_group(
                authors.get("corresponding_author"),
                "authors.corresponding_author",
                required=True,
            )
        ):
            raise MetadataError(
                "correspondence.signing_author must be a corresponding author."
            )
    return ManuscriptMetadata(
        title=_text(manuscript.get("title"), "manuscript.title"),
        article_type=_text(manuscript.get("article_type"), "manuscript.article_type"),
        language=language,
        journal_name=_text(journal.get("name"), "journal.name"),
        publisher=publisher,
        round_number=current,
        parent_round=parent,
        first_authors=_author_group(
            authors.get("first_author"), "authors.first_author", required=True
        ),
        corresponding_authors=_author_group(
            authors.get("corresponding_author"),
            "authors.corresponding_author",
            required=True,
        ),
        other_authors=_author_group(
            authors.get("other_author", []),
            "authors.other_author",
            required=False,
        ),
        submission=submission,
        correspondence=correspondence,
    )


def save_meta(path: Path, metadata: ManuscriptMetadata) -> None:
    """Atomically write deterministic round metadata."""
    data = {
        "revision": {
            "round": round_name(metadata.round_number),
            "name": revision_directory_name(metadata.round_number),
            "parent": (
                None
                if metadata.parent_round is None
                else round_name(metadata.parent_round)
            ),
        },
        "manuscript": {
            "title": metadata.title,
            "language": metadata.language,
            "article_type": metadata.article_type,
        },
        "journal": {
            "name": metadata.journal_name,
            "publisher": metadata.publisher,
        },
        "authors": {
            "first_author": list(metadata.first_authors),
            "corresponding_author": list(metadata.corresponding_authors),
            "other_author": list(metadata.other_authors),
        },
        "submission": {
            "cover_letter": metadata.submission.cover_letter,
            "highlights": metadata.submission.highlights,
            "graphical_abstract": metadata.submission.graphical_abstract,
        },
        "correspondence": {
            "manuscript_id": metadata.correspondence.manuscript_id or None,
            "editor_name": metadata.correspondence.editor_name or None,
            "editor_title": metadata.correspondence.editor_title or None,
            "signing_author": metadata.correspondence.signing_author or None,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.new")
    temporary.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    os.replace(temporary, path)


def with_revision(
    metadata: ManuscriptMetadata,
    round_number: int,
) -> ManuscriptMetadata:
    """Return the direct child metadata while preserving all editable fields."""
    return replace(metadata, round_number=round_number, parent_round=round_number - 1)


def load_author_library(path: Path) -> AuthorLibrary:
    """Load the role-free manuscript author database."""
    data = _read_yaml(path)
    unexpected = set(data) - {"authors", "affiliations"}
    if unexpected:
        raise MetadataError(
            f"Unsupported authors.yaml keys: {', '.join(sorted(unexpected))}."
        )
    raw_affiliations = _mapping(data.get("affiliations"), "affiliations")
    affiliations: dict[str, AffiliationRecord] = {}
    for raw_id, item in raw_affiliations.items():
        affiliation_id = _text(str(raw_id), "affiliation ID")
        if affiliation_id in affiliations:
            raise MetadataError(f"Duplicate affiliation ID: {affiliation_id}")
        record = _mapping(item, f"affiliations.{affiliation_id}")
        unexpected_affiliation = set(record) - {"name_zh", "name_en", "address"}
        if unexpected_affiliation:
            raise MetadataError(
                f"Affiliation {affiliation_id!r} contains unsupported keys: "
                + ", ".join(sorted(unexpected_affiliation))
            )
        affiliations[affiliation_id] = AffiliationRecord(
            affiliation_id,
            _text(
                record.get("name_zh"),
                f"affiliations.{affiliation_id}.name_zh",
                optional=True,
            ),
            _text(
                record.get("name_en"),
                f"affiliations.{affiliation_id}.name_en",
            ),
            _text(
                record.get("address"),
                f"affiliations.{affiliation_id}.address",
                optional=True,
            ),
        )
    if not affiliations:
        raise MetadataError("affiliations must not be empty.")
    raw_authors = _mapping(data.get("authors"), "authors")
    authors: dict[str, AuthorRecord] = {}
    for raw_id, item in raw_authors.items():
        author_id = _text(str(raw_id), "author ID")
        if author_id in authors:
            raise MetadataError(f"Duplicate author ID: {author_id}")
        record = _mapping(item, f"authors.{author_id}")
        unexpected_author = set(record) - {
            "name_zh",
            "name_en",
            "email",
            "affiliations",
        }
        if unexpected_author:
            raise MetadataError(
                f"Author {author_id!r} contains unsupported keys: "
                + ", ".join(sorted(unexpected_author))
            )
        raw_keys = record.get("affiliations")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise MetadataError(
                f"authors.{author_id}.affiliations must be a non-empty list."
            )
        keys = tuple(
            _text(str(key), f"authors.{author_id}.affiliations") for key in raw_keys
        )
        missing = set(keys) - set(affiliations)
        if missing:
            raise MetadataError(
                f"Author {author_id!r} references missing affiliations: "
                + ", ".join(sorted(missing))
            )
        authors[author_id] = AuthorRecord(
            author_id,
            _text(record.get("name_zh"), f"authors.{author_id}.name_zh"),
            _text(record.get("name_en"), f"authors.{author_id}.name_en"),
            _text(
                record.get("email"),
                f"authors.{author_id}.email",
                optional=True,
            ),
            keys,
        )
    if not authors:
        raise MetadataError("authors must not be empty.")
    return AuthorLibrary(authors, affiliations)


def resolve_authors(
    metadata: ManuscriptMetadata,
    library: AuthorLibrary,
) -> AuthorSelection:
    """Resolve selected author IDs without assigning library-level roles."""
    missing = [
        author_id
        for author_id in metadata.author_ids
        if author_id not in library.authors
    ]
    if missing:
        raise MetadataError(
            "Selected author IDs are missing from references/authors.yaml: "
            + ", ".join(missing)
        )
    corresponding = tuple(
        library.authors[item] for item in metadata.corresponding_authors
    )
    missing_emails = [author.author_id for author in corresponding if not author.email]
    if missing_emails:
        raise MetadataError(
            "Corresponding authors require email addresses: "
            + ", ".join(missing_emails)
        )
    selected = tuple(library.authors[item] for item in metadata.author_ids)
    used_affiliations = tuple(
        dict.fromkeys(key for author in selected for key in author.affiliations)
    )
    numbers = {key: index for index, key in enumerate(used_affiliations, 1)}
    return AuthorSelection(
        selected,
        tuple(library.affiliations[key] for key in used_affiliations),
        tuple(library.authors[item] for item in metadata.first_authors),
        corresponding,
        numbers,
    )


def resolve_signing_author(
    metadata: ManuscriptMetadata,
    selection: AuthorSelection,
    *,
    require_explicit_multiple: bool = False,
) -> AuthorRecord | None:
    """Resolve the correspondence signer without assigning an author-library role."""
    requested = metadata.correspondence.signing_author
    if requested:
        for author in selection.corresponding_authors:
            if author.author_id == requested:
                return author
        raise MetadataError(
            "correspondence.signing_author must be a corresponding author."
        )
    if len(selection.corresponding_authors) == 1:
        return selection.corresponding_authors[0]
    if require_explicit_multiple:
        raise MetadataError(
            "Multiple corresponding authors require correspondence.signing_author."
        )
    return None


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _author_label(
    author: AuthorRecord,
    selection: AuthorSelection,
    language: str,
) -> str:
    markers = [str(selection.affiliation_numbers[key]) for key in author.affiliations]
    if author in selection.corresponding_authors:
        markers.append("*")
    name = author.name_zh if language == "zh" else author.name_en
    return f"{_latex_escape(name)}$^{{{','.join(markers)}}}$"


def _affiliation_text(affiliation: AffiliationRecord, language: str) -> str:
    """Render one affiliation without inventing unavailable translations."""
    name = (
        affiliation.name_zh
        if language == "zh" and affiliation.name_zh
        else affiliation.name_en
    )
    return ", ".join(part for part in (name, affiliation.address) if part)


def render_author_metadata(
    metadata: ManuscriptMetadata,
    selection: AuthorSelection,
) -> str:
    """Render shared correspondence macros."""
    names_en = ", ".join(_latex_escape(item.name_en) for item in selection.authors)
    names_zh = "、".join(_latex_escape(item.name_zh) for item in selection.authors)
    first_names = ", ".join(
        _latex_escape(item.name_en) for item in selection.first_authors
    )
    corresponding_names = ", ".join(
        _latex_escape(item.name_en) for item in selection.corresponding_authors
    )
    corresponding_names_zh = "、".join(
        _latex_escape(item.name_zh) for item in selection.corresponding_authors
    )
    emails = "; ".join(
        _latex_escape(item.email) for item in selection.corresponding_authors
    )
    affiliation_lines = [
        f"$^{{{selection.affiliation_numbers[item.affiliation_id]}}}$"
        + _latex_escape(_affiliation_text(item, "en"))
        for item in selection.affiliations
    ]
    signer = resolve_signing_author(metadata, selection)
    signer_affiliations = (
        tuple(
            affiliation
            for affiliation in selection.affiliations
            if signer is not None and affiliation.affiliation_id in signer.affiliations
        )
        if signer is not None
        else ()
    )
    signer_affiliation_en = "; ".join(
        _latex_escape(item.name_en) for item in signer_affiliations
    )
    signer_affiliation_zh = "; ".join(
        _latex_escape(item.name_zh or item.name_en) for item in signer_affiliations
    )
    signer_addresses = "; ".join(
        dict.fromkeys(
            _latex_escape(item.address) for item in signer_affiliations if item.address
        )
    )
    correspondence = metadata.correspondence
    return "\n".join(
        [
            "% Generated from meta.yaml and authors.yaml. Do not edit.",
            f"\\newcommand{{\\ManuscriptTitle}}{{{_latex_escape(metadata.title)}}}",
            f"\\newcommand{{\\JournalName}}{{{_latex_escape(metadata.journal_name)}}}",
            f"\\newcommand{{\\ArticleType}}{{{_latex_escape(metadata.article_type)}}}",
            f"\\newcommand{{\\SelectedAuthorNames}}{{{names_en}}}",
            f"\\newcommand{{\\SelectedAuthorNamesZh}}{{{names_zh}}}",
            f"\\newcommand{{\\FirstAuthorNames}}{{{first_names}}}",
            f"\\newcommand{{\\CorrespondingAuthorName}}{{{corresponding_names}}}",
            f"\\newcommand{{\\CorrespondingAuthorNameZh}}{{{corresponding_names_zh}}}",
            f"\\newcommand{{\\CorrespondingAuthorEmail}}{{{emails}}}",
            "\\newcommand{\\CorrespondenceAuthorName}{"
            + (_latex_escape(signer.name_en) if signer is not None else "")
            + "}",
            "\\newcommand{\\CorrespondenceAuthorNameZh}{"
            + (_latex_escape(signer.name_zh) if signer is not None else "")
            + "}",
            "\\newcommand{\\CorrespondenceAuthorEmail}{"
            + (_latex_escape(signer.email) if signer is not None else "")
            + "}",
            f"\\newcommand{{\\CorrespondenceAuthorAffiliation}}{{{signer_affiliation_en}}}",
            f"\\newcommand{{\\CorrespondenceAuthorAffiliationZh}}{{{signer_affiliation_zh}}}",
            f"\\newcommand{{\\CorrespondenceAuthorAddress}}{{{signer_addresses}}}",
            f"\\newcommand{{\\ManuscriptID}}{{{_latex_escape(correspondence.manuscript_id)}}}",
            f"\\newcommand{{\\EditorName}}{{{_latex_escape(correspondence.editor_name)}}}",
            f"\\newcommand{{\\EditorTitle}}{{{_latex_escape(correspondence.editor_title)}}}",
            "\\newcommand{\\AuthorAffiliations}{%",
            r"\\".join(affiliation_lines),
            "}",
            "",
        ]
    )


def _nature_name(author: AuthorRecord) -> str:
    parts = author.name_en.split()
    if len(parts) == 1:
        return f"\\sur{{{_latex_escape(parts[0])}}}"
    return (
        f"\\fnm{{{_latex_escape(' '.join(parts[:-1]))}}} "
        f"\\sur{{{_latex_escape(parts[-1])}}}"
    )


def render_publisher_metadata(
    metadata: ManuscriptMetadata,
    selection: AuthorSelection,
) -> str:
    """Render declarations required by the selected publisher class."""
    corresponding = set(selection.corresponding_authors)
    affiliations = {item.affiliation_id: item for item in selection.affiliations}
    title = _latex_escape(metadata.title)
    lines = ["% Generated publisher metadata. Do not edit."]
    if metadata.publisher == "elsevier":
        lines.append(f"\\title{{{title}}}")
        for author in selection.authors:
            labels = ",".join(
                str(selection.affiliation_numbers[key]) for key in author.affiliations
            )
            marker = "\\corref{cor1}" if author in corresponding else ""
            lines.append(
                f"\\author[{labels}]{{{_latex_escape(author.name_en)}{marker}}}"
            )
        emails = "; ".join(
            _latex_escape(item.email) for item in selection.corresponding_authors
        )
        lines.append(f"\\cortext[cor1]{{Corresponding author emails: {emails}.}}")
        for item in selection.affiliations:
            label = selection.affiliation_numbers[item.affiliation_id]
            lines.append(
                f"\\address[{label}]{{{_latex_escape(_affiliation_text(item, 'en'))}}}"
            )
    elif metadata.publisher == "nature":
        lines.append(f"\\title[{title}]{{{title}}}")
        for author in selection.authors:
            labels = ",".join(
                str(selection.affiliation_numbers[key]) for key in author.affiliations
            )
            star = "*" if author in corresponding else ""
            lines.append(f"\\author{star}[{labels}]{{{_nature_name(author)}}}")
            if author in corresponding:
                lines.append(f"\\email{{{_latex_escape(author.email)}}}")
        for item in selection.affiliations:
            label = selection.affiliation_numbers[item.affiliation_id]
            lines.append(
                f"\\affil[{label}]"
                f"{{\\orgname{{{_latex_escape(_affiliation_text(item, 'en'))}}}}}"
            )
    elif metadata.publisher == "acs":
        lines.append(f"\\title{{{title}}}")
        for author in selection.authors:
            lines.append(f"\\author{{{_latex_escape(author.name_en)}}}")
            if author in corresponding:
                lines.append(f"\\email{{{_latex_escape(author.email)}}}")
            for index, key in enumerate(author.affiliations):
                command = "affiliation" if index == 0 else "alsoaffiliation"
                name = _latex_escape(_affiliation_text(affiliations[key], "en"))
                lines.append(f"\\{command}[{name}]{{{name}}}")
    elif metadata.publisher == "chinese":
        labels_en = ", ".join(
            _author_label(item, selection, "en") for item in selection.authors
        )
        labels_zh = "、".join(
            _author_label(item, selection, "zh") for item in selection.authors
        )
        affiliation_en = r"\\".join(
            f"$^{{{selection.affiliation_numbers[item.affiliation_id]}}}$"
            f"{_latex_escape(_affiliation_text(item, 'en'))}"
            for item in selection.affiliations
        )
        affiliation_zh = r"\\".join(
            f"$^{{{selection.affiliation_numbers[item.affiliation_id]}}}$"
            f"{_latex_escape(_affiliation_text(item, 'zh'))}"
            for item in selection.affiliations
        )
        corr_en = "; ".join(
            f"{_latex_escape(item.name_en)}, {_latex_escape(item.email)}"
            for item in selection.corresponding_authors
        )
        corr_zh = "; ".join(
            f"{_latex_escape(item.name_zh)}, {_latex_escape(item.email)}"
            for item in selection.corresponding_authors
        )
        lines.extend(
            [
                f"\\title{{{title}}}",
                f"\\entitle{{{title}}}",
                f"\\author{{{labels_zh}}}",
                f"\\enauthor{{{labels_en}}}",
                f"\\affiliation{{{affiliation_zh}}}",
                f"\\enaffiliation{{{affiliation_en}}}",
                f"\\corrauthorcn{{{corr_zh}}}",
                f"\\corrauthoren{{{corr_en}}}",
            ]
        )
    return "\n".join((*lines, ""))


def generate_metadata(
    manuscript_root: Path,
    round_dir: Path,
    target_dir: Path,
) -> AuthorSelection:
    """Generate ephemeral LaTeX metadata inside an isolated build directory."""
    metadata = load_meta(round_dir / "meta.yaml")
    library = load_author_library(manuscript_root / "references" / "authors.yaml")
    selection = resolve_authors(metadata, library)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "author_metadata.tex").write_text(
        render_author_metadata(metadata, selection), encoding="utf-8"
    )
    (target_dir / "publisher_metadata.tex").write_text(
        render_publisher_metadata(metadata, selection), encoding="utf-8"
    )
    return selection


# Internal migration aliases; the public format is ``meta.yaml``.
load_manuscript = load_meta
save_manuscript = save_meta
