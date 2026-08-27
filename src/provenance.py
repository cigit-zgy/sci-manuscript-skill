"""Parse revision provenance without changing manuscript text semantics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from .errors import WorkflowError
from .review_ids import validate_review_id_list
from .tex import command_at, extract_braced, is_escaped, skip_tex_space


def _provenance_seam_value(left: str, right: str) -> tuple[str, int]:
    r"""Join parser fragments without turning wrapper layout into ``\par``.

    A line break on each side of a removed ``\review`` delimiter is still only
    TeX inter-token whitespace in the wrapped source.  Concatenating the raw
    fragments can otherwise create a new blank physical line.  Preserve a
    paragraph boundary that already exists wholly on either side of the seam,
    but collapse seam-only whitespace to one ordinary space.
    """
    if not left or not right:
        return right, 0
    trailing = re.search(r"[ \t\r\n]+$", left)
    leading = re.match(r"[ \t\r\n]+", right)
    if trailing is None or leading is None:
        return right, 0
    left_space = trailing.group(0)
    right_space = leading.group(0)
    normalized_left = left_space.replace("\r\n", "\n")
    normalized_right = right_space.replace("\r\n", "\n")
    if "\n\n" in normalized_left or "\n\n" in normalized_right:
        return right, 0
    if normalized_left.count("\n") + normalized_right.count("\n") < 2:
        return right, 0
    return right[leading.end() :], leading.end()


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


def extract_provenance(
    text: str,
    *,
    source_path: Path | None = None,
) -> ProvenanceSource:
    """Remove provenance wrappers and retain reviewer spans as a sidecar map.

    ``\\review{ids}{body}`` contributes ``body`` verbatim to the clean source and
    records non-overlapping effective reviewer intervals. Nested scopes inherit
    and extend their parent IDs in first-seen order.
    """

    def union_ids(
        inherited: tuple[str, ...], declared: tuple[str, ...]
    ) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*inherited, *declared)))

    def invalid_command(
        offset: int,
        review_id: str,
        reason: str,
    ) -> WorkflowError:
        line_number = text.count("\n", 0, offset) + 1
        line_start = text.rfind("\n", 0, offset) + 1
        line_end = text.find("\n", offset)
        if line_end == -1:
            line_end = len(text)
        context = text[line_start:line_end].strip()
        file_label = str(source_path.resolve()) if source_path else "<in-memory TeX>"
        return WorkflowError(
            "REVIEW_PROVENANCE_INVALID\n"
            f"File: {file_label}\n"
            f"Line: {line_number}\n"
            f"ID: {review_id}\n"
            f"Reason: {reason}\n"
            f"Context: {context}"
        )

    def parse(
        fragment: str,
        *,
        inherited: tuple[str, ...] = (),
        base_offset: int = 0,
    ) -> ProvenanceSource:
        pieces: list[str] = []
        spans: list[ReviewSpan] = []
        length = 0
        cursor = 0

        def append(value: str) -> tuple[int, int, int]:
            nonlocal length
            if not value:
                return length, length, 0
            removed = 0
            if pieces:
                value, removed = _provenance_seam_value(pieces[-1], value)
            start = length
            if value:
                pieces.append(value)
                length += len(value)
            return start, length, removed

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
                command_offset = base_offset + cursor
                try:
                    ids_raw, after_ids = _provenance_field(
                        fragment, cursor + len(r"\review")
                    )
                except WorkflowError as exc:
                    raise invalid_command(
                        command_offset,
                        "<unavailable>",
                        str(exc),
                    ) from exc
                try:
                    declared_ids = validate_review_id_list(ids_raw)
                except WorkflowError as exc:
                    raise invalid_command(
                        command_offset,
                        ids_raw.strip() or "<empty>",
                        str(exc),
                    ) from exc
                body_opening = skip_tex_space(fragment, after_ids)
                try:
                    body, end = _provenance_field(fragment, after_ids)
                except WorkflowError as exc:
                    raise invalid_command(
                        command_offset,
                        ids_raw.strip(),
                        str(exc),
                    ) from exc
                ids = union_ids(inherited, declared_ids)
                parsed = parse(
                    body,
                    inherited=ids,
                    base_offset=base_offset + body_opening + 1,
                )
                start = length
                _, _, removed = append(parsed.text)
                if not parsed.text:
                    # An empty wrapper is an explicit deletion-only provenance
                    # marker. It owns no visible bytes but keeps the review ID
                    # auditable so the response can report no current location.
                    spans.append(ReviewSpan(ids, start, start))
                spans.extend(
                    ReviewSpan(
                        span.review_ids,
                        max(0, span.start - removed) + start,
                        max(0, span.end - removed) + start,
                    )
                    for span in parsed.review_spans
                    if span.end > removed
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
            appended_start, appended_end, _ = append(fragment[plain_start:cursor])
            if inherited and appended_start != appended_end:
                spans.append(ReviewSpan(inherited, appended_start, appended_end))

        merged: list[ReviewSpan] = []
        for span in sorted(spans, key=lambda item: (item.start, item.end)):
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
