"""Apply addition-only highlights to exact current-manuscript source bytes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from itertools import pairwise, zip_longest
from pathlib import Path

from .errors import WorkflowError
from .provenance import ProvenanceSource, split_by_review_provenance
from .tex import (
    extract_braced,
    is_commented,
    is_escaped,
    scan_tex_commands,
    skip_tex_space,
)


@dataclass(frozen=True)
class HighlightSpan:
    """One non-overlapping current-source interval and its visible owner."""

    start: int
    end: int
    review_ids: tuple[str, ...] | None
    kind: str = "text"


@dataclass(frozen=True)
class _CurrentBlock:
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class _LabeledStructuralBlock:
    kind: str
    label: str
    start: int
    end: int


@dataclass(frozen=True)
class CitationProvenance:
    """Canonical ownership and current-source lines for one newly added key."""

    review_ids: tuple[str, ...] | None
    source_lines: tuple[int, ...]


@dataclass(frozen=True)
class TopologyIdentity:
    """Successful clean/marked topology comparison counts."""

    paragraph_count_clean: int
    paragraph_count_marked: int
    paragraph_boundary_count_clean: int
    paragraph_boundary_count_marked: int


@dataclass
class TinyIslandAudit:
    """Aggregate decisions from deterministic visual span coalescing."""

    examined: int = 0
    coalesced: int = 0
    rejected_density: int = 0
    rejected_boundary: int = 0
    rejected_protected: int = 0
    rejected_provenance: int = 0


@dataclass(frozen=True)
class EquationAudit:
    """Conservative display-equation identity decisions."""

    examined: int
    normalized_identical: int
    highlighted: int
    ambiguous: int


def normalized_block_hash(text: str) -> str:
    """Hash one exact block after comment and whitespace normalization."""
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
    normalized = " ".join("".join(pieces).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _visible_length(text: str) -> int:
    pieces: list[str] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if text[cursor] == "\\" and not is_escaped(text, cursor):
            match = re.match(r"\\[A-Za-z@]+\*?|\\.", text[cursor:])
            if match is not None:
                cursor += len(match.group(0))
                continue
        if text[cursor] not in "{}[]$&^_~" and not text[cursor].isspace():
            pieces.append(text[cursor])
        cursor += 1
    return len(pieces)


def _command_field_blocks(text: str) -> list[_CurrentBlock]:
    names = ("section", "subsection", "subsubsection", "paragraph", "caption")
    try:
        commands = scan_tex_commands(text, names, field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed heading or caption in current source.") from exc
    blocks: list[_CurrentBlock] = []
    for command in commands:
        opening = skip_tex_space(text, command.start + len(command.name) + 1)
        blocks.append(_CurrentBlock(command.name, opening + 1, command.end - 1))
    return blocks


_DISPLAY_ENVIRONMENT = re.compile(
    r"\\begin\{(?P<name>equation\*?|align\*?|gather\*?|multline\*?|displaymath)\}"
    r".*?\\end\{(?P=name)\}",
    re.S,
)

_LABELED_STRUCTURAL_ENVIRONMENT = re.compile(
    r"\\begin\{(?P<name>figure\*?|table\*?|equation\*?|align\*?|gather\*?|"
    r"multline\*?|displaymath)\}.*?\\end\{(?P=name)\}",
    re.S,
)

_TOPOLOGY_ENVIRONMENTS = frozenset(
    {
        "align",
        "align*",
        "description",
        "displaymath",
        "enumerate",
        "equation",
        "equation*",
        "figure",
        "figure*",
        "gather",
        "gather*",
        "itemize",
        "multline",
        "multline*",
        "table",
        "table*",
    }
)
_ENVIRONMENT_BOUNDARY = re.compile(r"\\(?P<edge>begin|end)\{(?P<name>[A-Za-z*]+)\}")
_PAR_COMMAND = re.compile(r"\\par(?![A-Za-z@])[ \t]*")
_PARAGRAPH_SEPARATOR = re.compile(r"(?:\r?\n[ \t]*){2,}")
_CITATION_COMMANDS = ("cite", "citep", "citet", "citealp", "citeauthor", "citeyear")
_REFERENCE_COMMANDS = ("ref", "eqref", "pageref", "autoref", "cref", "Cref")
_ONE_FIELD_LINK_COMMANDS = ("url", "nolinkurl", "doi")
_SENTENCE_BOUNDARIES = frozenset("。！？；.!?;")  # noqa: RUF001
_TINY_ISLAND_MAX_ATOMS = 5
_TINY_ISLAND_MAX_LATIN_WORDS = 2
_TINY_ISLAND_DENSITY_PERCENT = 80


def _display_blocks(text: str) -> list[_CurrentBlock]:
    return [
        _CurrentBlock("display", match.start(), match.end())
        for match in _DISPLAY_ENVIRONMENT.finditer(text)
        if not is_commented(text, match.start())
    ]


def _structural_kind(environment: str) -> str:
    if environment.startswith("figure"):
        return "figure"
    if environment.startswith("table"):
        return "table"
    return "display"


def _labeled_structural_blocks(text: str) -> list[_LabeledStructuralBlock]:
    """Return uniquely labeled first-level figure, table, and display blocks."""
    candidates: list[_LabeledStructuralBlock] = []
    for match in _LABELED_STRUCTURAL_ENVIRONMENT.finditer(text):
        if is_commented(text, match.start()):
            continue
        block_text = match.group(0)
        try:
            labels = scan_tex_commands(block_text, ("label",), field_count=1)
        except ValueError as exc:
            raise WorkflowError(
                "Malformed label in structural manuscript block."
            ) from exc
        if len(labels) != 1:
            continue
        candidates.append(
            _LabeledStructuralBlock(
                _structural_kind(match.group("name")),
                labels[0].fields[0].strip(),
                match.start(),
                match.end(),
            )
        )
    counts: dict[tuple[str, str], int] = {}
    for block in candidates:
        key = (block.kind, block.label)
        counts[key] = counts.get(key, 0) + 1
    return [block for block in candidates if counts[(block.kind, block.label)] == 1]


def _canonical_structural_content(text: str) -> str:
    """Normalize only TeX-nonrendering comments and source layout whitespace."""
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
    normalized = " ".join("".join(pieces).split())
    normalized = re.sub(r"\\([A-Za-z@]+\*?)\s+(?=[{\[])", r"\\\1", normalized)
    normalized = re.sub(r"(?<=[{\[])\s+|\s+(?=[}\]])", "", normalized)
    return re.sub(r"}\s+{", "}{", normalized)


_EQUATION_TEXT_COMMANDS = frozenset(
    {"mbox", "text", "textbf", "textit", "textrm", "textsf", "texttt"}
)


def _normalized_equation_body(text: str) -> str:
    """Return a lightweight identity projection for one display body.

    TeX ignores ordinary whitespace in math mode, but whitespace inside text
    commands remains visible. Labels and tags are structural metadata rather
    than mathematical content, so they do not participate in this identity.
    """
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
                try:
                    _field, cursor = extract_braced(text, command_end)
                except ValueError as exc:
                    raise WorkflowError("Malformed label or tag in equation.") from exc
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
            if preserve_stack and preserve_stack[-1]:
                if pieces and pieces[-1] != " ":
                    pieces.append(" ")
            cursor += 1
            continue
        pending_text_group = False
        pieces.append(character)
        cursor += 1
    return "".join(pieces)


def _caption_fields(
    text: str,
) -> dict[tuple[str, int, int], tuple[str, int, int, int, int]]:
    """Return caption fields keyed by command kind, occurrence, and field index."""
    result: dict[tuple[str, int, int], tuple[str, int, int, int, int]] = {}
    for name, field_count in (("caption", 1), ("bicaption", 2)):
        try:
            commands = scan_tex_commands(text, (name,), field_count=field_count)
        except ValueError as exc:
            raise WorkflowError(f"Malformed \\{name} in structural block.") from exc
        for occurrence, command in enumerate(commands):
            cursor = command.start + len(command.name) + 1
            for field_index, field in enumerate(command.fields):
                opening = skip_tex_space(text, cursor)
                _content, cursor = extract_braced(text, cursor)
                result[(name, occurrence, field_index)] = (
                    field,
                    opening + 1,
                    cursor - 1,
                    command.start,
                    command.end,
                )
    return result


def _owners_for_new_span(
    start: int,
    end: int,
    provenance: ProvenanceSource | None,
    evidence: list[HighlightSpan],
) -> list[HighlightSpan]:
    if provenance is not None:
        return [
            HighlightSpan(left, right, owner)
            for left, right, owner in split_by_review_provenance(provenance, start, end)
        ]
    owners = {
        span.review_ids for span in evidence if span.start < end and span.end > start
    }
    owner = next(iter(owners)) if len(owners) == 1 else None
    return [HighlightSpan(start, end, owner)]


def _exact_caption_additions(
    parent_field: str | None,
    current_field: str,
    current_start: int,
    provenance: ProvenanceSource | None,
    evidence: list[HighlightSpan],
) -> list[HighlightSpan]:
    """Return exact current additions inside one already identity-matched caption."""
    if parent_field is None:
        return _owners_for_new_span(
            current_start,
            current_start + len(current_field),
            provenance,
            evidence,
        )
    prefix = 0
    while (
        prefix < len(parent_field)
        and prefix < len(current_field)
        and parent_field[prefix] == current_field[prefix]
    ):
        prefix += 1
    suffix = 0
    while (
        suffix < len(parent_field) - prefix
        and suffix < len(current_field) - prefix
        and parent_field[-suffix - 1] == current_field[-suffix - 1]
    ):
        suffix += 1
    new_end = len(current_field) - suffix
    if prefix == new_end:
        return []
    selected = current_field[prefix:new_end]
    start = current_start + prefix
    end = current_start + new_end
    if any(character in selected for character in "\\{}[]"):
        start = current_start
        end = current_start + len(current_field)
    return _owners_for_new_span(start, end, provenance, evidence)


def _subtract_intervals(
    spans: list[HighlightSpan], intervals: list[tuple[int, int]]
) -> list[HighlightSpan]:
    retained: list[HighlightSpan] = []
    for span in spans:
        fragments = [(span.start, span.end)]
        for interval_start, interval_end in sorted(intervals):
            revised: list[tuple[int, int]] = []
            for start, end in fragments:
                if interval_end <= start or interval_start >= end:
                    revised.append((start, end))
                    continue
                if start < interval_start:
                    revised.append((start, interval_start))
                if interval_end < end:
                    revised.append((interval_end, end))
            fragments = revised
        retained.extend(
            HighlightSpan(start, end, span.review_ids, span.kind)
            for start, end in fragments
            if start < end
        )
    return merge_spans(retained)


def _document_bounds(text: str) -> tuple[int, int]:
    begin = text.find(r"\begin{document}")
    end = text.rfind(r"\end{document}")
    if begin < 0 or end < begin:
        raise WorkflowError("Current source has no complete document environment.")
    return begin + len(r"\begin{document}"), end


def _paragraph_seams(text: str) -> list[tuple[int, int, str]]:
    """Return immutable current paragraph delimiters without parsing LaTeX."""
    begin, end = _document_bounds(text)
    seams = [
        (begin + match.start(), begin + match.end(), "paragraph_blank_line")
        for match in _PARAGRAPH_SEPARATOR.finditer(text[begin:end])
    ]
    seams.extend(
        (match.start(), match.end(), "paragraph_par")
        for match in _PAR_COMMAND.finditer(text, begin, end)
        if not is_escaped(text, match.start()) and not is_commented(text, match.start())
    )
    return sorted(seams)


def _structural_seams(text: str) -> list[tuple[int, int, str]]:
    """Return command tokens that a text-color wrapper must not enclose."""
    begin, end = _document_bounds(text)
    seams: list[tuple[int, int, str]] = []
    for match in _ENVIRONMENT_BOUNDARY.finditer(text, begin, end):
        if match.group("name") not in _TOPOLOGY_ENVIRONMENTS:
            continue
        if is_commented(text, match.start()):
            continue
        seams.append(
            (
                match.start(),
                match.end(),
                f"{match.group('name')}_{match.group('edge')}",
            )
        )
    for command in scan_tex_commands(
        text,
        ("section", "subsection", "subsubsection", "paragraph", "caption"),
        field_count=1,
    ):
        if begin <= command.start < end:
            opening = skip_tex_space(text, command.start + len(command.name) + 1)
            seams.append((command.start, opening + 1, f"heading_{command.name}"))
            seams.append((command.end - 1, command.end, f"heading_{command.name}_end"))
    item_commands = re.compile(r"\\item(?![A-Za-z@])")
    for match in item_commands.finditer(text, begin, end):
        if not is_escaped(text, match.start()) and not is_commented(
            text, match.start()
        ):
            seams.append((match.start(), match.end(), "list_item"))
    return sorted(seams)


def _comment_seams(text: str) -> list[tuple[int, int, str]]:
    """Keep comments and their swallowed newline outside revision macros."""
    begin, end = _document_bounds(text)
    seams: list[tuple[int, int, str]] = []
    cursor = begin
    while cursor < end:
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor, end)
            stop = end if newline < 0 else newline + 1
            seams.append((cursor, stop, "comment"))
            cursor = stop
            continue
        cursor += 1
    return seams


def _topology_events(text: str) -> tuple[tuple[str, int, int], ...]:
    events = [
        (kind, start, end)
        for start, end, kind in (*_paragraph_seams(text), *_structural_seams(text))
    ]
    return tuple(sorted(events, key=lambda item: (item[1], item[2], item[0])))


def _topology_context(text: str, offset: int) -> tuple[int, str]:
    line = text.count("\n", 0, max(0, offset)) + 1
    left = max(0, text.rfind("\n", 0, max(0, offset - 1)))
    right = text.find("\n", min(len(text), offset + 1))
    if right < 0:
        right = len(text)
    context = text[left:right].strip().replace("\n", r"\n")
    return line, context[:240]


def validate_topology_identity(
    clean: str,
    marked_projection: str,
    source: Path,
) -> TopologyIdentity:
    """Fail when stripped marked source changes current structural seams."""
    clean_events = _topology_events(clean)
    marked_events = _topology_events(marked_projection)
    if clean_events != marked_events:
        clean_event = marked_event = None
        for clean_item, marked_item in zip_longest(clean_events, marked_events):
            if clean_item != marked_item:
                clean_event, marked_event = clean_item, marked_item
                break
        clean_offset = clean_event[1] if clean_event is not None else len(clean)
        marked_offset = (
            marked_event[1] if marked_event is not None else len(marked_projection)
        )
        clean_line, clean_context = _topology_context(clean, clean_offset)
        marked_line, marked_context = _topology_context(
            marked_projection, marked_offset
        )
        boundary = (
            clean_event[0]
            if clean_event is not None
            else marked_event[0]
            if marked_event is not None
            else "unknown"
        )
        raise WorkflowError(
            "CLEAN_MARKED_TOPOLOGY_MISMATCH\n"
            f"file: {source.resolve()}\n"
            f"nearest line: clean={clean_line}, marked={marked_line}\n"
            f"boundary type: {boundary}\n"
            f"clean context: {clean_context}\n"
            f"marked context: {marked_context}"
        )
    clean_paragraphs = len(_paragraph_blocks(clean))
    marked_paragraphs = len(_paragraph_blocks(marked_projection))
    clean_boundaries = sum(
        kind.startswith("paragraph_") for kind, _start, _end in clean_events
    )
    marked_boundaries = sum(
        kind.startswith("paragraph_") for kind, _start, _end in marked_events
    )
    return TopologyIdentity(
        clean_paragraphs,
        marked_paragraphs,
        clean_boundaries,
        marked_boundaries,
    )


def display_evidence_is_covered(current: str, evidence: str) -> bool:
    """Return whether labeled formula evidence belongs to one current display.

    ``latexdiff --math-markup=WHOLE`` may normalize harmless source whitespace
    inside a formula, so its field is not always an exact current substring.
    A unique current display label is a narrow structural identity; the normal
    whole-display comparison remains responsible for the actual highlight.
    """
    labels = set(re.findall(r"\\label\{([^{}]+)\}", evidence))
    if not labels:
        return False
    matches = 0
    for block in _display_blocks(current):
        block_labels = set(
            re.findall(r"\\label\{([^{}]+)\}", current[block.start : block.end])
        )
        if labels <= block_labels:
            matches += 1
    return matches == 1


def _paragraph_blocks(text: str) -> list[_CurrentBlock]:
    begin, end = _document_bounds(text)
    blocks: list[_CurrentBlock] = []
    cursor = begin
    for start, stop, _kind in _paragraph_seams(text):
        if start < begin or stop > end:
            continue
        _append_paragraph(blocks, text, cursor, start)
        cursor = stop
    _append_paragraph(blocks, text, cursor, end)
    return blocks


def _append_paragraph(
    blocks: list[_CurrentBlock], text: str, start: int, end: int
) -> None:
    candidate = text[start:end]
    stripped = candidate.strip()
    if not stripped or re.search(
        r"\\(?:begin|end|section|subsection|subsubsection|paragraph|caption)\b",
        stripped,
    ):
        return
    left = start + candidate.find(stripped)
    blocks.append(_CurrentBlock("paragraph", left, left + len(stripped)))


def _simple_blocks(text: str) -> list[_CurrentBlock]:
    return sorted(
        [*_command_field_blocks(text), *_paragraph_blocks(text)],
        key=lambda item: (item.start, item.end),
    )


def merge_spans(spans: list[HighlightSpan]) -> list[HighlightSpan]:
    """Sort and validate intervals without joining structural blocks."""
    merged: list[HighlightSpan] = []
    for span in sorted(spans, key=lambda item: (item.start, item.end)):
        if span.start == span.end:
            continue
        if span.start < 0 or span.end < span.start:
            raise WorkflowError("Invalid highlighted current-source interval.")
        if merged and span.start < merged[-1].end:
            if span.end <= merged[-1].end and span.review_ids == merged[-1].review_ids:
                continue
            raise WorkflowError("Highlighted current-source intervals overlap.")
        merged.append(span)
    return merged


def _trim_wrapper_whitespace(text: str, span: HighlightSpan) -> HighlightSpan | None:
    """Keep TeX whitespace tokens outside a text-color wrapper.

    Only the interval edges move; source bytes remain owned by the untouched
    slices assembled around the wrapper. Internal whitespace is unchanged.
    """
    if span.kind in {"citation", "display"}:
        return span
    start = span.start
    end = span.end
    while start < end:
        if text.startswith(r"\ ", start):
            start += 2
        elif text[start].isspace() or text[start] == "~":
            start += 1
        else:
            break
    while end > start:
        if end - start >= 2 and text[end - 2 : end] == r"\ ":
            end -= 2
        elif text[end - 1].isspace() or text[end - 1] == "~":
            end -= 1
        else:
            break
    if start == end:
        return None
    return HighlightSpan(start, end, span.review_ids, span.kind)


def preserve_topology_seams(
    text: str, spans: list[HighlightSpan]
) -> list[HighlightSpan]:
    """Split text highlights so current delimiters remain outside all macros."""
    seams = [
        *_paragraph_seams(text),
        *_structural_seams(text),
        *_comment_seams(text),
    ]
    protected: list[HighlightSpan] = []
    for span in merge_spans(spans):
        if span.kind in {"citation", "display"}:
            protected.append(span)
            continue
        fragments = [(span.start, span.end)]
        for seam_start, seam_end, _kind in seams:
            if seam_end <= span.start or seam_start >= span.end:
                continue
            revised: list[tuple[int, int]] = []
            for start, end in fragments:
                if seam_end <= start or seam_start >= end:
                    revised.append((start, end))
                    continue
                if start < seam_start:
                    revised.append((start, seam_start))
                if seam_end < end:
                    revised.append((seam_end, end))
            fragments = revised
        for start, end in fragments:
            if start >= end or not _visible_length(text[start:end]):
                continue
            trimmed = _trim_wrapper_whitespace(
                text, HighlightSpan(start, end, span.review_ids, span.kind)
            )
            if trimmed is not None:
                protected.append(trimmed)
    return merge_spans(protected)


def preserve_text_command_shells(
    text: str,
    spans: list[HighlightSpan],
    command_names: tuple[str, ...],
) -> list[HighlightSpan]:
    """Keep deferred frontmatter commands outside visible color scopes."""
    if not command_names:
        return spans
    try:
        commands = scan_tex_commands(text, command_names, field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed prose-bearing frontmatter command.") from exc
    fields = [
        (
            command.start,
            skip_tex_space(text, command.start + len(command.name) + 1) + 1,
            command.end - 1,
            command.end,
        )
        for command in commands
    ]
    protected: list[HighlightSpan] = []
    for span in merge_spans(spans):
        fragments = [(span.start, span.end)]
        for command_start, field_start, field_end, command_end in fields:
            revised: list[tuple[int, int]] = []
            for start, end in fragments:
                if command_end <= start or command_start >= end:
                    revised.append((start, end))
                    continue
                if start < command_start:
                    revised.append((start, command_start))
                inner_start = max(start, field_start)
                inner_end = min(end, field_end)
                if inner_start < inner_end:
                    revised.append((inner_start, inner_end))
                if command_end < end:
                    revised.append((command_end, end))
            fragments = revised
        protected.extend(
            HighlightSpan(start, end, span.review_ids, span.kind)
            for start, end in fragments
            if start < end
        )
    return merge_spans(protected)


def _lexical_atom_counts(text: str) -> tuple[int, int]:
    """Count visible CJK atoms, Latin words, and digit runs without tokenization."""
    visible = re.sub(r"%[^\n]*|\\[A-Za-z@]+\*?|\\.", "", text)
    cjk_atoms = len(re.findall(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]", visible))
    latin_words = len(re.findall(r"[A-Za-z]+", visible))
    digit_runs = len(re.findall(r"\d+", visible))
    return cjk_atoms + latin_words + digit_runs, latin_words


def _tiny_island_gap_is_protected(gap: str) -> bool:
    """Protect citation/reference/link commands and complete math expressions."""
    if re.search(
        r"(?<!\\)\$.*?(?<!\\)\$|\\\(.*?\\\)|\\\[.*?\\\]"
        r"|https?://[^\s{}]+|10\.\d{4,9}/[^\s{}]+",
        gap,
        re.S,
    ):
        return True
    try:
        return any(
            scan_tex_commands(gap, names, field_count=fields)
            for names, fields in (
                (_CITATION_COMMANDS, 1),
                (_REFERENCE_COMMANDS, 1),
                (_ONE_FIELD_LINK_COMMANDS, 1),
                (("href",), 2),
            )
        )
    except ValueError:
        return True


def _overlaps_sorted_interval(
    intervals: list[tuple[int, int]], index: int, start: int, end: int
) -> tuple[bool, int]:
    while index < len(intervals) and intervals[index][1] <= start:
        index += 1
    return index < len(intervals) and intervals[index][0] < end, index


def coalesce_tiny_unchanged_islands(
    text: str, spans: list[HighlightSpan]
) -> tuple[list[HighlightSpan], TinyIslandAudit]:
    """Visually absorb tiny dense gaps between equal-provenance fine spans."""
    ordered = merge_spans(spans)
    if len(ordered) < 2:
        return ordered, TinyIslandAudit()
    boundaries = sorted(
        (start, end)
        for start, end, _kind in (
            *_paragraph_seams(text),
            *_structural_seams(text),
            *_comment_seams(text),
        )
    )
    boundary_index = 0
    joins: list[bool] = []
    audit = TinyIslandAudit()
    for left, right in pairwise(ordered):
        gap_start, gap_end = left.end, right.start
        join = False
        if gap_start >= gap_end:
            joins.append(False)
            continue
        audit.examined += 1
        gap = text[gap_start:gap_end]
        if left.review_ids != right.review_ids:
            audit.rejected_provenance += 1
        elif left.kind != "text" or right.kind != "text":
            audit.rejected_protected += 1
        elif _tiny_island_gap_is_protected(gap):
            audit.rejected_protected += 1
        else:
            has_boundary, boundary_index = _overlaps_sorted_interval(
                boundaries, boundary_index, gap_start, gap_end
            )
            left_tail = text[left.start : left.end].rstrip()
            if (
                has_boundary
                or (left_tail and left_tail[-1] in _SENTENCE_BOUNDARIES)
                or any(character in _SENTENCE_BOUNDARIES for character in gap)
            ):
                audit.rejected_boundary += 1
            else:
                gap_atoms, latin_words = _lexical_atom_counts(gap)
                if (
                    gap_atoms <= _TINY_ISLAND_MAX_ATOMS
                    and latin_words <= _TINY_ISLAND_MAX_LATIN_WORDS
                ):
                    left_atoms, _ = _lexical_atom_counts(text[left.start : left.end])
                    right_atoms, _ = _lexical_atom_counts(text[right.start : right.end])
                    modified = left_atoms + right_atoms
                    total = modified + gap_atoms
                    if total == 0 or (
                        modified * 100 >= total * _TINY_ISLAND_DENSITY_PERCENT
                    ):
                        join = True
                        audit.coalesced += 1
                    else:
                        audit.rejected_density += 1
        joins.append(join)
    result = [ordered[0]]
    for join, right in zip(joins, ordered[1:], strict=True):
        if join:
            left = result[-1]
            result[-1] = HighlightSpan(
                left.start, right.end, left.review_ids, left.kind
            )
        else:
            result.append(right)
    return result, audit


def suppress_exact_moves(
    parent: str,
    current: str,
    spans: list[HighlightSpan],
    provenance: ProvenanceSource | None = None,
) -> tuple[list[HighlightSpan], int]:
    """Suppress false additions from exact prose or stable-label block moves."""
    parent_hashes = {
        normalized_block_hash(parent[block.start : block.end])
        for block in _simple_blocks(parent)
        if _visible_length(parent[block.start : block.end])
    }
    moved = [
        (block.start, block.end)
        for block in _simple_blocks(current)
        if normalized_block_hash(current[block.start : block.end]) in parent_hashes
        and any(span.start < block.end and span.end > block.start for span in spans)
    ]
    retained = [
        span
        for span in spans
        if not any(start <= span.start and span.end <= end for start, end in moved)
    ]

    parent_structures = {
        (block.kind, block.label): block for block in _labeled_structural_blocks(parent)
    }
    protected_structures: list[tuple[int, int]] = []
    unchanged_structure_count = 0
    protected_caption_commands: list[tuple[int, int]] = []
    caption_additions: list[HighlightSpan] = []
    for current_block in _labeled_structural_blocks(current):
        parent_block = parent_structures.get((current_block.kind, current_block.label))
        if parent_block is None:
            continue
        parent_text = parent[parent_block.start : parent_block.end]
        current_text = current[current_block.start : current_block.end]
        if _canonical_structural_content(parent_text) == _canonical_structural_content(
            current_text
        ):
            if any(
                span.start < current_block.end and span.end > current_block.start
                for span in retained
            ):
                protected_structures.append((current_block.start, current_block.end))
                unchanged_structure_count += 1
            continue

        parent_fields = _caption_fields(parent_text)
        current_fields = _caption_fields(current_text)
        current_caption_commands = {
            (current_block.start + value[3], current_block.start + value[4])
            for value in current_fields.values()
        }
        if current_block.kind == "figure":
            protected_structures.append((current_block.start, current_block.end))
        else:
            protected_caption_commands.extend(current_caption_commands)
        for key, (
            current_field,
            field_start,
            _field_end,
            _command_start,
            _command_end,
        ) in current_fields.items():
            parent_field = parent_fields.get(key)
            parent_value = parent_field[0] if parent_field is not None else None
            if parent_value is not None and _canonical_structural_content(
                parent_value
            ) == _canonical_structural_content(current_field):
                continue
            caption_additions.extend(
                _exact_caption_additions(
                    parent_value,
                    current_field,
                    current_block.start + field_start,
                    provenance,
                    spans,
                )
            )

    retained = _subtract_intervals(
        retained, [*protected_structures, *protected_caption_commands]
    )
    return merge_spans([*retained, *caption_additions]), len(
        moved
    ) + unchanged_structure_count


def adaptive_blocks(
    text: str, spans: list[HighlightSpan]
) -> tuple[list[HighlightSpan], int, int, int]:
    """Collapse heavily revised single-owner blocks at the fixed 60% rule."""
    # Wrapping an otherwise empty paragraph separator in a macro consumes the
    # blank line and changes paragraph topology. Whitespace/comment-only
    # latexdiff additions are evidence, never renderable spans.
    collapsed = preserve_topology_seams(text, spans)
    whole = 0
    fine = 0
    blocks = _simple_blocks(text)
    for block in blocks:
        intersecting = [
            span
            for span in collapsed
            if span.start < block.end and span.end > block.start
        ]
        enclosed = [
            span
            for span in intersecting
            if block.start <= span.start and span.end <= block.end
        ]
        if not enclosed:
            continue
        total = _visible_length(text[block.start : block.end])
        added = sum(_visible_length(text[item.start : item.end]) for item in enclosed)
        owners = {item.review_ids for item in enclosed}
        safely_enclosed = len(enclosed) == len(intersecting)
        if total and added / total >= 0.60 and len(owners) == 1 and safely_enclosed:
            collapsed = [item for item in collapsed if item not in enclosed]
            collapsed.append(
                HighlightSpan(block.start, block.end, enclosed[0].review_ids)
            )
            whole += 1
        else:
            fine += 1
    return merge_spans(collapsed), len(blocks), fine, whole


def _owners_for_interval(
    provenance: ProvenanceSource,
    start: int,
    end: int,
    additions: list[HighlightSpan],
) -> tuple[str, ...] | None:
    owners = {
        span.review_ids for span in additions if span.start < end and span.end > start
    }
    if len(owners) == 1:
        return next(iter(owners))
    provenance_owners = {
        owner
        for _left, _right, owner in split_by_review_provenance(provenance, start, end)
        if owner is not None
    }
    return next(iter(provenance_owners)) if len(provenance_owners) == 1 else None


def citation_spans(
    parent: str, provenance: ProvenanceSource, additions: list[HighlightSpan]
) -> list[HighlightSpan]:
    """Track current citation groups whose BibTeX-key relationship changed."""
    try:
        old = scan_tex_commands(parent, _CITATION_COMMANDS, field_count=1)
        current = scan_tex_commands(provenance.text, _CITATION_COMMANDS, field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed citation command in revision source.") from exc
    old_sets = [
        frozenset(key.strip() for key in item.fields[0].split(",")) for item in old
    ]
    result: list[HighlightSpan] = []
    for index, command in enumerate(current):
        keys = frozenset(key.strip() for key in command.fields[0].split(","))
        if keys in old_sets:
            continue
        previous = old_sets[index] if index < len(old_sets) else frozenset()
        if keys and keys.issubset(previous):
            continue
        owner = _owners_for_interval(provenance, command.start, command.end, additions)
        result.append(HighlightSpan(command.start, command.end, owner, "citation"))
    return result


def protected_citation_spans(
    provenance: ProvenanceSource,
    additions: list[HighlightSpan],
    changes: list[HighlightSpan],
) -> list[HighlightSpan]:
    """Return pure-blue citation islands intersecting revision highlights.

    Changed reviewer-owned citations retain their IDs solely for location
    instrumentation; citation appearance is link blue for every ownership state.
    """
    try:
        commands = scan_tex_commands(provenance.text, _CITATION_COMMANDS, field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed citation command in revision source.") from exc
    changed = {(item.start, item.end): item.review_ids for item in changes}
    return [
        HighlightSpan(
            command.start,
            command.end,
            changed.get((command.start, command.end)),
            "citation",
        )
        for command in commands
        if (command.start, command.end) in changed
        or any(
            span.start < command.end and span.end > command.start for span in additions
        )
    ]


def added_citation_provenance(
    parent: str,
    provenance: ProvenanceSource,
    additions: list[HighlightSpan],
) -> dict[str, CitationProvenance]:
    """Return citation-primary ownership for keys absent from the parent."""
    try:
        old = scan_tex_commands(parent, _CITATION_COMMANDS, field_count=1)
        current = scan_tex_commands(provenance.text, _CITATION_COMMANDS, field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed citation command in revision source.") from exc
    parent_keys = {
        key.strip()
        for command in old
        for key in command.fields[0].split(",")
        if key.strip()
    }
    result: dict[str, CitationProvenance] = {}
    for command in current:
        owner = _owners_for_interval(provenance, command.start, command.end, additions)
        line = provenance.text.count("\n", 0, command.start) + 1
        for key in (item.strip() for item in command.fields[0].split(",")):
            if not key or key in parent_keys:
                continue
            previous = result.get(key)
            if previous is None:
                result[key] = CitationProvenance(owner, (line,))
                continue
            if (previous.review_ids is None) != (owner is None):
                raise WorkflowError(
                    "REFERENCE_PROVENANCE_CONFLICT\n"
                    f"key: {key}\n"
                    "citation provenance: AUTHOR and REVIEWER\n"
                    f"current source lines: {(*previous.source_lines, line)}"
                )
            if owner is None:
                review_ids = None
            else:
                assert previous.review_ids is not None
                review_ids = tuple(dict.fromkeys((*previous.review_ids, *owner)))
            result[key] = CitationProvenance(
                review_ids,
                tuple(dict.fromkeys((*previous.source_lines, line))),
            )
    return result


def _classify_equations(
    parent: str, provenance: ProvenanceSource, additions: list[HighlightSpan]
) -> tuple[list[HighlightSpan], list[tuple[int, int]], EquationAudit]:
    """Classify displays before applying whole-current-equation highlighting."""
    old = _display_blocks(parent)
    current = _display_blocks(provenance.text)
    old_hashes = {
        _normalized_equation_body(parent[item.start : item.end]) for item in old
    }
    old_labeled = {
        block.label: block
        for block in _labeled_structural_blocks(parent)
        if block.kind == "display"
    }
    current_labeled = {
        (block.start, block.end): block
        for block in _labeled_structural_blocks(provenance.text)
        if block.kind == "display"
    }
    result: list[HighlightSpan] = []
    unchanged: list[tuple[int, int]] = []
    identical = 0
    ambiguous = 0
    for index, block in enumerate(current):
        labeled = current_labeled.get((block.start, block.end))
        if labeled is not None and (
            old_labeled_block := old_labeled.get(labeled.label)
        ):
            old_text = parent[old_labeled_block.start : old_labeled_block.end]
            current_text = provenance.text[labeled.start : labeled.end]
            if _normalized_equation_body(old_text) == _normalized_equation_body(
                current_text
            ):
                identical += 1
                unchanged.append((block.start, block.end))
                continue
        current_hash = _normalized_equation_body(
            provenance.text[block.start : block.end]
        )
        previous_hash = (
            _normalized_equation_body(parent[old[index].start : old[index].end])
            if index < len(old)
            else None
        )
        if current_hash == previous_hash or current_hash in old_hashes:
            identical += 1
            unchanged.append((block.start, block.end))
            continue
        owner = _owners_for_interval(provenance, block.start, block.end, additions)
        result.append(HighlightSpan(block.start, block.end, owner, "display"))
    return (
        result,
        unchanged,
        EquationAudit(len(current), identical, len(result), ambiguous),
    )


def analyze_equations(
    parent: str, provenance: ProvenanceSource, additions: list[HighlightSpan]
) -> tuple[list[HighlightSpan], EquationAudit]:
    """Return changed display spans and aggregate identity decisions."""
    spans, _unchanged, audit = _classify_equations(parent, provenance, additions)
    return spans, audit


def resolve_equation_spans(
    parent: str, provenance: ProvenanceSource, additions: list[HighlightSpan]
) -> tuple[list[HighlightSpan], list[HighlightSpan], EquationAudit]:
    """Veto every fine span inside normalized-identical current displays."""
    spans, unchanged, audit = _classify_equations(parent, provenance, additions)
    return _subtract_intervals(additions, unchanged), spans, audit


def equation_spans(
    parent: str, provenance: ProvenanceSource, additions: list[HighlightSpan]
) -> list[HighlightSpan]:
    """Return whole-current spans for substantively changed displays."""
    spans, _audit = analyze_equations(parent, provenance, additions)
    return spans


def replace_special_spans(
    additions: list[HighlightSpan], special: list[HighlightSpan]
) -> list[HighlightSpan]:
    ranges = sorted((item.start, item.end) for item in special)
    retained: list[HighlightSpan] = []
    for item in additions:
        fragments = [(item.start, item.end)]
        for protected_start, protected_end in ranges:
            revised: list[tuple[int, int]] = []
            for start, end in fragments:
                if protected_end <= start or protected_start >= end:
                    revised.append((start, end))
                    continue
                if start < protected_start:
                    revised.append((start, protected_start))
                if protected_end < end:
                    revised.append((protected_end, end))
            fragments = revised
        retained.extend(
            HighlightSpan(start, end, item.review_ids, item.kind)
            for start, end in fragments
            if start < end
        )
    return merge_spans([*retained, *special])


def _highlight_macro(span: HighlightSpan, content: str) -> str:
    if span.kind == "citation":
        link = f"\\SCIReferenceLink{{{content}}}"
        if span.review_ids is not None:
            return f"\\SCIReviewReferenceSpan{{{','.join(span.review_ids)}}}{{{link}}}"
        return link
    if span.review_ids is None:
        return f"\\DIFadd{{{content}}}"
    return (
        f"\\SCIReviewSpan{{{','.join(span.review_ids)}}}{{\\DIFaddReview{{{content}}}}}"
    )


def _display_markup(span: HighlightSpan, content: str) -> str:
    protected_content = _protect_display_citations(content)
    begin = re.match(r"(\\begin\{[^}]+\})", protected_content)
    end = re.search(r"(\\end\{[^}]+\})$", protected_content)
    if begin is None or end is None:
        raise WorkflowError("Malformed current display selected for highlighting.")
    opening = (
        r"\SCIAuthorDisplayBegin{}"
        if span.review_ids is None
        else f"\\SCIReviewDisplayBegin{{{','.join(span.review_ids)}}}"
    )
    return (
        protected_content[: begin.end()]
        + opening
        + protected_content[begin.end() : end.start()]
        + r"\SCIDisplayEnd{}"
        + protected_content[end.start() :]
    )


def _protect_display_citations(content: str) -> str:
    """Keep citation commands link blue inside a whole colored display."""
    try:
        commands = scan_tex_commands(content, _CITATION_COMMANDS, field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed citation command in current display.") from exc
    pieces: list[str] = []
    cursor = 0
    for command in commands:
        pieces.extend(
            (
                content[cursor : command.start],
                f"\\SCIReferenceLink{{{content[command.start : command.end]}}}",
            )
        )
        cursor = command.end
    pieces.append(content[cursor:])
    return "".join(pieces)


def _citation_command_starts(text: str) -> set[int]:
    try:
        commands = scan_tex_commands(text, _CITATION_COMMANDS, field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed citation command in current source.") from exc
    return {command.start for command in commands}


def _ends_with_cjk_character(text: str, end: int) -> bool:
    if end <= 0:
        return False
    codepoint = ord(text[end - 1])
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def apply_highlights(text: str, spans: list[HighlightSpan]) -> str:
    """Insert only color/provenance markup into exact current-source bytes."""
    pieces: list[str] = []
    cursor = 0
    citation_starts = _citation_command_starts(text)
    for span in preserve_topology_seams(text, spans):
        if span.end > len(text):
            raise WorkflowError("Highlighted interval escaped current source.")
        pieces.append(text[cursor : span.start])
        content = text[span.start : span.end]
        pieces.append(
            _display_markup(span, content)
            if span.kind == "display"
            else _highlight_macro(span, content)
        )
        if (
            span.kind != "citation"
            and span.end in citation_starts
            and _ends_with_cjk_character(text, span.end)
        ):
            pieces.append(r"\SCIRevisionCitationSeam{}")
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _unwrap_command(text: str, name: str, fields: int, keep: int) -> str:
    try:
        commands = scan_tex_commands(text, (name,), field_count=fields)
    except ValueError as exc:
        raise WorkflowError(f"Malformed internal \\{name} markup.") from exc
    pieces: list[str] = []
    cursor = 0
    for command in commands:
        pieces.extend((text[cursor : command.start], command.fields[keep]))
        cursor = command.end
    pieces.append(text[cursor:])
    return "".join(pieces)


def strip_highlight_markup(text: str, style_begin: str, style_end: str) -> str:
    """Project a marked source back to its exact current scientific source."""
    start = text.find(style_begin)
    end = text.find(style_end)
    if (start < 0) != (end < 0):
        raise WorkflowError("Marked revision style boundaries are incomplete.")
    if start >= 0:
        cut = end + len(style_end)
        if text[cut : cut + 1] == "\n":
            cut += 1
        text = text[:start] + text[cut:]
    text = text.replace(r"\SCIRevisionCitationSeam{}", "")
    for name, fields, keep in (
        ("SCIReviewSpan", 2, 1),
        ("SCIReviewReferenceSpan", 2, 1),
        ("SCIReferenceLink", 1, 0),
        ("DIFaddReview", 1, 0),
        ("DIFadd", 1, 0),
    ):
        previous = None
        while previous != text:
            previous = text
            text = _unwrap_command(text, name, fields, keep)
    text = re.sub(r"\\SCI(?:Author|Review)DisplayBegin\{[^}]*\}", "", text)
    return text.replace(r"\SCIDisplayEnd{}", "")
