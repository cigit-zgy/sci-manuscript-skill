"""Validate project metadata and render shared LaTeX author commands."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .rounds import round_directory_name, round_name


class MetadataError(RuntimeError):
    """Raised when manuscript or author-library metadata is invalid."""


try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - environment boundary
    raise MetadataError(
        "PyYAML is required. Install the dependencies declared in pyproject.toml."
    ) from exc


PUBLISHER_TEMPLATES = {
    "elsevier": "elsarticle",
    "nature": "sn-jnl",
    "acs": "achemso",
    "chinese": "kxtbcas",
}
PUBLISHERS = tuple(PUBLISHER_TEMPLATES)
CURRENT_PROJECT_FORMAT = 1


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
    journal_template: str
    round_number: int
    parent_round: int | None
    submission: SubmissionSettings
    first_authors: tuple[str, ...]
    corresponding_authors: tuple[str, ...]
    authors: tuple[str, ...]
    format_version: int = CURRENT_PROJECT_FORMAT
    created_with: str = "0+unknown"

    @property
    def author_names(self) -> tuple[str, ...]:
        """Return publication order without duplicating role overlaps."""
        ordered = (*self.first_authors, *self.authors, *self.corresponding_authors)
        return tuple(dict.fromkeys(ordered))


@dataclass(frozen=True)
class AuthorSelection:
    """Resolved authors and corresponding author for one manuscript version."""

    authors: tuple[AuthorRecord, ...]
    affiliations: tuple[AffiliationRecord, ...]
    first_authors: tuple[AuthorRecord, ...]
    corresponding_authors: tuple[AuthorRecord, ...]


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


def _optional_text(value: Any, location: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MetadataError(f"{location} must be a string when provided.")
    return value.strip()


def _boolean(value: Any, location: str) -> bool:
    if not isinstance(value, bool):
        raise MetadataError(f"{location} must be true or false.")
    return value


def _round_number(value: Any, location: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.startswith("r"):
        raise MetadataError(f"{location} must be null or a round such as r01.")
    suffix = value[1:]
    if not suffix.isdigit():
        raise MetadataError(f"{location} must be null or a round such as r01.")
    return int(suffix)


def _author_group(value: Any, location: str, required: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (required and not value):
        requirement = "a non-empty list" if required else "a list"
        raise MetadataError(f"{location} must be {requirement} of author names.")
    names = tuple(
        _text(item, f"{location}[{index}]") for index, item in enumerate(value)
    )
    if len(set(names)) != len(names):
        raise MetadataError(f"{location} must not contain duplicate names.")
    return names


def _revision_directory(value: Any, location: str) -> int | None:
    if value is None:
        return None
    name = _text(value, location)
    if name == "initial_submission":
        return 0
    prefix = "revision_"
    if not name.startswith(prefix) or not name[len(prefix) :].isdigit():
        raise MetadataError(
            f"{location} must be null, initial_submission, or revision_01."
        )
    number = int(name[len(prefix) :])
    if number < 1:
        raise MetadataError(f"{location} must not use revision_0.")
    return number


def load_manuscript(path: Path) -> ManuscriptMetadata:
    """Load and validate one version's ``manuscript.yaml``."""
    data = _read_yaml(path)
    expected = {
        "workflow",
        "manuscript",
        "journal",
        "revision",
        "submission",
        "authors",
    }
    unexpected = set(data) - expected
    if unexpected:
        raise MetadataError(
            f"Unsupported manuscript.yaml keys: {', '.join(sorted(unexpected))}."
        )
    raw_workflow = data.get("workflow")
    if raw_workflow is None:
        format_version = 0
        created_with = ""
    else:
        workflow = _mapping(raw_workflow, "workflow")
        raw_format = workflow.get("format_version")
        if isinstance(raw_format, bool) or not isinstance(raw_format, int):
            raise MetadataError("workflow.format_version must be an integer.")
        if raw_format < 1:
            raise MetadataError("workflow.format_version must be at least 1.")
        if raw_format > CURRENT_PROJECT_FORMAT:
            raise MetadataError(
                "Project format "
                f"{raw_format} is newer than supported format "
                f"{CURRENT_PROJECT_FORMAT}; refusing to downgrade."
            )
        format_version = raw_format
        created_with = _text(workflow.get("created_with"), "workflow.created_with")
    manuscript = _mapping(data.get("manuscript"), "manuscript")
    journal = _mapping(data.get("journal"), "journal")
    revision = _mapping(data.get("revision"), "revision")
    submission = _mapping(data.get("submission"), "submission")
    current = _round_number(revision.get("round"), "revision.round")
    if current is None:
        raise MetadataError("revision.round cannot be null.")
    declared_name = _revision_directory(revision.get("name"), "revision.name")
    if declared_name != current:
        raise MetadataError(
            f"revision.name does not match revision.round: {round_name(current)}."
        )
    parent = _revision_directory(revision.get("parent"), "revision.parent")
    if current == 0 and parent is not None:
        raise MetadataError("R0 must have revision.parent: null.")
    if current > 0 and parent != current - 1:
        raise MetadataError(
            f"{round_name(current)} must declare revision.parent: "
            f"{round_name(current - 1)}."
        )
    language = _text(manuscript.get("language"), "manuscript.language")
    if language not in {"en", "zh"}:
        raise MetadataError("manuscript.language must be en or zh.")
    publisher = _text(journal.get("publisher"), "journal.publisher").lower()
    if publisher not in PUBLISHERS:
        available = ", ".join(PUBLISHERS)
        raise MetadataError(f"journal.publisher must be one of: {available}.")
    journal_template = _text(journal.get("template"), "journal.template")
    expected_template = PUBLISHER_TEMPLATES[publisher]
    if journal_template != expected_template:
        raise MetadataError(
            f"journal.template must be {expected_template!r} for {publisher}."
        )
    author_groups = _mapping(data.get("authors"), "authors")
    return ManuscriptMetadata(
        title=_text(manuscript.get("title"), "manuscript.title"),
        article_type=_text(manuscript.get("article_type"), "manuscript.article_type"),
        language=language,
        journal_name=_text(journal.get("name"), "journal.name"),
        publisher=publisher,
        journal_template=journal_template,
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
        first_authors=_author_group(
            author_groups.get("first_authors"),
            "authors.first_authors",
            required=True,
        ),
        corresponding_authors=_author_group(
            author_groups.get("corresponding_authors"),
            "authors.corresponding_authors",
            required=True,
        ),
        authors=_author_group(
            author_groups.get("authors"),
            "authors.authors",
            required=False,
        ),
        format_version=format_version,
        created_with=created_with,
    )


def render_manuscript(metadata: ManuscriptMetadata) -> str:
    """Render one annotated deterministic manuscript configuration."""
    sections = (
        (
            "Workflow format",
            {
                "workflow": {
                    "format_version": metadata.format_version,
                    "created_with": metadata.created_with,
                }
            },
        ),
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
                    "template": metadata.journal_template,
                }
            },
        ),
        (
            "Revision",
            {
                "revision": {
                    "name": round_directory_name(metadata.round_number),
                    "parent": (
                        None
                        if metadata.parent_round is None
                        else round_directory_name(metadata.parent_round)
                    ),
                    "round": round_name(metadata.round_number),
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
        (
            "Authors",
            {
                "authors": {
                    "first_authors": list(metadata.first_authors),
                    "corresponding_authors": list(metadata.corresponding_authors),
                    "authors": list(metadata.authors),
                }
            },
        ),
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
    return "\n".join(pieces)


def save_manuscript(path: Path, metadata: ManuscriptMetadata) -> None:
    """Atomically write an annotated deterministic manuscript configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.new")
    temporary.write_text(render_manuscript(metadata), encoding="utf-8")
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
        if role not in {"author", "first_author", "corresponding_author"}:
            raise MetadataError(
                f"authors.{name}.role must be author, first_author, or "
                "corresponding_author."
            )
        raw_keys = record.get("affiliations")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise MetadataError(
                f"authors.{name}.affiliations must be a non-empty list."
            )
        authors[name] = AuthorRecord(
            name=_text(record.get("name_en", name), f"authors.{name}.name_en"),
            name_zh=_text(record.get("name_zh", name), f"authors.{name}.name_zh"),
            email=_optional_text(record.get("email"), f"authors.{name}.email"),
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
    first = tuple(library.authors[name] for name in metadata.first_authors)
    corresponding = tuple(
        library.authors[name] for name in metadata.corresponding_authors
    )
    missing_emails = [author.name for author in corresponding if not author.email]
    if missing_emails:
        raise MetadataError(
            "Corresponding authors must have email addresses: "
            + ", ".join(missing_emails)
        )
    used_keys = {key for author in authors for key in author.affiliations}
    affiliations = tuple(
        record for record in library.affiliations if record.key in used_keys
    )
    return AuthorSelection(authors, affiliations, first, corresponding)


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


def _author_label(
    author: AuthorRecord,
    language: str,
    corresponding_names: set[str],
) -> str:
    markers = list(author.affiliations)
    if author.name in corresponding_names:
        markers.append("*")
    name = author.name_zh if language == "zh" else author.name
    return f"{_latex_escape(name)}$^{{{','.join(markers)}}}$"


def render_author_metadata(
    metadata: ManuscriptMetadata,
    selection: AuthorSelection,
) -> str:
    """Render shared correspondence macros without publisher commands."""
    names_en = ", ".join(_latex_escape(item.name) for item in selection.authors)
    names_zh = "、".join(_latex_escape(item.name_zh) for item in selection.authors)
    first_names = ", ".join(
        _latex_escape(item.name) for item in selection.first_authors
    )
    corresponding_names = ", ".join(
        _latex_escape(item.name) for item in selection.corresponding_authors
    )
    corresponding_names_zh = "、".join(
        _latex_escape(item.name_zh) for item in selection.corresponding_authors
    )
    corresponding_emails = "; ".join(
        _latex_escape(item.email) for item in selection.corresponding_authors
    )
    affiliation_lines = [
        f"$^{{{item.key}}}${_latex_escape(item.name_en)}, {_latex_escape(item.address)}"
        for item in selection.affiliations
    ]
    return "\n".join(
        [
            "% Generated from manuscript.yaml and authors.yaml. Do not edit.",
            f"\\newcommand{{\\ManuscriptTitle}}{{{_latex_escape(metadata.title)}}}",
            f"\\newcommand{{\\JournalName}}{{{_latex_escape(metadata.journal_name)}}}",
            f"\\newcommand{{\\ArticleType}}{{{_latex_escape(metadata.article_type)}}}",
            f"\\newcommand{{\\SelectedAuthorNames}}{{{names_en}}}",
            f"\\newcommand{{\\SelectedAuthorNamesZh}}{{{names_zh}}}",
            f"\\newcommand{{\\FirstAuthorNames}}{{{first_names}}}",
            f"\\newcommand{{\\CorrespondingAuthorName}}{{{corresponding_names}}}",
            f"\\newcommand{{\\CorrespondingAuthorNameZh}}{{{corresponding_names_zh}}}",
            f"\\newcommand{{\\CorrespondingAuthorEmail}}{{{corresponding_emails}}}",
            "\\newcommand{\\AuthorAffiliations}{%",
            r"\\\n".join(affiliation_lines),
            "}",
            "",
        ]
    )


def _nature_name(author: AuthorRecord) -> str:
    parts = author.name.split()
    if len(parts) == 1:
        return f"\\sur{{{_latex_escape(parts[0])}}}"
    given = _latex_escape(" ".join(parts[:-1]))
    family = _latex_escape(parts[-1])
    return f"\\fnm{{{given}}} \\sur{{{family}}}"


def render_publisher_metadata(
    metadata: ManuscriptMetadata,
    selection: AuthorSelection,
) -> str:
    """Render declarations required by the selected publisher class."""
    corresponding = {item.name for item in selection.corresponding_authors}
    affiliations = {item.key: item for item in selection.affiliations}
    lines = ["% Generated publisher metadata. Do not edit."]
    title = _latex_escape(metadata.title)
    if metadata.publisher == "elsevier":
        lines.append(f"\\title{{{title}}}")
        for author in selection.authors:
            labels = ",".join(author.affiliations)
            marker = "\\corref{cor1}" if author.name in corresponding else ""
            lines.append(f"\\author[{labels}]{{{_latex_escape(author.name)}{marker}}}")
        emails = "; ".join(
            _latex_escape(author.email) for author in selection.corresponding_authors
        )
        lines.append(f"\\cortext[cor1]{{Corresponding author emails: {emails}.}}")
        for item in selection.affiliations:
            lines.append(
                f"\\address[{item.key}]{{{_latex_escape(item.name_en)}, "
                f"{_latex_escape(item.address)}}}"
            )
    elif metadata.publisher == "nature":
        lines.append(f"\\title[{title}]{{{title}}}")
        for author in selection.authors:
            labels = ",".join(author.affiliations)
            star = "*" if author.name in corresponding else ""
            lines.append(f"\\author{star}[{labels}]{{{_nature_name(author)}}}")
            if author.name in corresponding:
                lines.append(f"\\email{{{_latex_escape(author.email)}}}")
        for item in selection.affiliations:
            lines.append(
                f"\\affil[{item.key}]{{\\orgname{{{_latex_escape(item.name_en)}}}, "
                f"\\orgaddress{{\\street{{{_latex_escape(item.address)}}}}}}}"
            )
    elif metadata.publisher == "acs":
        lines.append(f"\\title{{{title}}}")
        for author in selection.authors:
            lines.append(f"\\author{{{_latex_escape(author.name)}}}")
            if author.name in corresponding:
                lines.append(f"\\email{{{_latex_escape(author.email)}}}")
            for index, key in enumerate(author.affiliations):
                item = affiliations[key]
                command = "affiliation" if index == 0 else "alsoaffiliation"
                lines.append(
                    f"\\{command}[{_latex_escape(item.name_en)}]"
                    f"{{{_latex_escape(item.name_en)}, {_latex_escape(item.address)}}}"
                )
    else:
        labels_en = ", ".join(
            _author_label(item, "en", corresponding) for item in selection.authors
        )
        labels_zh = "、".join(
            _author_label(item, "zh", corresponding) for item in selection.authors
        )
        affiliation_text = r"\\".join(
            f"$^{{{item.key}}}${_latex_escape(item.name_en)}, "
            f"{_latex_escape(item.address)}"
            for item in selection.affiliations
        )
        corr_en = "; ".join(
            f"{_latex_escape(item.name)}, {_latex_escape(item.email)}"
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
                f"\\affiliation{{{affiliation_text}}}",
                f"\\enaffiliation{{{affiliation_text}}}",
                f"\\corrauthorcn{{{corr_zh}}}",
                f"\\corrauthoren{{{corr_en}}}",
            ]
        )
    return "\n".join((*lines, ""))


def generate_author_metadata(project: Path, round_dir: Path) -> AuthorSelection:
    """Generate shared metadata from one version YAML and root references."""
    metadata = load_manuscript(round_dir / "manuscript.yaml")
    references = project / "references"
    library = load_author_library(references / "authors.yaml")
    selection = resolve_authors(metadata, library)
    outputs = {
        references / "author_metadata.tex": render_author_metadata(metadata, selection),
        references / "publisher_metadata.tex": render_publisher_metadata(
            metadata, selection
        ),
    }
    for target, text in outputs.items():
        temporary = target.with_suffix(".tex.new")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
    return selection
