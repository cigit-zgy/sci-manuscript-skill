"""Parse revision provenance without changing manuscript text semantics."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from .response import is_review_id
from .workspace import WorkflowError


@dataclass(frozen=True)
class ReviewSpan:
    """One reviewer-linked interval in provenance-free TeX source."""

    review_ids: tuple[str, ...]
    start: int
    end: int


@dataclass(frozen=True)
class ProvenanceSource:
    """Provenance-free TeX plus reviewer intervals in that exact string."""

    text: str
    review_spans: tuple[ReviewSpan, ...]


def _is_escaped(text: str, index: int) -> bool:
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def _skip_space(text: str, start: int) -> int:
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return cursor


def _extract_braced(text: str, start: int) -> tuple[str, int]:
    cursor = _skip_space(text, start)
    if cursor >= len(text) or text[cursor] != "{":
        raise WorkflowError("Provenance command requires a braced argument.")
    depth = 0
    opening = cursor
    while cursor < len(text):
        char = text[cursor]
        if char == "%" and not _is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        if char == "{" and not _is_escaped(text, cursor):
            depth += 1
        elif char == "}" and not _is_escaped(text, cursor):
            depth -= 1
            if depth == 0:
                return text[opening + 1 : cursor], cursor + 1
        cursor += 1
    raise WorkflowError("Unbalanced braces in provenance command.")


def _command_at(text: str, start: int, name: str) -> bool:
    if not text.startswith(name, start):
        return False
    end = start + len(name)
    return end >= len(text) or not (text[end].isalnum() or text[end] == "@")


def _parse_review_ids(raw: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not values:
        raise WorkflowError("\\review requires at least one reviewer ID.")
    invalid = [value for value in values if not is_review_id(value)]
    if invalid:
        raise WorkflowError(
            "Invalid reviewer ID(s): " + ", ".join(invalid) + "; expected E-1 or 1-1."
        )
    return values


def extract_provenance(text: str) -> ProvenanceSource:
    """Remove provenance wrappers and retain reviewer spans as a sidecar map.

    ``\\review{ids}{body}`` contributes ``body`` verbatim to the clean source and
    records the resulting character interval. ``\\user`` and legacy
    ``\\selfadd`` remain transparent. Nested reviewer scopes are rejected.
    """

    def parse(fragment: str, *, inside_review: bool = False) -> ProvenanceSource:
        pieces: list[str] = []
        spans: list[ReviewSpan] = []
        length = 0
        cursor = 0

        def append(value: str) -> None:
            nonlocal length
            pieces.append(value)
            length += len(value)

        while cursor < len(fragment):
            if fragment[cursor] == "%" and not _is_escaped(fragment, cursor):
                newline = fragment.find("\n", cursor)
                end = len(fragment) if newline == -1 else newline + 1
                append(fragment[cursor:end])
                cursor = end
                continue

            if _command_at(fragment, cursor, r"\review"):
                if inside_review:
                    raise WorkflowError(
                        "Nested \\review scopes are ambiguous; combine reviewer IDs "
                        "in one wrapper instead."
                    )
                ids_raw, after_ids = _extract_braced(
                    fragment, cursor + len(r"\review")
                )
                body, end = _extract_braced(fragment, after_ids)
                ids = _parse_review_ids(ids_raw)
                parsed = parse(body, inside_review=True)
                start = length
                append(parsed.text)
                spans.extend(
                    ReviewSpan(span.review_ids, span.start + start, span.end + start)
                    for span in parsed.review_spans
                )
                spans.append(ReviewSpan(ids, start, length))
                cursor = end
                continue

            transparent = None
            for name in (r"\user", r"\selfadd"):
                if _command_at(fragment, cursor, name):
                    transparent = name
                    break
            if transparent is not None:
                body, end = _extract_braced(fragment, cursor + len(transparent))
                parsed = parse(body, inside_review=inside_review)
                start = length
                append(parsed.text)
                spans.extend(
                    ReviewSpan(span.review_ids, span.start + start, span.end + start)
                    for span in parsed.review_spans
                )
                cursor = end
                continue

            append(fragment[cursor])
            cursor += 1

        return ProvenanceSource(
            "".join(pieces),
            tuple(sorted(spans, key=lambda item: (item.start, item.end))),
        )

    result = parse(text)
    previous_end = -1
    for span in result.review_spans:
        if span.start < previous_end:
            raise WorkflowError("Reviewer provenance intervals overlap ambiguously.")
        if span.start > span.end or span.end > len(result.text):
            raise WorkflowError("Reviewer provenance interval escaped clean source.")
        previous_end = span.end
    return result


def split_by_review_provenance(
    source: ProvenanceSource,
    start: int,
    end: int,
) -> tuple[tuple[int, int, tuple[str, ...] | None], ...]:
    """Split one clean-source interval at reviewer provenance boundaries."""
    if start < 0 or end < start or end > len(source.text):
        raise WorkflowError("Diff interval escaped provenance source.")
    if start == end:
        return ()
    boundaries = {start, end}
    for span in source.review_spans:
        if span.end <= start or span.start >= end:
            continue
        boundaries.add(max(start, span.start))
        boundaries.add(min(end, span.end))
    segments: list[tuple[int, int, tuple[str, ...] | None]] = []
    for left, right in pairwise(sorted(boundaries)):
        if left == right:
            continue
        owner: tuple[str, ...] | None = None
        for span in source.review_spans:
            if span.start <= left and right <= span.end:
                owner = span.review_ids
                break
        segments.append((left, right, owner))
    return tuple(segments)
