"""Validate project metadata and render publisher-specific author commands."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from . import authors as author_data
from .errors import MetadataError
from .tex import command_at, extract_braced, is_escaped

__all__ = [
    "CorrespondenceSettings",
    "ManuscriptMetadata",
    "MetadataError",
    "SubmissionSettings",
    "load_meta",
]

PUBLISHERS = ("elsevier", "nature", "acs", "chinese", "custom")
PUBLISHER_LANGUAGES = {
    "chinese": "zh",
    "elsevier": "en",
    "nature": "en",
    "acs": "en",
}
ROUND_PATTERN = re.compile(r"^r(\d{2,})$")


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
    """Workflow configuration for one manuscript version."""

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
    title_zh: str = ""
    title_en: str = ""
    abstract_zh: str = ""
    abstract_en: str = ""
    keywords_zh: str = ""
    keywords_en: str = ""
    funding: tuple[str, ...] = ()
    author_biographies: tuple[str, ...] = ()

    @property
    def author_ids(self) -> tuple[str, ...]:
        """Return publication order while preserving permitted role overlap."""
        ordered = (
            *self.first_authors,
            *self.other_authors,
            *self.corresponding_authors,
        )
        return tuple(dict.fromkeys(ordered))

    def localized_title(self, language: str) -> str:
        """Return the requested title with the initialization scalar as default."""
        preferred = self.title_zh if language == "zh" else self.title_en
        alternate = self.title_en if language == "zh" else self.title_zh
        return preferred or self.title or alternate


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


def _text_group(value: Any, location: str) -> tuple[str, ...]:
    """Return one duplicate-free list of non-empty text values."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise MetadataError(f"{location} must be a list.")
    items = tuple(
        _text(item, f"{location}[{index}]") for index, item in enumerate(value)
    )
    if len(items) != len(set(items)):
        raise MetadataError(f"{location} must not contain duplicate values.")
    return items


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


def validate_publisher_language(publisher: str, language: str) -> None:
    """Reject publisher and language combinations outside the release matrix."""
    if publisher == "custom":
        return
    required_language = PUBLISHER_LANGUAGES[publisher]
    if language != required_language:
        raise MetadataError(
            f"selected publisher={publisher!r}, selected language={language!r}; "
            f"accepted language: {required_language}."
        )


def load_meta(path: Path) -> ManuscriptMetadata:
    """Load and validate one version's ``meta.yaml``."""
    data = _read_yaml(path)
    expected = {
        "revision",
        "manuscript",
        "journal",
        "authors",
        "frontmatter",
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
    unexpected_manuscript = set(manuscript) - {"language", "article_type"}
    if unexpected_manuscript:
        raise MetadataError(
            "Unsupported manuscript keys: " + ", ".join(sorted(unexpected_manuscript))
        )
    journal = _mapping(data.get("journal"), "journal")
    authors = _mapping(data.get("authors"), "authors")
    frontmatter = _mapping(data.get("frontmatter", {}), "frontmatter")
    unexpected_frontmatter = set(frontmatter) - {
        "funding",
        "author_biographies",
    }
    if unexpected_frontmatter:
        raise MetadataError(
            "Unsupported frontmatter keys: " + ", ".join(sorted(unexpected_frontmatter))
        )
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
    validate_publisher_language(publisher, language)
    funding = _text_group(frontmatter.get("funding"), "frontmatter.funding")
    author_biographies = _author_group(
        frontmatter.get("author_biographies", []),
        "frontmatter.author_biographies",
        required=False,
    )
    unexpected_authors = set(authors) - {"first", "corresponding", "other"}
    if unexpected_authors:
        legacy = unexpected_authors & {
            "first_author",
            "corresponding_author",
            "other_author",
        }
        if legacy:
            raise MetadataError(
                "Detected a v1 workspace author schema while running 2.0. "
                "Archive the workspace before migration and read the CHANGELOG "
                "and workflow migration section."
            )
        raise MetadataError(
            "Canonical authors schema contains unsupported keys: "
            + ", ".join(sorted(unexpected_authors))
        )
    first_authors = _author_group(authors.get("first"), "authors.first", required=True)
    corresponding_authors = _author_group(
        authors.get("corresponding"),
        "authors.corresponding",
        required=True,
    )
    other_authors = _author_group(
        authors.get("other", []), "authors.other", required=False
    )
    duplicate_roles = set(first_authors) & set(other_authors)
    if duplicate_roles:
        raise MetadataError(
            "authors.first and authors.other must not overlap: "
            + ", ".join(sorted(duplicate_roles))
        )
    unknown_biographies = set(author_biographies) - {
        *first_authors,
        *corresponding_authors,
    }
    if unknown_biographies:
        raise MetadataError(
            "frontmatter.author_biographies must reference first or "
            "corresponding authors: " + ", ".join(sorted(unknown_biographies))
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
            and correspondence.signing_author not in corresponding_authors
        ):
            raise MetadataError(
                "correspondence.signing_author must be a corresponding author."
            )
    return ManuscriptMetadata(
        title="",
        article_type=_text(manuscript.get("article_type"), "manuscript.article_type"),
        language=language,
        journal_name=_text(journal.get("name"), "journal.name"),
        publisher=publisher,
        round_number=current,
        parent_round=parent,
        first_authors=first_authors,
        corresponding_authors=corresponding_authors,
        other_authors=other_authors,
        submission=submission,
        correspondence=correspondence,
        funding=funding,
        author_biographies=author_biographies,
    )


def _metadata_data(metadata: ManuscriptMetadata) -> dict[str, Any]:
    """Return the canonical editable metadata mapping."""
    manuscript: dict[str, Any] = {
        "language": metadata.language,
        "article_type": metadata.article_type,
    }
    authors = {
        "first": list(metadata.first_authors),
        "corresponding": list(metadata.corresponding_authors),
        "other": list(metadata.other_authors),
    }
    return {
        "revision": {
            "round": round_name(metadata.round_number),
            "name": revision_directory_name(metadata.round_number),
            "parent": (
                None
                if metadata.parent_round is None
                else round_name(metadata.parent_round)
            ),
        },
        "manuscript": manuscript,
        "journal": {
            "name": metadata.journal_name,
            "publisher": metadata.publisher,
        },
        "authors": authors,
        "frontmatter": {
            "funding": list(metadata.funding),
            "author_biographies": list(metadata.author_biographies),
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


def _update_commented_mapping(
    target: CommentedMap,
    values: dict[str, Any],
) -> None:
    """Update known values without replacing comments or mapping order."""
    for key, value in values.items():
        if isinstance(value, dict):
            nested = target.get(key)
            if not isinstance(nested, CommentedMap):
                nested = CommentedMap()
                target[key] = nested
            _update_commented_mapping(nested, value)
        else:
            target[key] = value


def _add_meta_comments(data: CommentedMap) -> None:
    """Annotate a newly created user metadata file."""
    data.yaml_set_start_comment(
        "Editable manuscript configuration. Build commands read this file but do "
        "not rewrite it."
    )
    revision = data["revision"]
    revision.yaml_set_comment_before_after_key(
        "round", before="Lifecycle round; managed only by revision/reindex operations."
    )
    manuscript = data["manuscript"]
    manuscript.yaml_set_comment_before_after_key(
        "language", before="Manuscript language: en or zh."
    )
    manuscript.yaml_set_comment_before_after_key(
        "article_type", before="Journal article type, for example Perspective."
    )
    journal = data["journal"]
    journal.yaml_set_comment_before_after_key(
        "name", before="Target journal name used in correspondence."
    )
    journal.yaml_set_comment_before_after_key(
        "publisher",
        before="Packaged publisher resource key: chinese, elsevier, nature, or acs.",
    )
    authors = data["authors"]
    authors.yaml_set_comment_before_after_key(
        "first", before="First-author IDs from the active authors.yaml."
    )
    authors.yaml_set_comment_before_after_key(
        "corresponding",
        before="Corresponding-author IDs; email is required in authors.yaml.",
    )
    authors.yaml_set_comment_before_after_key(
        "other", before="Remaining author IDs in publication order."
    )
    frontmatter = data["frontmatter"]
    frontmatter.yaml_set_comment_before_after_key(
        "funding", before="Funding acknowledgements rendered by the publisher class."
    )
    frontmatter.yaml_set_comment_before_after_key(
        "author_biographies",
        before="Author IDs whose bilingual biographies appear in frontmatter.",
    )


def save_meta(path: Path, metadata: ManuscriptMetadata) -> None:
    """Atomically update metadata while preserving user YAML comments."""
    yaml_round_trip = YAML(typ="rt")
    yaml_round_trip.preserve_quotes = True
    yaml_round_trip.width = 1000
    yaml_round_trip.indent(mapping=2, sequence=4, offset=2)
    is_new = not path.exists()
    if is_new:
        document = CommentedMap()
    else:
        try:
            loaded = yaml_round_trip.load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise MetadataError(f"Cannot preserve metadata YAML: {path}") from exc
        if not isinstance(loaded, CommentedMap):
            raise MetadataError(f"Metadata root must be a mapping: {path}")
        document = loaded
    _update_commented_mapping(document, _metadata_data(metadata))
    if is_new:
        _add_meta_comments(document)
    buffer = StringIO()
    yaml_round_trip.dump(document, buffer)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.new")
    temporary.write_text(buffer.getvalue(), encoding="utf-8")
    os.replace(temporary, path)


def write_meta_template(path: Path) -> None:
    """Create an intentionally incomplete, commented metadata draft."""
    text = """# Edit every required value before the first build.
revision:
  # Lifecycle state; do not edit during normal manuscript work.
  round: r00
  name: initial_submission
  parent: null
manuscript:
  # Required: en or zh.
  language:
  # Required journal article type.
  article_type:
journal:
  # Required target journal name.
  name:
  # Required packaged publisher key: chinese, elsevier, nature, or acs.
  publisher:
authors:
  # First-author IDs from the active authors.yaml.
  first: []
  # Corresponding-author IDs; IDs may also occur under first or other.
  corresponding: []
  # Remaining author IDs in publication order.
  other: []
frontmatter:
  # Funding acknowledgements; leave the list empty when not applicable.
  funding: []
  # Author IDs whose bilingual biographies should appear in frontmatter.
  author_biographies: []
submission:
  cover_letter: true
  highlights: true
  graphical_abstract: true
correspondence:
  manuscript_id:
  editor_name:
  editor_title:
  signing_author:
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.new")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def with_revision(
    metadata: ManuscriptMetadata,
    round_number: int,
) -> ManuscriptMetadata:
    """Return the direct child metadata while preserving all editable fields."""
    return replace(metadata, round_number=round_number, parent_round=round_number - 1)


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


def _frontmatter_field(text: str, command: str) -> str:
    """Return one plain title field from a canonical frontmatter command."""
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        if command_at(text, cursor, command):
            try:
                raw, _ = extract_braced(text, cursor + len(command) + 1)
            except ValueError as exc:
                raise MetadataError(
                    f"Unbalanced \\{command} field in manuscript frontmatter."
                ) from exc
            clean_lines: list[str] = []
            for line in raw.splitlines():
                comment = next(
                    (
                        index
                        for index, character in enumerate(line)
                        if character == "%" and not is_escaped(line, index)
                    ),
                    len(line),
                )
                clean_lines.append(line[:comment].strip())
            return " ".join(part for part in clean_lines if part)
        cursor += 1
    return ""


def _metadata_with_frontmatter_title(
    metadata: ManuscriptMetadata,
    round_dir: Path,
) -> ManuscriptMetadata:
    """Load user-owned title fields from the round frontmatter source."""
    source = round_dir / "sections" / "00_frontmatter.tex"
    if not source.is_file():
        return metadata
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MetadataError(f"Cannot read manuscript frontmatter: {source}") from exc
    title_zh = _frontmatter_field(text, "title") if metadata.language == "zh" else ""
    title_en = (
        _frontmatter_field(text, "entitle")
        if metadata.language == "zh"
        else _frontmatter_field(text, "title")
    )
    title = title_zh if metadata.language == "zh" else title_en
    return replace(
        metadata,
        title=title or metadata.title,
        title_zh=title_zh or metadata.title_zh,
        title_en=title_en or metadata.title_en,
    )


def _author_label(
    author: author_data.AuthorRecord,
    selection: author_data.AuthorSelection,
    language: str,
) -> str:
    markers = [str(selection.affiliation_numbers[key]) for key in author.affiliations]
    if author in selection.corresponding_authors:
        markers.append("*")
    name = author.name_zh if language == "zh" else author.name_en
    return f"{_latex_escape(name)}$^{{{','.join(markers)}}}$"


def _affiliation_text(affiliation: author_data.AffiliationRecord, language: str) -> str:
    """Render one affiliation without inventing unavailable translations."""
    name = (
        affiliation.name_zh
        if language == "zh" and affiliation.name_zh
        else affiliation.name_en
    )
    return ", ".join(part for part in (name, affiliation.address) if part)


def _correspondence_address(
    author: author_data.AuthorRecord,
    affiliations: dict[str, author_data.AffiliationRecord],
    language: str,
) -> str:
    """Resolve one correspondence address from explicit metadata or affiliation 1."""
    if author.correspondence_address:
        return author.correspondence_address
    first_id = author.affiliations[0] if author.affiliations else ""
    first_affiliation = affiliations.get(first_id)
    if first_affiliation is not None:
        address = _affiliation_text(first_affiliation, language)
        if address:
            return address
    raise MetadataError(
        f'Missing correspondence address for corresponding author "{author.name_en}".'
    )


def _render_correspondence_blocks(
    selection: author_data.AuthorSelection,
    language: str,
) -> str:
    """Render ordered response-letter blocks with component-local spacing."""
    affiliations = {
        affiliation.affiliation_id: affiliation
        for affiliation in selection.affiliations
    }
    blocks: list[str] = []
    for author in selection.corresponding_authors:
        name = author.name_zh if language == "zh" else author.name_en
        address = _correspondence_address(author, affiliations, language)
        address_label = (
            "通讯地址："  # noqa: RUF001 - required Chinese response label
            if language == "zh"
            else "Correspondence address: "
        )
        email_label = "邮箱：" if language == "zh" else "E-mail: "  # noqa: RUF001
        email = _latex_escape(author.email)
        blocks.append(
            "\n".join(
                (
                    f"{_latex_escape(name)}\\par",
                    r"\vspace{0.15\baselineskip}",
                    f"{address_label}{_latex_escape(address)}\\par",
                    r"\vspace{0.15\baselineskip}",
                    f"{email_label}\\href{{mailto:{email}}}{{{email}}}",
                )
            )
        )
    return "\n\\par\\vspace{0.55\\baselineskip}\n".join(blocks)


def render_author_metadata(
    metadata: ManuscriptMetadata,
    selection: author_data.AuthorSelection,
) -> str:
    """Render shared correspondence macros."""
    names_en = ", ".join(_latex_escape(item.name_en) for item in selection.authors)
    names_zh = "，".join(  # noqa: RUF001 - intentional Chinese author separator
        _latex_escape(item.name_zh) for item in selection.authors
    )
    first_names = ", ".join(
        _latex_escape(item.name_en) for item in selection.first_authors
    )
    corresponding_names = ", ".join(
        _latex_escape(item.name_en) for item in selection.corresponding_authors
    )
    corresponding_names_zh = "，".join(  # noqa: RUF001
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
    signer = author_data.resolve_signing_author(metadata, selection)
    affiliations_by_id = {
        affiliation.affiliation_id: affiliation
        for affiliation in selection.affiliations
    }
    correspondence_blocks_en = _render_correspondence_blocks(selection, "en")
    correspondence_blocks_zh = _render_correspondence_blocks(selection, "zh")
    signer_affiliations = (
        tuple(affiliations_by_id[key] for key in signer.affiliations)
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
            f"\\newcommand{{\\ManuscriptTitle}}{{{_latex_escape(metadata.localized_title(metadata.language))}}}",
            f"\\newcommand{{\\JournalName}}{{{_latex_escape(metadata.journal_name)}}}",
            f"\\newcommand{{\\ArticleType}}{{{_latex_escape(metadata.article_type)}}}",
            f"\\newcommand{{\\SelectedAuthorNames}}{{{names_en}}}",
            f"\\newcommand{{\\SelectedAuthorNamesZh}}{{{names_zh}}}",
            f"\\newcommand{{\\FirstAuthorNames}}{{{first_names}}}",
            f"\\newcommand{{\\CorrespondingAuthorName}}{{{corresponding_names}}}",
            f"\\newcommand{{\\CorrespondingAuthorNameZh}}{{{corresponding_names_zh}}}",
            f"\\newcommand{{\\CorrespondingAuthorEmail}}{{{emails}}}",
            "\\newcommand{\\CorrespondenceAuthorsEn}{%",
            correspondence_blocks_en,
            "}",
            "\\newcommand{\\CorrespondenceAuthorsZh}{%",
            correspondence_blocks_zh,
            "}",
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


def _nature_name(author: author_data.AuthorRecord) -> str:
    parts = author.name_en.split()
    if len(parts) == 1:
        return f"\\sur{{{_latex_escape(parts[0])}}}"
    return (
        f"\\fnm{{{_latex_escape(' '.join(parts[:-1]))}}} "
        f"\\sur{{{_latex_escape(parts[-1])}}}"
    )


def render_publisher_metadata(
    metadata: ManuscriptMetadata,
    selection: author_data.AuthorSelection,
) -> str:
    """Render declarations required by the selected publisher class."""
    corresponding = set(selection.corresponding_authors)
    affiliations = {item.affiliation_id: item for item in selection.affiliations}
    lines = ["% Generated publisher metadata. Do not edit."]
    if metadata.publisher == "elsevier":
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
        labels_zh = "，".join(  # noqa: RUF001 - intentional Chinese punctuation
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

        def biography(author: author_data.AuthorRecord, language: str) -> str:
            bio = author.bio_zh if language == "zh" else author.bio_en
            if bio:
                return _latex_escape(bio)
            name = author.name_zh if language == "zh" else author.name_en
            escaped_name = _latex_escape(name)
            if not author.email:
                return escaped_name
            return f"{escaped_name}, {_latex_escape(author.email)}"

        selected_biographies = set(metadata.author_biographies)
        first_biographies = tuple(
            item
            for item in selection.first_authors
            if item.author_id in selected_biographies
        )
        corresponding_biographies = tuple(
            item
            for item in selection.corresponding_authors
            if item.author_id in selected_biographies
        )
        first_zh = "; ".join(biography(item, "zh") for item in first_biographies)
        first_en = "; ".join(biography(item, "en") for item in first_biographies)
        corr_zh = "; ".join(biography(item, "zh") for item in corresponding_biographies)
        corr_en = "; ".join(biography(item, "en") for item in corresponding_biographies)
        lines.extend(
            [
                f"\\author{{{labels_zh}}}",
                f"\\enauthor{{{labels_en}}}",
                f"\\affiliation{{{affiliation_zh}}}",
                f"\\enaffiliation{{{affiliation_en}}}",
                f"\\firstauthorcn{{{first_zh}}}",
                f"\\firstauthoren{{{first_en}}}",
                f"\\corrauthorcn{{{corr_zh}}}",
                f"\\corrauthoren{{{corr_en}}}",
            ]
        )
        if metadata.funding:
            separator = "；" if metadata.language == "zh" else "; "  # noqa: RUF001
            funding = separator.join(_latex_escape(item) for item in metadata.funding)
            lines.append(f"\\funding{{{funding}}}")
    return "\n".join((*lines, ""))


def generate_metadata(
    round_dir: Path,
    target_dir: Path,
) -> author_data.AuthorSelection:
    """Generate ephemeral LaTeX metadata inside an isolated build directory."""
    metadata = _metadata_with_frontmatter_title(
        load_meta(round_dir / "meta.yaml"),
        round_dir,
    )
    library = author_data.load_author_library(author_data.resolve_author_library_path())
    selection = author_data.resolve_authors(metadata, library)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "author_metadata.tex").write_text(
        render_author_metadata(metadata, selection), encoding="utf-8"
    )
    (target_dir / "publisher_metadata.tex").write_text(
        render_publisher_metadata(metadata, selection), encoding="utf-8"
    )
    return selection
