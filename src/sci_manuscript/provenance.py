"""Parse revision provenance without changing manuscript text semantics."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from .errors import WorkflowError
from .review_ids import validate_review_id_list
from .tex import command_at, extract_braced, is_escaped


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


def _provenance_field(text: str, start: int) -> tuple[str, int]:
    try:
        return extract_braced(text, start)
    except ValueError as exc:
        raise WorkflowError("Unbalanced braces in provenance command.") from exc


def _parse_review_ids(raw: str) -> tuple[str, ...]:
    return validate_review_id_list(raw)


def extract_provenance(text: str) -> ProvenanceSource:
    """Remove provenance wrappers and retain reviewer spans as a sidecar map.

    ``\\review{ids}{body}`` contributes ``body`` verbatim to the clean source and
    records non-overlapping effective reviewer intervals. Nested scopes inherit
    and extend their parent IDs in first-seen order.
    """

    def union_ids(
        inherited: tuple[str, ...], declared: tuple[str, ...]
    ) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*inherited, *declared)))

    def parse(
        fragment: str,
        *,
        inherited: tuple[str, ...] = (),
    ) -> ProvenanceSource:
        pieces: list[str] = []
        spans: list[ReviewSpan] = []
        length = 0
        cursor = 0

        def append(value: str) -> None:
            nonlocal length
            pieces.append(value)
            length += len(value)

        while cursor < len(fragment):
            if fragment[cursor] == "%" and not is_escaped(fragment, cursor):
                newline = fragment.find("\n", cursor)
                end = len(fragment) if newline == -1 else newline + 1
                append(fragment[cursor:end])
                cursor = end
                continue

            if not is_escaped(fragment, cursor) and command_at(
                fragment, cursor, "review"
            ):
                ids_raw, after_ids = _provenance_field(
                    fragment, cursor + len(r"\review")
                )
                body, end = _provenance_field(fragment, after_ids)
                ids = union_ids(inherited, _parse_review_ids(ids_raw))
                parsed = parse(body, inherited=ids)
                start = length
                append(parsed.text)
                spans.extend(
                    ReviewSpan(span.review_ids, span.start + start, span.end + start)
                    for span in parsed.review_spans
                )
                cursor = end
                continue

            plain_start = cursor
            while cursor < len(fragment):
                if fragment[cursor] == "%" and not is_escaped(fragment, cursor):
                    break
                if not is_escaped(fragment, cursor) and command_at(
                    fragment, cursor, "review"
                ):
                    break
                cursor += 1
            append(fragment[plain_start:cursor])
            if inherited and plain_start != cursor:
                spans.append(
                    ReviewSpan(inherited, length - (cursor - plain_start), length)
                )

        merged: list[ReviewSpan] = []
        for span in sorted(spans, key=lambda item: (item.start, item.end)):
            if span.start == span.end:
                continue
            if (
                merged
                and merged[-1].end == span.start
                and merged[-1].review_ids == span.review_ids
            ):
                previous = merged[-1]
                merged[-1] = ReviewSpan(previous.review_ids, previous.start, span.end)
            else:
                merged.append(span)

        return ProvenanceSource(
            "".join(pieces),
            tuple(merged),
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
