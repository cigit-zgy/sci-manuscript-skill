"""Reusable author-library configuration, validation, and role resolution."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .errors import MetadataError

if TYPE_CHECKING:
    from .metadata import ManuscriptMetadata

CONFIG_DIRECTORY_ENV = "SCI_MANUSCRIPT_CONFIG_DIR"


@dataclass(frozen=True)
class AuthorRecord:
    """One author from the manuscript-level author library."""

    author_id: str
    name_zh: str
    name_en: str
    email: str
    affiliations: tuple[str, ...]
    bio_zh: str = ""
    bio_en: str = ""
    correspondence_address: str = ""


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
    source: Path


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


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MetadataError(f"YAML file is missing: {path}")
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
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


def resolve_author_library_path() -> Path:
    """Resolve the configured user library or bundled public author data."""
    configured = configured_author_library_path()
    if configured.is_file():
        return configured
    bundled = Path(str(files("sci_manuscript") / "resources" / "authors.yaml"))
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
            _text(record.get("name_en"), f"affiliations.{affiliation_id}.name_en"),
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
            "bio_zh",
            "bio_en",
            "correspondence_address",
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
            author_id=author_id,
            name_zh=_text(record.get("name_zh"), f"authors.{author_id}.name_zh"),
            name_en=_text(record.get("name_en"), f"authors.{author_id}.name_en"),
            email=_text(
                record.get("email"), f"authors.{author_id}.email", optional=True
            ),
            affiliations=keys,
            bio_zh=_text(
                record.get("bio_zh"), f"authors.{author_id}.bio_zh", optional=True
            ),
            bio_en=_text(
                record.get("bio_en"), f"authors.{author_id}.bio_en", optional=True
            ),
            correspondence_address=_text(
                record.get("correspondence_address"),
                f"authors.{author_id}.correspondence_address",
                optional=True,
            ),
        )
    if not authors:
        raise MetadataError("authors must not be empty.")
    return AuthorLibrary(authors, affiliations, path.resolve())


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
            "Selected author IDs are missing from the active author library: "
            + ", ".join(missing)
        )
    selected = tuple(library.authors[item] for item in metadata.author_ids)
    corresponding_ids = set(metadata.corresponding_authors)
    corresponding = tuple(
        author for author in selected if author.author_id in corresponding_ids
    )
    for author in corresponding:
        if not author.email:
            raise MetadataError(
                f'Missing email for corresponding author "{author.name_en}". '
                f"Source: author metadata ({library.source}). Missing field: email."
            )
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
