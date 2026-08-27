"""Apply addition-only highlights to exact current-manuscript source bytes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path

from .errors import WorkflowError
from .provenance import ProvenanceSource, split_by_review_provenance
from .tex import (
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
    event_id: str | None = None


@dataclass(frozen=True)
class _CurrentBlock:
    kind: str
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


_DISPLAY_ENVIRONMENT = re.compile(
    r"\\begin\{(?P<name>equation\*?|align\*?|gather\*?|multline\*?|displaymath)\}"
    r".*?\\end\{(?P=name)\}",
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


def _display_blocks(text: str) -> list[_CurrentBlock]:
    return [
        _CurrentBlock("display", match.start(), match.end())
        for match in _DISPLAY_ENVIRONMENT.finditer(text)
        if not is_commented(text, match.start())
    ]


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
    return HighlightSpan(start, end, span.review_ids, span.kind, span.event_id)


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
                text,
                HighlightSpan(start, end, span.review_ids, span.kind, span.event_id),
            )
            if trimmed is not None:
                protected.append(trimmed)
    return merge_spans(protected)


def _owners_for_interval(
    provenance: ProvenanceSource,
    start: int,
    end: int,
    additions: list[HighlightSpan],
) -> tuple[str, ...] | None:
    del additions  # detector evidence cannot own scientific content
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
            HighlightSpan(start, end, item.review_ids, item.kind, item.event_id)
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
    if span.event_id is None:
        raise WorkflowError("REVISION_RENDER_UNAUTHORIZED: missing event ID.")
    if span.review_ids is None:
        return f"\\SciAuthorRevision{{{span.event_id}}}{{{content}}}"
    return (
        f"\\SCIReviewSpan{{{','.join(span.review_ids)}}}"
        f"{{\\SciReviewerRevision{{{span.event_id}}}"
        f"{{{','.join(span.review_ids)}}}{{{content}}}}}"
    )


def _display_markup(span: HighlightSpan, content: str) -> str:
    protected_content = _protect_display_citations(content)
    begin = re.match(r"(\\begin\{[^}]+\})", protected_content)
    end = re.search(r"(\\end\{[^}]+\})$", protected_content)
    if begin is None or end is None:
        raise WorkflowError("Malformed current display selected for highlighting.")
    if span.event_id is None:
        raise WorkflowError("REVISION_RENDER_UNAUTHORIZED: missing display event ID.")
    opening = (
        f"\\SciAuthorDisplayRevisionBegin{{{span.event_id}}}"
        if span.review_ids is None
        else (
            f"\\SCIReviewDisplayBegin{{{','.join(span.review_ids)}}}"
            f"\\SciReviewerDisplayRevisionBegin{{{span.event_id}}}"
            f"{{{','.join(span.review_ids)}}}"
        )
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
    prepared = preserve_topology_seams(text, spans)
    next_number = 0
    authorized: list[HighlightSpan] = []
    for span in prepared:
        if span.kind == "citation" or span.event_id is not None:
            authorized.append(span)
            continue
        next_number += 1
        authorized.append(
            HighlightSpan(
                span.start,
                span.end,
                span.review_ids,
                span.kind,
                f"sci:rev:adhoc:e{next_number:04d}",
            )
        )
    for span in authorized:
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
        ("SciReviewerRevision", 3, 2),
        ("SciAuthorRevision", 2, 1),
        ("DIFaddReview", 1, 0),
        ("DIFadd", 1, 0),
    ):
        previous = None
        while previous != text:
            previous = text
            text = _unwrap_command(text, name, fields, keep)
    text = re.sub(r"\\SCIReviewDisplayBegin\{[^}]*\}", "", text)
    text = re.sub(
        r"\\Sci(?:Author|Reviewer)DisplayRevisionBegin\{[^}]*\}"
        r"(?:\{[^}]*\})?",
        "",
        text,
    )
    return text.replace(r"\SCIDisplayEnd{}", "")
