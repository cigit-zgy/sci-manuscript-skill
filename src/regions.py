"""Project flattened TeX into publisher-independent manuscript regions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .errors import WorkflowError
from .tex import (
    TeXCommand,
    command_at,
    is_commented,
    is_escaped,
    scan_tex_commands,
    skip_tex_space,
)

CHINESE_SENTENCE_MAX_ATOMS = 50
CHINESE_CLAUSE_MIN_ATOMS = 15
ENGLISH_SENTENCE_MAX_WORDS = 30
ENGLISH_CLAUSE_MIN_WORDS = 10
MAX_UNITS_PER_SENTENCE = 3


class RegionKind(str, Enum):
    """Canonical document, structural, and revision-unit kinds."""

    FRONTMATTER = "frontmatter"
    MAINMATTER = "mainmatter"
    BACKMATTER = "backmatter"
    BIBLIOGRAPHY = "bibliography"
    SECONDARY_SUMMARY = "secondary_summary"
    DOCUMENT_TITLE = "document_title"
    SECONDARY_TITLE = "secondary_title"
    AUTHOR_BLOCK = "author_block"
    AUTHOR_ITEM = "author_item"
    AFFILIATION_BLOCK = "affiliation_block"
    AFFILIATION_ITEM = "affiliation_item"
    AUTHOR_NOTE = "author_note"
    FUNDING_FRONTMATTER = "funding_frontmatter"
    ABSTRACT = "abstract"
    SECONDARY_ABSTRACT = "secondary_abstract"
    KEYWORDS = "keywords"
    HEADING_H1 = "heading_h1"
    HEADING_H2 = "heading_h2"
    HEADING_H3 = "heading_h3"
    HEADING_H4_PLUS = "heading_h4_plus"
    PROSE_PARAGRAPH = "prose_paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    DISPLAY_EQUATION = "display_equation"
    EQUATION_EXPLANATION = "equation_explanation"
    FIGURE = "figure"
    FIGURE_CAPTION = "figure_caption"
    TABLE = "table"
    TABLE_CAPTION = "table_caption"
    TABLE_ROW = "table_row"
    TABLE_CELL = "table_cell"
    FOOTNOTE = "footnote"
    ACKNOWLEDGEMENTS = "acknowledgements"
    FUNDING_STATEMENT = "funding_statement"
    AUTHOR_CONTRIBUTIONS = "author_contributions"
    COMPETING_INTERESTS = "competing_interests"
    DATA_AVAILABILITY = "data_availability"
    CODE_AVAILABILITY = "code_availability"
    SUPPLEMENTARY_STATEMENT = "supplementary_statement"
    BIBLIOGRAPHY_ENTRY = "bibliography_entry"
    ENGLISH_SUMMARY_TITLE = "english_summary_title"
    ENGLISH_SUMMARY_PROSE = "english_summary_prose"
    UNKNOWN_REGION = "unknown_region"
    SENTENCE = "sentence"
    CLAUSE = "clause"
    INLINE_MATH = "inline_math"
    CITATION = "citation"
    CROSS_REFERENCE = "cross_reference"
    URL_DOI = "url_doi"


@dataclass(frozen=True)
class ProtectedSpan:
    """One inline source interval whose syntax must remain intact."""

    kind: RegionKind
    source_start: int
    source_end: int
    identity: str


@dataclass(frozen=True)
class RevisionUnit:
    """One readable or natural current-source revision unit."""

    kind: RegionKind
    source_start: int
    source_end: int
    normalized_content: str


@dataclass(frozen=True)
class StructuralBlock:
    """One canonical structural block over exact flattened-source offsets."""

    kind: RegionKind
    structural_path: tuple[str, ...]
    ordinal: int
    source_start: int
    source_end: int
    normalized_content: str
    identity: str | None = None
    label: str | None = None
    asset_identity: str | None = None
    container_start: int | None = None
    container_end: int | None = None
    units: tuple[RevisionUnit, ...] = ()
    protected_spans: tuple[ProtectedSpan, ...] = ()


@dataclass(frozen=True)
class ManuscriptProjection:
    """Ordered canonical blocks for one flattened manuscript source."""

    text: str
    blocks: tuple[StructuralBlock, ...]


_HEADING_KINDS = {
    "section": RegionKind.HEADING_H1,
    "subsection": RegionKind.HEADING_H2,
    "subsubsection": RegionKind.HEADING_H3,
    "paragraph": RegionKind.HEADING_H4_PLUS,
}
_HEADING_LEVELS = {name: index for index, name in enumerate(_HEADING_KINDS, 1)}
_COMMAND_FIELDS = {
    "title": RegionKind.DOCUMENT_TITLE,
    "entitle": RegionKind.SECONDARY_TITLE,
    "abstract": RegionKind.ABSTRACT,
    "cnabstract": RegionKind.ABSTRACT,
    "enabstract": RegionKind.SECONDARY_ABSTRACT,
    "keywords": RegionKind.KEYWORDS,
    "cnkeywords": RegionKind.KEYWORDS,
    "enkeywords": RegionKind.KEYWORDS,
    "author": RegionKind.AUTHOR_ITEM,
    "enauthor": RegionKind.AUTHOR_ITEM,
    "affiliation": RegionKind.AFFILIATION_ITEM,
    "enaffiliation": RegionKind.AFFILIATION_ITEM,
    "affil": RegionKind.AFFILIATION_ITEM,
    "address": RegionKind.AUTHOR_NOTE,
    "email": RegionKind.AUTHOR_NOTE,
    "cortext": RegionKind.AUTHOR_NOTE,
    "corrauthorcn": RegionKind.AUTHOR_NOTE,
    "corrauthoren": RegionKind.AUTHOR_NOTE,
    "firstauthorcn": RegionKind.AUTHOR_NOTE,
    "firstauthoren": RegionKind.AUTHOR_NOTE,
    "funding": RegionKind.FUNDING_FRONTMATTER,
}
_ENVIRONMENT_FIELDS = {
    "abstract": RegionKind.ABSTRACT,
    "englishabstract": RegionKind.SECONDARY_ABSTRACT,
    "keyword": RegionKind.KEYWORDS,
}
_BACKMATTER_ENVIRONMENT_FIELDS = {
    "acknowledgement": RegionKind.ACKNOWLEDGEMENTS,
    "acknowledgements": RegionKind.ACKNOWLEDGEMENTS,
    "fundingstatement": RegionKind.FUNDING_STATEMENT,
    "authorcontribution": RegionKind.AUTHOR_CONTRIBUTIONS,
    "authorcontributions": RegionKind.AUTHOR_CONTRIBUTIONS,
    "competinginterests": RegionKind.COMPETING_INTERESTS,
    "dataavailability": RegionKind.DATA_AVAILABILITY,
    "codeavailability": RegionKind.CODE_AVAILABILITY,
    "supplementarystatement": RegionKind.SUPPLEMENTARY_STATEMENT,
}
_PARAGRAPH_SEPARATOR = re.compile(r"(?:\r?\n[ \t]*){2,}")
_ENVIRONMENT_FIELD = re.compile(
    r"\\begin\{(?P<name>abstract|englishabstract|keyword)\}"
    r"(?P<body>.*?)\\end\{(?P=name)\}",
    re.S,
)
_BACKMATTER_ENVIRONMENT = re.compile(
    r"\\begin\{(?P<name>"
    + "|".join(re.escape(name) for name in _BACKMATTER_ENVIRONMENT_FIELDS)
    + r")\}(?P<body>.*?)\\end\{(?P=name)\}",
    re.S,
)
_DOCUMENT = re.compile(r"\\begin\{document\}(?P<body>.*?)\\end\{document\}", re.S)
_STRUCTURAL_ENVIRONMENT = re.compile(
    r"\\begin\{(?P<name>equation\*?|figure\*?|table\*?|itemize|enumerate|"
    r"thebibliography)\}(?P<body>.*?)\\end\{(?P=name)\}",
    re.S,
)
_CITATION_COMMANDS = ("cite", "citep", "citet", "citealp", "citeauthor", "citeyear")
_REFERENCE_COMMANDS = ("ref", "eqref", "pageref", "autoref", "cref", "Cref")
_LINK_COMMANDS = ("url", "nolinkurl", "doi")
_RAW_URL_OR_DOI = re.compile(r"https?://[^\s{}]+|10\.\d{4,9}/[^\s{}]+")


def normalize_region_content(text: str) -> str:
    """Normalize comments and source-layout whitespace without losing TeX."""
    pieces: list[str] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
            pieces.append(" ")
            continue
        pieces.append(text[cursor])
        cursor += 1
    return " ".join("".join(pieces).split())


_EQUATION_TEXT_COMMANDS = frozenset(
    {"mbox", "text", "textbf", "textit", "textrm", "textsf", "texttt"}
)


def normalize_equation_content(text: str) -> str:
    """Normalize only TeX-ignored display layout and structural metadata."""
    pieces: list[str] = []
    preserve_stack: list[bool] = []
    pending_text_group = False
    cursor = 0
    while cursor < len(text):
        character = text[cursor]
        if character == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if character == "\\" and not is_escaped(text, cursor):
            command = re.match(r"\\([A-Za-z@]+\*?)", text[cursor:])
            if command is None:
                pieces.append(text[cursor : cursor + 2])
                cursor += 2
                continue
            name = command.group(1)
            command_end = cursor + len(command.group(0))
            if name.rstrip("*") in {"label", "tag"}:
                opening = skip_tex_space(text, command_end)
                cursor = _matching_brace_end(text, opening) + 1
                pending_text_group = False
                continue
            pieces.append(command.group(0))
            pending_text_group = name.rstrip("*") in _EQUATION_TEXT_COMMANDS
            cursor = command_end
            continue
        if character == "{":
            preserve = pending_text_group or (
                preserve_stack[-1] if preserve_stack else False
            )
            preserve_stack.append(preserve)
            pending_text_group = False
            pieces.append(character)
            cursor += 1
            continue
        if character == "}":
            if preserve_stack:
                preserve_stack.pop()
            pending_text_group = False
            pieces.append(character)
            cursor += 1
            continue
        if character.isspace():
            if preserve_stack and preserve_stack[-1] and pieces and pieces[-1] != " ":
                pieces.append(" ")
            cursor += 1
            continue
        pending_text_group = False
        pieces.append(character)
        cursor += 1
    return "".join(pieces)


def _ambiguity(text: str, context: str, exc: Exception | None = None) -> WorkflowError:
    del exc
    line = 1
    nearby = text[:240].replace("\n", r"\n")
    message = (
        "REGION_CLASSIFICATION_AMBIGUOUS\n"
        f"line: {line}\n"
        f"region context: {context}\n"
        f"nearby TeX: {nearby}"
    )
    return WorkflowError(message)


def _field_bounds(text: str, command_start: int, command_name: str) -> tuple[int, int]:
    opening = skip_tex_space(text, command_start + len(command_name) + 1)
    if opening < len(text) and text[opening] == "*":
        opening = skip_tex_space(text, opening + 1)
    while opening < len(text) and text[opening] == "[":
        opening = skip_tex_space(text, _matching_square_end(text, opening) + 1)
    return opening + 1, _matching_brace_end(text, opening)


def _matching_brace_end(text: str, opening: int) -> int:
    if opening >= len(text) or text[opening] != "{":
        raise WorkflowError(
            "REGION_CLASSIFICATION_AMBIGUOUS\nnearby TeX: missing field"
        )
    depth = 1
    cursor = opening + 1
    while cursor < len(text):
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if text[cursor] == "{" and not is_escaped(text, cursor):
            depth += 1
        elif text[cursor] == "}" and not is_escaped(text, cursor):
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    line = text.count("\n", 0, opening) + 1
    nearby = text[max(0, opening - 80) : opening + 160].replace("\n", r"\n")
    raise WorkflowError(
        "REGION_CLASSIFICATION_AMBIGUOUS\n"
        f"line: {line}\n"
        "region context: UNKNOWN_REGION\n"
        f"nearby TeX: {nearby}"
    )


_DEFINITION_TARGET = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\s*$"
    r"|\\(?:g?def|let)\s*$"
)


def _is_definition_target(text: str, command_start: int) -> bool:
    line_start = text.rfind("\n", 0, command_start) + 1
    return _DEFINITION_TARGET.search(text[line_start:command_start]) is not None


def _matching_square_end(text: str, opening: int) -> int:
    depth = 1
    cursor = opening + 1
    while cursor < len(text):
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if text[cursor] == "[" and not is_escaped(text, cursor):
            depth += 1
        elif text[cursor] == "]" and not is_escaped(text, cursor):
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    raise ValueError("Unbalanced TeX optional argument brackets.")


def _scan_optional_commands(
    text: str,
    names: tuple[str, ...],
    *,
    field_count: int,
) -> tuple[TeXCommand, ...]:
    commands: list[TeXCommand] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        name = next(
            (
                item
                for item in names
                if text[cursor] == "\\"
                and not is_escaped(text, cursor)
                and command_at(text, cursor, item)
            ),
            None,
        )
        if name is None:
            cursor += 1
            continue
        start = cursor
        if _is_definition_target(text, start):
            cursor += len(name) + 1
            continue
        end = start + len(name) + 1
        end = skip_tex_space(text, end)
        if end < len(text) and text[end] == "*":
            end = skip_tex_space(text, end + 1)
        while end < len(text) and text[end] == "[":
            end = skip_tex_space(text, _matching_square_end(text, end) + 1)
        fields: list[str] = []
        try:
            for _ in range(field_count):
                opening = skip_tex_space(text, end)
                if opening >= len(text) or text[opening] != "{":
                    raise ValueError(f"Malformed active \\{name} command.")
                closing = _matching_brace_end(text, opening)
                fields.append(text[opening + 1 : closing])
                end = closing + 1
        except WorkflowError as exc:
            raise ValueError(f"Malformed active \\{name} command.") from exc
        commands.append(TeXCommand(name, start, end, tuple(fields)))
        cursor = end
    return tuple(commands)


def _trim_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _visible_counts(text: str) -> tuple[int, int, bool]:
    characters = list(text)
    for span in _protected_spans(text, 0, len(text)):
        characters[span.source_start : span.source_end] = " " * (
            span.source_end - span.source_start
        )
    visible = re.sub(r"%[^\n]*|\\[A-Za-z@]+\*?|\\.", "", "".join(characters))
    cjk = len(re.findall(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]", visible))
    lexical_tokens = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", visible)
    return cjk + len(lexical_tokens), len(lexical_tokens), cjk > 0


_ENGLISH_ABBREVIATION = re.compile(
    r"(?:e\.g|i\.e|fig|eq|no|dr|mr|mrs|ms|prof|et\s+al)\.$", re.IGNORECASE
)


def _period_is_sentence_boundary(text: str, cursor: int, start: int, end: int) -> bool:
    before = text[cursor - 1] if cursor > start else ""
    after = text[cursor + 1] if cursor + 1 < end else ""
    if before.isdigit() and after.isdigit():
        return False
    if after.isalpha() and cursor + 2 < end and text[cursor + 2] == ".":
        return False
    prefix = text[max(start, cursor - 12) : cursor + 1]
    return _ENGLISH_ABBREVIATION.search(prefix) is None


def _strong_sentence_ranges(text: str, start: int, end: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    protected = _protected_spans(text, start, end)
    protected_index = 0
    left = start
    cursor = start
    while cursor < end:
        while (
            protected_index < len(protected)
            and protected[protected_index].source_end <= cursor
        ):
            protected_index += 1
        if (
            protected_index < len(protected)
            and protected[protected_index].source_start
            <= cursor
            < protected[protected_index].source_end
        ):
            cursor = protected[protected_index].source_end
            continue
        character = text[cursor]
        boundary = character in "。！？；!?;"  # noqa: RUF001
        if character == ".":
            boundary = _period_is_sentence_boundary(text, cursor, start, end)
        if boundary:
            right = cursor + 1
            item_start, item_end = _trim_bounds(text, left, right)
            if item_start < item_end:
                ranges.append((item_start, item_end))
            left = right
        cursor += 1
    item_start, item_end = _trim_bounds(text, left, end)
    if item_start < item_end:
        ranges.append((item_start, item_end))
    return ranges


def _weak_clause_ranges(
    text: str, start: int, end: int, *, chinese: bool
) -> list[tuple[int, int]]:
    boundaries = "，：" if chinese else ",:"  # noqa: RUF001
    result: list[tuple[int, int]] = []
    protected = _protected_spans(text, start, end)
    protected_index = 0
    left = start
    cursor = start
    while cursor < end:
        while (
            protected_index < len(protected)
            and protected[protected_index].source_end <= cursor
        ):
            protected_index += 1
        if (
            protected_index < len(protected)
            and protected[protected_index].source_start
            <= cursor
            < protected[protected_index].source_end
        ):
            cursor = protected[protected_index].source_end
            continue
        if text[cursor] not in boundaries:
            cursor += 1
            continue
        right = cursor + 1
        item_start, item_end = _trim_bounds(text, left, right)
        if item_start < item_end:
            result.append((item_start, item_end))
        left = right
        cursor += 1
    item_start, item_end = _trim_bounds(text, left, end)
    if item_start < item_end:
        result.append((item_start, item_end))
    return result


def _unit_size(text: str, item: tuple[int, int], *, chinese: bool) -> int:
    atoms, words, _has_cjk = _visible_counts(text[item[0] : item[1]])
    return atoms if chinese else words


def _merge_clause_ranges(
    text: str, ranges: list[tuple[int, int]], *, chinese: bool
) -> list[tuple[int, int]]:
    merged = list(ranges)
    minimum = CHINESE_CLAUSE_MIN_ATOMS if chinese else ENGLISH_CLAUSE_MIN_WORDS
    while len(merged) > 1:
        short_index = next(
            (
                index
                for index, item in enumerate(merged)
                if _unit_size(text, item, chinese=chinese) < minimum
            ),
            None,
        )
        if short_index is None:
            break
        if short_index == 0:
            pair_start = 0
        elif short_index == len(merged) - 1:
            pair_start = short_index - 1
        else:
            left_size = _unit_size(text, merged[short_index - 1], chinese=chinese)
            right_size = _unit_size(text, merged[short_index + 1], chinese=chinese)
            pair_start = short_index - 1 if left_size <= right_size else short_index
        merged[pair_start : pair_start + 2] = [
            (merged[pair_start][0], merged[pair_start + 1][1])
        ]
    while len(merged) > MAX_UNITS_PER_SENTENCE:
        pair_start = min(
            range(len(merged) - 1),
            key=lambda index: (
                _unit_size(text, merged[index], chinese=chinese)
                + _unit_size(text, merged[index + 1], chinese=chinese),
                index,
            ),
        )
        merged[pair_start : pair_start + 2] = [
            (merged[pair_start][0], merged[pair_start + 1][1])
        ]
    return merged


def prose_units(text: str, start: int, end: int) -> tuple[RevisionUnit, ...]:
    """Split prose into readable sentence or long-sentence clause units."""
    units: list[RevisionUnit] = []
    for sentence in prose_sentence_units(text, start, end):
        sentence_start = sentence.source_start
        sentence_end = sentence.source_end
        atoms, words, chinese = _visible_counts(text[sentence_start:sentence_end])
        use_clauses = (
            atoms > CHINESE_SENTENCE_MAX_ATOMS
            if chinese
            else words > ENGLISH_SENTENCE_MAX_WORDS
        )
        ranges = (
            _merge_clause_ranges(
                text,
                _weak_clause_ranges(
                    text, sentence_start, sentence_end, chinese=chinese
                ),
                chinese=chinese,
            )
            if use_clauses
            else [(sentence_start, sentence_end)]
        )
        kind = RegionKind.CLAUSE if len(ranges) > 1 else RegionKind.SENTENCE
        units.extend(
            RevisionUnit(kind, left, right, normalize_region_content(text[left:right]))
            for left, right in ranges
        )
    return tuple(units)


def prose_sentence_units(text: str, start: int, end: int) -> tuple[RevisionUnit, ...]:
    """Return whole scientific sentences before presentation segmentation."""
    return tuple(
        RevisionUnit(
            RegionKind.SENTENCE,
            sentence_start,
            sentence_end,
            normalize_region_content(text[sentence_start:sentence_end]),
        )
        for sentence_start, sentence_end in _strong_sentence_ranges(text, start, end)
    )


def _item_units(
    text: str, start: int, end: int, kind: RegionKind
) -> tuple[RevisionUnit, ...]:
    separators = frozenset(",，;；")  # noqa: RUF001
    result: list[RevisionUnit] = []
    left = start
    depth = 0
    for cursor in range(start, end):
        character = text[cursor]
        if character == "{" and not is_escaped(text, cursor):
            depth += 1
        elif character == "}" and not is_escaped(text, cursor):
            depth = max(0, depth - 1)
        elif depth == 0 and character in separators:
            item_start, item_end = _trim_bounds(text, left, cursor)
            if item_start < item_end:
                result.append(
                    RevisionUnit(
                        kind,
                        item_start,
                        item_end,
                        normalize_region_content(text[item_start:item_end]),
                    )
                )
            left = cursor + 1
    item_start, item_end = _trim_bounds(text, left, end)
    if item_start < item_end:
        result.append(
            RevisionUnit(
                kind,
                item_start,
                item_end,
                normalize_region_content(text[item_start:item_end]),
            )
        )
    return tuple(result)


def _funding_units(text: str, start: int, end: int) -> tuple[RevisionUnit, ...]:
    """Return grant items without a shared human-readable field wrapper."""
    units = list(_item_units(text, start, end, RegionKind.FUNDING_FRONTMATTER))
    if not units:
        return ()
    field = text[start:end]
    pairs = (
        ("\uff08", "\uff09"),
        ("(", ")"),
        ("\u3010", "\u3011"),
        ("[", "]"),
    )
    wrapper = next(
        (
            (opening, closing, field.rfind(opening))
            for opening, closing in pairs
            if field.rstrip().endswith(closing) and field.rfind(opening) >= 0
        ),
        None,
    )
    if wrapper is None:
        return tuple(units)
    _opening, closing, opening_index = wrapper
    first = units[0]
    first_start, first_end = _trim_bounds(
        text,
        max(first.source_start, start + opening_index + 1),
        first.source_end,
    )
    last = units[-1]
    last_start, last_end = _trim_bounds(text, last.source_start, last.source_end)
    if last_end > last_start and text[last_end - 1] == closing:
        last_end = _trim_bounds(text, last_start, last_end - 1)[1]
    units[0] = RevisionUnit(
        RegionKind.FUNDING_FRONTMATTER,
        first_start,
        first_end,
        normalize_region_content(text[first_start:first_end]),
    )
    units[-1] = RevisionUnit(
        RegionKind.FUNDING_FRONTMATTER,
        last_start if len(units) > 1 else first_start,
        last_end,
        normalize_region_content(
            text[last_start if len(units) > 1 else first_start : last_end]
        ),
    )
    return tuple(unit for unit in units if unit.source_start < unit.source_end)


def _command_protected_spans(
    text: str,
    start: int,
    end: int,
    names: tuple[str, ...],
    kind: RegionKind,
    *,
    field_count: int = 1,
) -> list[ProtectedSpan]:
    fragment = text[start:end]
    result: list[ProtectedSpan] = []
    cursor = 0
    while cursor < len(fragment):
        if fragment[cursor] == "%" and not is_escaped(fragment, cursor):
            newline = fragment.find("\n", cursor)
            cursor = len(fragment) if newline < 0 else newline + 1
            continue
        name = next(
            (
                item
                for item in names
                if fragment[cursor] == "\\"
                and not is_escaped(fragment, cursor)
                and command_at(fragment, cursor, item)
            ),
            None,
        )
        if name is None:
            cursor += 1
            continue
        command_start = cursor
        command_end = cursor + len(name) + 1
        fields: list[str] = []
        for _ in range(field_count):
            opening = skip_tex_space(fragment, command_end)
            if opening >= len(fragment) or fragment[opening] != "{":
                fields = []
                break
            try:
                closing = _matching_brace_end(fragment, opening)
            except WorkflowError as exc:
                raise _ambiguity(text[start:end], kind.value, exc) from exc
            fields.append(fragment[opening + 1 : closing])
            command_end = closing + 1
        if not fields:
            cursor += len(name) + 1
            continue
        identity = fields[0].strip()
        if kind is RegionKind.CITATION:
            identity = ",".join(
                sorted(item.strip() for item in identity.split(",") if item.strip())
            )
        result.append(
            ProtectedSpan(
                kind,
                start + command_start,
                start + command_end,
                identity,
            )
        )
        cursor = command_end
    return result


def _inline_math_spans(text: str, start: int, end: int) -> list[ProtectedSpan]:
    fragment = text[start:end]
    pattern = re.compile(r"(?<!\\)\$(?!\$).*?(?<!\\)\$|\\\(.*?\\\)", re.S)
    return [
        ProtectedSpan(
            RegionKind.INLINE_MATH,
            start + match.start(),
            start + match.end(),
            match.group(0),
        )
        for match in pattern.finditer(fragment)
    ]


def _raw_link_spans(text: str, start: int, end: int) -> list[ProtectedSpan]:
    result: list[ProtectedSpan] = []
    for match in _RAW_URL_OR_DOI.finditer(text, start, end):
        right = match.end()
        while right > match.start() and text[right - 1] in ".,;!?":
            right -= 1
        if match.start() < right:
            result.append(
                ProtectedSpan(
                    RegionKind.URL_DOI,
                    match.start(),
                    right,
                    text[match.start() : right],
                )
            )
    return result


def _protected_spans(text: str, start: int, end: int) -> tuple[ProtectedSpan, ...]:
    spans = [
        *_inline_math_spans(text, start, end),
        *_command_protected_spans(
            text, start, end, _CITATION_COMMANDS, RegionKind.CITATION
        ),
        *_command_protected_spans(
            text, start, end, _REFERENCE_COMMANDS, RegionKind.CROSS_REFERENCE
        ),
        *_command_protected_spans(text, start, end, _LINK_COMMANDS, RegionKind.URL_DOI),
        *_command_protected_spans(
            text, start, end, ("href",), RegionKind.URL_DOI, field_count=2
        ),
        *_raw_link_spans(text, start, end),
    ]
    selected: list[ProtectedSpan] = []
    for span in sorted(spans, key=lambda item: (item.source_start, -item.source_end)):
        if selected and span.source_start < selected[-1].source_end:
            continue
        selected.append(span)
    return tuple(selected)


def _path_before(
    headings: list[tuple[int, int, str]],
    offset: int,
    *,
    parent_of_level: int | None = None,
) -> tuple[str, ...]:
    active: dict[int, int] = {}
    for start, level, _name in headings:
        if start >= offset:
            break
        active[level] = active.get(level, 0) + 1
        for deeper in tuple(key for key in active if key > level):
            del active[deeper]
    return (
        "mainmatter",
        *(
            f"heading_h{level}:{active[level]}"
            for level in sorted(active)
            if parent_of_level is None or level < parent_of_level
        ),
    )


def _add_field_blocks(text: str, blocks: list[StructuralBlock]) -> None:
    names = tuple(_COMMAND_FIELDS)
    try:
        commands = _scan_optional_commands(text, names, field_count=1)
    except ValueError as exc:
        raise _ambiguity(text, "frontmatter", exc) from exc
    seen_environment_ranges = [
        (match.start(), match.end()) for match in _ENVIRONMENT_FIELD.finditer(text)
    ]
    counts: dict[RegionKind, int] = {}
    for command in commands:
        if any(
            left <= command.start < right for left, right in seen_environment_ranges
        ):
            continue
        kind = _COMMAND_FIELDS[command.name]
        start, end = _field_bounds(text, command.start, command.name)
        start, end = _trim_bounds(text, start, end)
        counts[kind] = counts.get(kind, 0) + 1
        units = (
            _funding_units(text, start, end)
            if kind is RegionKind.FUNDING_FRONTMATTER
            else _item_units(text, start, end, kind)
            if kind is RegionKind.KEYWORDS
            else prose_units(text, start, end)
            if kind in {RegionKind.ABSTRACT, RegionKind.SECONDARY_ABSTRACT}
            else ()
        )
        blocks.append(
            StructuralBlock(
                kind,
                ("frontmatter",),
                counts[kind],
                start,
                end,
                normalize_region_content(text[start:end]),
                identity=f"{command.name}:{counts[kind]}",
                container_start=command.start,
                container_end=command.end,
                units=units,
                protected_spans=_protected_spans(text, start, end),
            )
        )
    for match in _ENVIRONMENT_FIELD.finditer(text):
        if is_commented(text, match.start()):
            continue
        kind = _ENVIRONMENT_FIELDS[match.group("name")]
        start, end = _trim_bounds(text, match.start("body"), match.end("body"))
        counts[kind] = counts.get(kind, 0) + 1
        units = (
            _item_units(text, start, end, kind)
            if kind is RegionKind.KEYWORDS
            else prose_units(text, start, end)
        )
        blocks.append(
            StructuralBlock(
                kind,
                ("frontmatter",),
                counts[kind],
                start,
                end,
                normalize_region_content(text[start:end]),
                identity=kind.value,
                container_start=match.start(),
                container_end=match.end(),
                units=units,
                protected_spans=_protected_spans(text, start, end),
            )
        )


def _add_heading_blocks(
    text: str, blocks: list[StructuralBlock]
) -> list[tuple[int, int, str]]:
    try:
        commands = _scan_optional_commands(text, tuple(_HEADING_KINDS), field_count=1)
    except ValueError as exc:
        raise _ambiguity(text, "heading", exc) from exc
    heading_events = sorted(
        (command.start, _HEADING_LEVELS[command.name], command.name)
        for command in commands
    )
    sibling_counts: dict[tuple[tuple[str, ...], int], int] = {}
    for command in commands:
        level = _HEADING_LEVELS[command.name]
        path = _path_before(heading_events, command.start, parent_of_level=level)
        key = (path, level)
        sibling_counts[key] = sibling_counts.get(key, 0) + 1
        start, end = _field_bounds(text, command.start, command.name)
        start, end = _trim_bounds(text, start, end)
        blocks.append(
            StructuralBlock(
                _HEADING_KINDS[command.name],
                path,
                sibling_counts[key],
                start,
                end,
                normalize_region_content(text[start:end]),
                identity=f"{command.name}:{sibling_counts[key]}",
                container_start=command.start,
                container_end=command.end,
                units=(
                    RevisionUnit(
                        _HEADING_KINDS[command.name],
                        start,
                        end,
                        normalize_region_content(text[start:end]),
                    ),
                ),
            )
        )
    return heading_events


def _add_footnote_blocks(text: str, blocks: list[StructuralBlock]) -> None:
    try:
        commands = _scan_optional_commands(text, ("footnote",), field_count=1)
    except ValueError as exc:
        raise _ambiguity(text, "footnote", exc) from exc
    for ordinal, command in enumerate(commands, 1):
        start, end = _field_bounds(text, command.start, command.name)
        start, end = _trim_bounds(text, start, end)
        blocks.append(
            StructuralBlock(
                RegionKind.FOOTNOTE,
                ("backmatter", "footnotes"),
                ordinal,
                start,
                end,
                normalize_region_content(text[start:end]),
                identity=f"footnote:{ordinal}",
                container_start=command.start,
                container_end=command.end,
                units=prose_units(text, start, end),
                protected_spans=_protected_spans(text, start, end),
            )
        )


def _add_named_backmatter_blocks(
    text: str,
    blocks: list[StructuralBlock],
    heading_events: list[tuple[int, int, str]],
) -> None:
    counts: dict[RegionKind, int] = {}
    for match in _BACKMATTER_ENVIRONMENT.finditer(text):
        if is_commented(text, match.start()):
            continue
        kind = _BACKMATTER_ENVIRONMENT_FIELDS[match.group("name")]
        counts[kind] = counts.get(kind, 0) + 1
        ordinal = counts[kind]
        start, end = _trim_bounds(text, match.start("body"), match.end("body"))
        blocks.append(
            StructuralBlock(
                kind,
                (*_path_before(heading_events, match.start()), "backmatter"),
                ordinal,
                start,
                end,
                normalize_region_content(text[start:end]),
                identity=f"{kind.value}:{ordinal}",
                container_start=match.start(),
                container_end=match.end(),
                units=prose_units(text, start, end),
                protected_spans=_protected_spans(text, start, end),
            )
        )


def _label_in(text: str, start: int, end: int) -> str | None:
    commands = scan_tex_commands(text[start:end], ("label",), field_count=1)
    return commands[0].fields[0].strip() if len(commands) == 1 else None


def _figure_asset_identity(
    text: str,
    start: int,
    end: int,
    asset_root: Path | None,
) -> str | None:
    match = re.search(
        r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^{}]+)\}",
        text[start:end],
    )
    if match is None:
        return None
    declared = match.group("path").strip()
    if asset_root is None:
        return declared
    candidate = asset_root / declared
    candidates = [candidate]
    if not candidate.suffix:
        candidates.extend(
            candidate.with_suffix(suffix)
            for suffix in (".pdf", ".png", ".jpg", ".jpeg", ".eps")
        )
    existing = next((path for path in candidates if path.is_file()), None)
    if existing is None:
        return declared
    digest = hashlib.sha256(existing.read_bytes()).hexdigest()
    return f"{declared}|sha256:{digest}"


def _caption_blocks(
    text: str,
    start: int,
    end: int,
    kind: RegionKind,
    path: tuple[str, ...],
    owner_identity: str,
) -> list[StructuralBlock]:
    fragment = text[start:end]
    commands = [
        *_scan_optional_commands(fragment, ("caption",), field_count=1),
        *_scan_optional_commands(fragment, ("bicaption",), field_count=2),
    ]
    result: list[StructuralBlock] = []
    field_events: list[tuple[int, int, int, int]] = []
    for command in commands:
        cursor = start + command.start + len(command.name) + 1
        cursor = skip_tex_space(text, cursor)
        if cursor < len(text) and text[cursor] == "*":
            cursor = skip_tex_space(text, cursor + 1)
        while cursor < len(text) and text[cursor] == "[":
            cursor = skip_tex_space(text, _matching_square_end(text, cursor) + 1)
        for _field in command.fields:
            opening = skip_tex_space(text, cursor)
            closing = _matching_brace_end(text, opening)
            field_start, field_end = _trim_bounds(text, opening + 1, closing)
            field_events.append(
                (
                    start + command.start,
                    start + command.end,
                    field_start,
                    field_end,
                )
            )
            cursor = closing + 1
    for ordinal, (container_start, container_end, field_start, field_end) in enumerate(
        sorted(field_events), 1
    ):
        result.append(
            StructuralBlock(
                kind,
                (*path, owner_identity),
                ordinal,
                field_start,
                field_end,
                normalize_region_content(text[field_start:field_end]),
                identity=f"{owner_identity}:caption:{ordinal}",
                container_start=container_start,
                container_end=container_end,
                units=prose_units(text, field_start, field_end),
                protected_spans=_protected_spans(text, field_start, field_end),
            )
        )
    return result


def _tabular_body(text: str, start: int, end: int) -> tuple[int, int] | None:
    match = re.search(
        r"\\begin\{tabular\}(?:\[[^\]]*\])?\{[^{}]*\}(?P<body>.*?)"
        r"\\end\{tabular\}",
        text[start:end],
        re.S,
    )
    if match is None:
        return None
    return start + match.start("body"), start + match.end("body")


def _table_rows_and_cells(
    text: str,
    body_start: int,
    body_end: int,
    path: tuple[str, ...],
    owner_identity: str,
) -> list[StructuralBlock]:
    result: list[StructuralBlock] = []
    row_start = body_start
    row_ordinal = 0
    for match in re.finditer(r"\\\\(?:\[[^\]]*\])?", text[body_start:body_end]):
        row_end = body_start + match.start()
        start, end = _trim_bounds(text, row_start, row_end)
        row_start = body_start + match.end()
        if start >= end:
            continue
        row_text = re.sub(
            r"\\(?:hline|toprule|midrule|bottomrule)\b", "", text[start:end]
        ).strip()
        if not row_text:
            continue
        relative = text[start:end].find(row_text)
        start += relative
        end = start + len(row_text)
        row_ordinal += 1
        row_identity = f"{owner_identity}:row:{row_ordinal}"
        result.append(
            StructuralBlock(
                RegionKind.TABLE_ROW,
                (*path, owner_identity),
                row_ordinal,
                start,
                end,
                normalize_region_content(text[start:end]),
                identity=row_identity,
            )
        )
        cell_start = start
        cell_ordinal = 0
        depth = 0
        for cursor in range(start, end + 1):
            character = text[cursor] if cursor < end else "&"
            if character == "{" and not is_escaped(text, cursor):
                depth += 1
            elif character == "}" and not is_escaped(text, cursor):
                depth = max(0, depth - 1)
            elif character == "&" and depth == 0:
                left, right = _trim_bounds(text, cell_start, cursor)
                if left < right:
                    cell_ordinal += 1
                    result.append(
                        StructuralBlock(
                            RegionKind.TABLE_CELL,
                            (*path, owner_identity, f"row:{row_ordinal}"),
                            cell_ordinal,
                            left,
                            right,
                            normalize_region_content(text[left:right]),
                            identity=f"{row_identity}:cell:{cell_ordinal}",
                            units=prose_units(text, left, right),
                            protected_spans=_protected_spans(text, left, right),
                        )
                    )
                cell_start = cursor + 1
    return result


def _list_item_blocks(
    text: str,
    body_start: int,
    body_end: int,
    path: tuple[str, ...],
    owner_identity: str,
) -> list[StructuralBlock]:
    commands = list(
        re.finditer(r"\\item(?![A-Za-z@])(?:\[[^\]]*\])?", text[body_start:body_end])
    )
    result: list[StructuralBlock] = []
    for ordinal, command in enumerate(commands, 1):
        start = body_start + command.end()
        end = (
            body_start + commands[ordinal].start()
            if ordinal < len(commands)
            else body_end
        )
        start, end = _trim_bounds(text, start, end)
        result.append(
            StructuralBlock(
                RegionKind.LIST_ITEM,
                (*path, owner_identity),
                ordinal,
                start,
                end,
                normalize_region_content(text[start:end]),
                identity=f"{owner_identity}:item:{ordinal}",
                units=prose_units(text, start, end),
                protected_spans=_protected_spans(text, start, end),
            )
        )
    return result


def _bibliography_entries(
    text: str,
    body_start: int,
    body_end: int,
    path: tuple[str, ...],
) -> list[StructuralBlock]:
    commands = list(
        re.finditer(
            r"\\bibitem(?:\[[^\]]*\])?\{(?P<key>[^{}]+)\}",
            text[body_start:body_end],
        )
    )
    result: list[StructuralBlock] = []
    for ordinal, command in enumerate(commands, 1):
        start = body_start + command.end()
        end = (
            body_start + commands[ordinal].start()
            if ordinal < len(commands)
            else body_end
        )
        start, end = _trim_bounds(text, start, end)
        key = command.group("key").strip()
        result.append(
            StructuralBlock(
                RegionKind.BIBLIOGRAPHY_ENTRY,
                (*path, "bibliography"),
                ordinal,
                start,
                end,
                normalize_region_content(text[start:end]),
                identity=key,
                protected_spans=_protected_spans(text, start, end),
            )
        )
    return result


def _add_structural_environment_blocks(
    text: str,
    blocks: list[StructuralBlock],
    heading_events: list[tuple[int, int, str]],
    asset_root: Path | None,
) -> None:
    counts: dict[tuple[tuple[str, ...], str], int] = {}
    for match in _STRUCTURAL_ENVIRONMENT.finditer(text):
        if is_commented(text, match.start()):
            continue
        name = match.group("name")
        path = _path_before(heading_events, match.start())
        key = (path, name.rstrip("*"))
        counts[key] = counts.get(key, 0) + 1
        ordinal = counts[key]
        label = _label_in(text, match.start(), match.end())
        owner_identity = label or f"{name.rstrip('*')}:{ordinal}"
        body_start, body_end = match.start("body"), match.end("body")
        if name.startswith("equation"):
            kind = RegionKind.DISPLAY_EQUATION
        elif name.startswith("figure"):
            kind = RegionKind.FIGURE
        elif name.startswith("table"):
            kind = RegionKind.TABLE
        elif name in {"itemize", "enumerate"}:
            kind = RegionKind.LIST
        else:
            kind = RegionKind.BIBLIOGRAPHY
        blocks.append(
            StructuralBlock(
                kind,
                path,
                ordinal,
                body_start,
                body_end,
                normalize_equation_content(text[body_start:body_end])
                if kind is RegionKind.DISPLAY_EQUATION
                else normalize_region_content(text[body_start:body_end]),
                identity=owner_identity,
                label=label,
                asset_identity=(
                    _figure_asset_identity(text, match.start(), match.end(), asset_root)
                    if kind is RegionKind.FIGURE
                    else None
                ),
                container_start=match.start(),
                container_end=match.end(),
                protected_spans=_protected_spans(text, body_start, body_end),
            )
        )
        if kind is RegionKind.FIGURE:
            blocks.extend(
                _caption_blocks(
                    text,
                    match.start(),
                    match.end(),
                    RegionKind.FIGURE_CAPTION,
                    path,
                    owner_identity,
                )
            )
        elif kind is RegionKind.TABLE:
            blocks.extend(
                _caption_blocks(
                    text,
                    match.start(),
                    match.end(),
                    RegionKind.TABLE_CAPTION,
                    path,
                    owner_identity,
                )
            )
            if (tabular := _tabular_body(text, body_start, body_end)) is not None:
                blocks.extend(
                    _table_rows_and_cells(text, *tabular, path, owner_identity)
                )
        elif kind is RegionKind.LIST:
            blocks.extend(
                _list_item_blocks(text, body_start, body_end, path, owner_identity)
            )
        elif kind is RegionKind.BIBLIOGRAPHY:
            blocks.extend(_bibliography_entries(text, body_start, body_end, path))


def _add_paragraph_blocks(
    text: str,
    blocks: list[StructuralBlock],
    heading_events: list[tuple[int, int, str]],
) -> None:
    document = _DOCUMENT.search(text)
    if document is None:
        raise WorkflowError(
            "REGION_CLASSIFICATION_AMBIGUOUS\n"
            "region context: document\nnearby TeX: missing document environment"
        )
    occupied = sorted(
        (
            block.container_start,
            block.container_end,
        )
        for block in blocks
        if block.container_start is not None
        and block.container_end is not None
        and document.start("body") <= block.container_start < document.end("body")
    )
    cursor = document.start("body")
    gaps: list[tuple[int, int]] = []
    for start, end in occupied:
        if cursor < start:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < document.end("body"):
        gaps.append((cursor, document.end("body")))
    counts: dict[tuple[str, ...], int] = {}
    for gap_start, gap_end in gaps:
        left = gap_start
        for separator in _PARAGRAPH_SEPARATOR.finditer(text, gap_start, gap_end):
            _append_prose_block(
                text, blocks, heading_events, counts, left, separator.start()
            )
            left = separator.end()
        _append_prose_block(text, blocks, heading_events, counts, left, gap_end)


def _append_prose_block(
    text: str,
    blocks: list[StructuralBlock],
    heading_events: list[tuple[int, int, str]],
    counts: dict[tuple[str, ...], int],
    start: int,
    end: int,
) -> None:
    start, end = _trim_bounds(text, start, end)
    if start >= end:
        return
    content = text[start:end]
    visible = normalize_region_content(content)
    if not visible or re.fullmatch(r"(?:\\[A-Za-z@]+\*?(?:\{[^{}]*\})?\s*)+", visible):
        return
    if any(token in content for token in (r"\bibliography", r"\bibitem")):
        return
    path = _path_before(heading_events, start)
    counts[path] = counts.get(path, 0) + 1
    blocks.append(
        StructuralBlock(
            RegionKind.PROSE_PARAGRAPH,
            path,
            counts[path],
            start,
            end,
            visible,
            units=prose_units(text, start, end),
            protected_spans=_protected_spans(text, start, end),
        )
    )


def project_manuscript(
    text: str,
    *,
    asset_root: Path | None = None,
    source_name: str = "<flattened manuscript>",
) -> ManuscriptProjection:
    """Return one exact-offset canonical projection of flattened TeX."""
    blocks: list[StructuralBlock] = []
    try:
        _add_field_blocks(text, blocks)
        heading_events = _add_heading_blocks(text, blocks)
        _add_footnote_blocks(text, blocks)
        _add_named_backmatter_blocks(text, blocks, heading_events)
        _add_structural_environment_blocks(text, blocks, heading_events, asset_root)
        _add_paragraph_blocks(text, blocks, heading_events)
    except WorkflowError as exc:
        message = str(exc)
        if "REGION_CLASSIFICATION_AMBIGUOUS" in message and "\nfile:" not in message:
            first, separator, rest = message.partition("\n")
            raise WorkflowError(
                f"{first}\nfile: {source_name}{separator}{rest}"
            ) from exc
        raise
    return ManuscriptProjection(
        text,
        tuple(sorted(blocks, key=lambda item: (item.source_start, item.source_end))),
    )
