"""Match canonical manuscript regions and select current revision units."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

from .errors import WorkflowError
from .regions import (
    ManuscriptProjection,
    RegionKind,
    RevisionUnit,
    StructuralBlock,
    normalize_region_content,
    prose_sentence_units,
)


class ChangeReason(str, Enum):
    """Why one current revision unit is visible as changed."""

    CONTENT = "content"
    CURRENT_ONLY = "current_only"
    STRUCTURAL_MOVE = "structural_move"
    REORDERED = "reordered"


class ChangeState(str, Enum):
    """Finite owner-free state for one current revision-capable unit."""

    UNCHANGED = "UNCHANGED"
    CHANGED = "CHANGED"
    ADDED = "ADDED"
    MOVED_COMPATIBLE = "MOVED_COMPATIBLE"
    STRUCTURAL_CHANGED = "STRUCTURAL_CHANGED"
    AMBIGUOUS = "AMBIGUOUS"


class ProofKind(str, Enum):
    """Bounded proof vocabulary carried by truth decisions."""

    EXACT_IDENTITY = "exact_identity"
    NORMALIZED_IDENTITY = "normalized_identity"
    ESTABLISHED_CORRESPONDENCE_DIFFERENCE = "established_correspondence_difference"
    DETERMINISTIC_ADDITION = "deterministic_addition"
    STRUCTURAL_EVENT = "structural_event"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class ChangedUnit:
    """One owner-free current-source interval selected by region semantics."""

    region_kind: RegionKind
    structural_path: tuple[str, ...]
    source_start: int
    source_end: int
    reason: ChangeReason


@dataclass(frozen=True)
class UnitDecision:
    """One compact full-document truth decision without scientific prose."""

    current_id: str
    region_kind: RegionKind
    structural_path: tuple[str, ...]
    source_start: int
    source_end: int
    normalized_hash: str
    candidate_parent_ids: tuple[str, ...]
    state: ChangeState
    proof: ProofKind
    visual_authorized: bool


@dataclass(frozen=True)
class IdentityCertificate:
    """Proof that one current scientific unit must remain black."""

    certificate_id: str
    current_id: str
    parent_ids: tuple[str, ...]
    proof: ProofKind


@dataclass(frozen=True)
class ChangeCertificate:
    """Positive owner-free authorization for one visible current change."""

    event_id: str
    current_id: str
    parent_ids: tuple[str, ...]
    state: ChangeState
    proof: ProofKind
    change: ChangedUnit


@dataclass(frozen=True)
class StructuralEvent:
    """Non-visual structure evidence kept distinct from revision color."""

    event_id: str
    region_kind: RegionKind
    structural_path: tuple[str, ...]
    source_start: int
    source_end: int
    state: ChangeState
    proof: ProofKind


@dataclass(frozen=True)
class RevisionMatchAudit:
    """Deterministic aggregate decisions from region matching."""

    parent_blocks: int
    current_blocks: int
    unchanged_blocks: int
    changed_units: int
    structural_moves: int
    reordered_units: int
    equation_structural_events: int
    figure_asset_changes: int
    ambiguous_duplicate_groups: int
    total_revision_units: int
    unchanged_units: int
    added_units: int
    structural_only_units: int
    ambiguous_units: int
    identity_certificates: int
    change_certificates: int


@dataclass(frozen=True)
class RevisionMatchResult:
    """Owner-free current changes plus matching audit."""

    changes: tuple[ChangedUnit, ...]
    audit: RevisionMatchAudit
    decisions: tuple[UnitDecision, ...]
    identity_certificates: tuple[IdentityCertificate, ...]
    change_certificates: tuple[ChangeCertificate, ...]
    structural_events: tuple[StructuralEvent, ...]


_MATCHED_BLOCK_KINDS = frozenset(
    {
        RegionKind.DOCUMENT_TITLE,
        RegionKind.SECONDARY_TITLE,
        RegionKind.AUTHOR_ITEM,
        RegionKind.AFFILIATION_ITEM,
        RegionKind.AUTHOR_NOTE,
        RegionKind.FUNDING_FRONTMATTER,
        RegionKind.ABSTRACT,
        RegionKind.SECONDARY_ABSTRACT,
        RegionKind.KEYWORDS,
        RegionKind.HEADING_H1,
        RegionKind.HEADING_H2,
        RegionKind.HEADING_H3,
        RegionKind.HEADING_H4_PLUS,
        RegionKind.PROSE_PARAGRAPH,
        RegionKind.DISPLAY_EQUATION,
        RegionKind.FIGURE_CAPTION,
        RegionKind.TABLE_CAPTION,
        RegionKind.TABLE_ROW,
        RegionKind.TABLE_CELL,
        RegionKind.LIST_ITEM,
        RegionKind.FOOTNOTE,
        RegionKind.ACKNOWLEDGEMENTS,
        RegionKind.FUNDING_STATEMENT,
        RegionKind.AUTHOR_CONTRIBUTIONS,
        RegionKind.COMPETING_INTERESTS,
        RegionKind.DATA_AVAILABILITY,
        RegionKind.CODE_AVAILABILITY,
        RegionKind.SUPPLEMENTARY_STATEMENT,
        RegionKind.ENGLISH_SUMMARY_TITLE,
        RegionKind.ENGLISH_SUMMARY_PROSE,
    }
)

_PROSE_BLOCK_KINDS = frozenset(
    {
        RegionKind.ABSTRACT,
        RegionKind.SECONDARY_ABSTRACT,
        RegionKind.PROSE_PARAGRAPH,
        RegionKind.FIGURE_CAPTION,
        RegionKind.TABLE_CAPTION,
        RegionKind.LIST_ITEM,
        RegionKind.FOOTNOTE,
        RegionKind.ACKNOWLEDGEMENTS,
        RegionKind.FUNDING_STATEMENT,
        RegionKind.AUTHOR_CONTRIBUTIONS,
        RegionKind.COMPETING_INTERESTS,
        RegionKind.DATA_AVAILABILITY,
        RegionKind.CODE_AVAILABILITY,
        RegionKind.SUPPLEMENTARY_STATEMENT,
        RegionKind.ENGLISH_SUMMARY_PROSE,
    }
)

_CJK_LAYOUT_CHARACTER = (
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\uff0c\u3002\uff1b\uff1a\uff01\uff1f\u3001"
    r"\uff08\uff09\u3010\u3011\u300a\u300b"
)


def _group_blocks(
    projection: ManuscriptProjection,
) -> dict[tuple[RegionKind, tuple[str, ...]], list[StructuralBlock]]:
    groups: dict[tuple[RegionKind, tuple[str, ...]], list[StructuralBlock]] = (
        defaultdict(list)
    )
    for block in projection.blocks:
        if block.kind in _MATCHED_BLOCK_KINDS:
            groups[(block.kind, block.structural_path)].append(block)
    for blocks in groups.values():
        blocks.sort(key=lambda item: (item.ordinal, item.source_start))
    return groups


def _unique_positions(blocks: list[StructuralBlock]) -> dict[str, int]:
    positions: dict[str, list[int]] = defaultdict(list)
    for index, block in enumerate(blocks):
        positions[block.normalized_content].append(index)
    return {
        content: indices[0]
        for content, indices in positions.items()
        if len(indices) == 1
    }


def _unique_identities(blocks: list[StructuralBlock]) -> dict[str, int]:
    positions: dict[str, list[int]] = defaultdict(list)
    for index, block in enumerate(blocks):
        if block.identity is not None:
            positions[block.identity].append(index)
    return {
        identity: indices[0]
        for identity, indices in positions.items()
        if len(indices) == 1
    }


def _duplicate_is_resolved_by_identity(
    content: str,
    parent_blocks: list[StructuralBlock],
    current_blocks: list[StructuralBlock],
    parent_identities: dict[str, int],
    current_identities: dict[str, int],
) -> bool:
    current_matches = [
        block for block in current_blocks if block.normalized_content == content
    ]
    if not current_matches:
        return True
    return all(
        block.identity is not None
        and block.identity in current_identities
        and block.identity in parent_identities
        and parent_blocks[parent_identities[block.identity]].normalized_content
        == content
        for block in current_matches
    )


def _reordered_contents(
    parent: list[StructuralBlock], current: list[StructuralBlock]
) -> set[str]:
    parent_positions = _unique_positions(parent)
    current_positions = _unique_positions(current)
    common = [content for content in current_positions if content in parent_positions]
    reordered: set[str] = set()
    for index, left in enumerate(common):
        for right in common[index + 1 :]:
            parent_order = parent_positions[left] < parent_positions[right]
            current_order = current_positions[left] < current_positions[right]
            if parent_order != current_order:
                reordered.update((left, right))
    return reordered


def _unit_change_reasons(
    parent: StructuralBlock,
    current: StructuralBlock,
    parent_units: tuple[RevisionUnit, ...],
    current_units: tuple[RevisionUnit, ...],
    parent_text: str,
    current_text: str,
) -> dict[int, ChangeReason]:
    """Classify unmatched current units after identity anchors are established."""
    parent_positions: dict[str, list[int]] = defaultdict(list)
    current_positions: dict[str, list[int]] = defaultdict(list)
    for index, unit in enumerate(parent_units):
        parent_positions[_visual_unit_key(parent, unit, parent_text)].append(index)
    for index, unit in enumerate(current_units):
        current_positions[_visual_unit_key(current, unit, current_text)].append(index)

    identity_pairs: list[tuple[int, int]] = []
    for key in parent_positions.keys() & current_positions.keys():
        parent_indices = parent_positions[key]
        current_indices = current_positions[key]
        if len(parent_indices) != len(current_indices) and (
            len(parent_indices) > 1 or len(current_indices) > 1
        ):
            raise WorkflowError(
                "REVISION_MATCH_AMBIGUOUS\n"
                f"region: {current.kind.value}\n"
                f"structural path: {'/'.join(current.structural_path)}\n"
                "duplicate natural-unit identity has unequal multiplicity"
            )
        identity_pairs.extend(zip(parent_indices, current_indices, strict=False))
    identity_pairs.sort(key=lambda item: item[1])
    if any(left[0] >= right[0] for left, right in pairwise(identity_pairs)):
        if len(identity_pairs) != len(current_units) or len(identity_pairs) != len(
            parent_units
        ):
            raise WorkflowError(
                "REVISION_MATCH_AMBIGUOUS\n"
                f"region: {current.kind.value}\n"
                f"structural path: {'/'.join(current.structural_path)}\n"
                "reordered identity anchors leave unresolved changed units"
            )
        return {}

    reasons: dict[int, ChangeReason] = {}
    anchors = [(-1, -1), *identity_pairs, (len(parent_units), len(current_units))]
    for left, right in pairwise(anchors):
        parent_gap = range(left[0] + 1, right[0])
        current_gap = range(left[1] + 1, right[1])
        reason = (
            ChangeReason.CURRENT_ONLY if len(parent_gap) == 0 else ChangeReason.CONTENT
        )
        reasons.update((index, reason) for index in current_gap)
    return reasons


def _unit_changes(
    parent: StructuralBlock,
    current: StructuralBlock,
    parent_text: str,
    current_text: str,
) -> list[ChangedUnit]:
    if current.kind is RegionKind.TABLE_ROW:
        return []
    if not current.units:
        return [
            ChangedUnit(
                current.kind,
                current.structural_path,
                current.source_start,
                current.source_end,
                ChangeReason.CONTENT,
            )
        ]
    if current.kind in _PROSE_BLOCK_KINDS:
        parent_sentences = prose_sentence_units(
            parent_text, parent.source_start, parent.source_end
        )
        current_sentences = prose_sentence_units(
            current_text, current.source_start, current.source_end
        )
        sentence_reasons = _unit_change_reasons(
            parent,
            current,
            parent_sentences,
            current_sentences,
            parent_text,
            current_text,
        )
        parent_clause_counts = Counter(
            _visual_unit_key(parent, item, parent_text) for item in parent.units
        )
        current_clause_counts = Counter(
            _visual_unit_key(current, item, current_text) for item in current.units
        )
        if any(
            parent_clause_counts[key] != current_clause_counts[key]
            and max(parent_clause_counts[key], current_clause_counts[key]) > 1
            for key in parent_clause_counts.keys() & current_clause_counts.keys()
        ):
            raise WorkflowError(
                "REVISION_MATCH_AMBIGUOUS\n"
                f"region: {current.kind.value}\n"
                f"structural path: {'/'.join(current.structural_path)}\n"
                "duplicate long-clause identity has unequal multiplicity"
            )
        parent_clause_keys = set(parent_clause_counts)
        changed: list[ChangedUnit] = []
        for index, sentence in enumerate(current_sentences):
            reason = sentence_reasons.get(index)
            if reason is None:
                continue
            current_units = tuple(
                item
                for item in current.units
                if sentence.source_start <= item.source_start
                and item.source_end <= sentence.source_end
            )
            changed.extend(
                ChangedUnit(
                    current.kind,
                    current.structural_path,
                    item.source_start,
                    item.source_end,
                    reason,
                )
                for item in current_units
                if _visual_unit_key(current, item, current_text)
                not in parent_clause_keys
            )
        return changed
    reasons = _unit_change_reasons(
        parent,
        current,
        parent.units,
        current.units,
        parent_text,
        current_text,
    )
    return [
        ChangedUnit(
            current.kind,
            current.structural_path,
            unit.source_start,
            unit.source_end,
            reasons[index],
        )
        for index, unit in enumerate(current.units)
        if index in reasons
    ]


def _visual_unit_key(
    block: StructuralBlock,
    unit: RevisionUnit,
    text: str,
) -> str:
    protected_kinds = {
        RegionKind.CITATION,
        RegionKind.CROSS_REFERENCE,
        RegionKind.URL_DOI,
    }
    protected = [
        span
        for span in block.protected_spans
        if span.kind in protected_kinds
        and unit.source_start <= span.source_start
        and span.source_end <= unit.source_end
    ]
    if not protected:
        return unit.normalized_content
    pieces: list[str] = []
    cursor = unit.source_start
    for span in protected:
        pieces.extend((text[cursor : span.source_start], "<protected-link>"))
        cursor = span.source_end
    pieces.append(text[cursor : unit.source_end])
    normalized = normalize_region_content("".join(pieces))
    normalized = re.sub(r"\s*(<protected-link>)\s*", r"\1", normalized)
    return re.sub(
        rf"(?<=[{_CJK_LAYOUT_CHARACTER}])\s+(?=[{_CJK_LAYOUT_CHARACTER}])",
        "",
        normalized,
    )


def _whole_or_units(block: StructuralBlock, reason: ChangeReason) -> list[ChangedUnit]:
    if reason in {ChangeReason.STRUCTURAL_MOVE, ChangeReason.REORDERED}:
        units: tuple[RevisionUnit, ...] = ()
    else:
        units = block.units
    if not units:
        return [
            ChangedUnit(
                block.kind,
                block.structural_path,
                block.source_start,
                block.source_end,
                reason,
            )
        ]
    return [
        ChangedUnit(
            block.kind,
            block.structural_path,
            unit.source_start,
            unit.source_end,
            reason,
        )
        for unit in units
    ]


def _same_kind_elsewhere(
    parent: ManuscriptProjection, current: StructuralBlock
) -> bool:
    return any(
        block.kind is current.kind
        and block.structural_path != current.structural_path
        and block.normalized_content == current.normalized_content
        for block in parent.blocks
    )


def _asset_replacement_count(
    parent: ManuscriptProjection,
    current: ManuscriptProjection,
) -> int:
    parent_figures = {
        (block.structural_path, block.identity): block
        for block in parent.blocks
        if block.kind is RegionKind.FIGURE
    }
    changes = 0
    for figure in current.blocks:
        if figure.kind is not RegionKind.FIGURE:
            continue
        parent_figure = parent_figures.get((figure.structural_path, figure.identity))
        if (
            parent_figure is None
            or figure.asset_identity is None
            or parent_figure.asset_identity == figure.asset_identity
        ):
            continue
        changes += 1
    return changes


def _duplicate_contents(blocks: list[StructuralBlock]) -> set[str]:
    positions: dict[str, int] = defaultdict(int)
    for block in blocks:
        positions[block.normalized_content] += 1
    return {content for content, count in positions.items() if count > 1}


def _unit_id(
    side: str,
    block: StructuralBlock,
    block_number: int,
    unit_number: int,
) -> str:
    return f"{side}:{block.kind.value}:b{block_number:04d}:u{unit_number:03d}"


def _truth_units(
    block: StructuralBlock,
    text: str,
    changed_ranges: set[tuple[int, int]],
) -> tuple[RevisionUnit, ...]:
    if block.kind not in _PROSE_BLOCK_KINDS:
        if block.units:
            return block.units
        return (
            RevisionUnit(
                block.kind,
                block.source_start,
                block.source_end,
                block.normalized_content,
            ),
        )
    result: list[RevisionUnit] = []
    for sentence in prose_sentence_units(text, block.source_start, block.source_end):
        sentence_parts = tuple(
            unit
            for unit in block.units
            if sentence.source_start <= unit.source_start
            and unit.source_end <= sentence.source_end
        )
        if (
            any(
                start < sentence.source_end and sentence.source_start < end
                for start, end in changed_ranges
            )
            and len(sentence_parts) > 1
        ):
            result.extend(sentence_parts)
        else:
            result.append(sentence)
    return tuple(result)


def _candidate_units(
    block: StructuralBlock,
    text: str,
    current_kind: RegionKind,
) -> tuple[RevisionUnit, ...]:
    if block.kind in _PROSE_BLOCK_KINDS and current_kind is RegionKind.SENTENCE:
        return prose_sentence_units(text, block.source_start, block.source_end)
    if block.units:
        return block.units
    return (
        RevisionUnit(
            block.kind,
            block.source_start,
            block.source_end,
            block.normalized_content,
        ),
    )


def _truth_records(
    parent: ManuscriptProjection,
    current: ManuscriptProjection,
    parent_groups: dict[tuple[RegionKind, tuple[str, ...]], list[StructuralBlock]],
    changes: tuple[ChangedUnit, ...],
    structural_events: tuple[StructuralEvent, ...],
) -> tuple[
    tuple[UnitDecision, ...],
    tuple[IdentityCertificate, ...],
    tuple[ChangeCertificate, ...],
]:
    changed_by_range = {(item.source_start, item.source_end): item for item in changes}
    changed_ranges = set(changed_by_range)
    parent_numbers = {
        id(block): number for number, block in enumerate(parent.blocks, 1)
    }
    current_numbers = {
        id(block): number for number, block in enumerate(current.blocks, 1)
    }
    decisions: list[UnitDecision] = []
    identities: list[IdentityCertificate] = []
    pending_changes: list[tuple[UnitDecision, ChangedUnit]] = []
    for current_block in current.blocks:
        if current_block.kind not in _MATCHED_BLOCK_KINDS:
            continue
        group_key = (current_block.kind, current_block.structural_path)
        parent_blocks = parent_groups.get(group_key, [])
        for unit_number, unit in enumerate(
            _truth_units(current_block, current.text, changed_ranges), 1
        ):
            current_id = _unit_id(
                "current",
                current_block,
                current_numbers[id(current_block)],
                unit_number,
            )
            unit_key = _visual_unit_key(current_block, unit, current.text)
            exact_parent_ids: list[str] = []
            normalized_parent_ids: list[str] = []
            logical_parent_ids: list[str] = []
            for parent_block in parent_blocks:
                parent_units = _candidate_units(parent_block, parent.text, unit.kind)
                for parent_unit_number, parent_unit in enumerate(parent_units, 1):
                    parent_id = _unit_id(
                        "parent",
                        parent_block,
                        parent_numbers[id(parent_block)],
                        parent_unit_number,
                    )
                    if parent_block.ordinal == current_block.ordinal:
                        logical_parent_ids.append(parent_id)
                    if (
                        parent.text[parent_unit.source_start : parent_unit.source_end]
                        == current.text[unit.source_start : unit.source_end]
                    ):
                        exact_parent_ids.append(parent_id)
                    if (
                        _visual_unit_key(parent_block, parent_unit, parent.text)
                        == unit_key
                    ):
                        normalized_parent_ids.append(parent_id)
            change = changed_by_range.get((unit.source_start, unit.source_end))
            structural = next(
                (
                    event
                    for event in structural_events
                    if event.source_start <= unit.source_start
                    and unit.source_end <= event.source_end
                ),
                None,
            )
            if change is not None:
                state = (
                    ChangeState.ADDED
                    if change.reason is ChangeReason.CURRENT_ONLY
                    else ChangeState.CHANGED
                )
                proof = (
                    ProofKind.DETERMINISTIC_ADDITION
                    if state is ChangeState.ADDED
                    else ProofKind.ESTABLISHED_CORRESPONDENCE_DIFFERENCE
                )
                candidates = (
                    ()
                    if state is ChangeState.ADDED
                    else tuple(dict.fromkeys(logical_parent_ids))
                )
                visual_authorized = True
            elif structural is not None:
                state = structural.state
                proof = ProofKind.STRUCTURAL_EVENT
                candidates = tuple(dict.fromkeys(exact_parent_ids))
                if not candidates:
                    candidates = tuple(dict.fromkeys(normalized_parent_ids))
                if not candidates:
                    global_parent_ids: list[str] = []
                    for parent_block in parent.blocks:
                        if parent_block.kind is not current_block.kind:
                            continue
                        for parent_unit_number, parent_unit in enumerate(
                            _candidate_units(parent_block, parent.text, unit.kind), 1
                        ):
                            if (
                                _visual_unit_key(parent_block, parent_unit, parent.text)
                                != unit_key
                            ):
                                continue
                            global_parent_ids.append(
                                _unit_id(
                                    "parent",
                                    parent_block,
                                    parent_numbers[id(parent_block)],
                                    parent_unit_number,
                                )
                            )
                    candidates = tuple(dict.fromkeys(global_parent_ids))
                if len(candidates) != 1:
                    raise WorkflowError(
                        "REVISION_MATCH_AMBIGUOUS\n"
                        f"region: {current_block.kind.value}\n"
                        f"structural path: {'/'.join(current_block.structural_path)}\n"
                        "structural event lacks one unique identity counterpart"
                    )
                visual_authorized = False
            else:
                state = ChangeState.UNCHANGED
                if exact_parent_ids:
                    proof = ProofKind.EXACT_IDENTITY
                    candidates = tuple(dict.fromkeys(exact_parent_ids))
                else:
                    proof = ProofKind.NORMALIZED_IDENTITY
                    candidates = tuple(dict.fromkeys(normalized_parent_ids))
                visual_authorized = False
            decision = UnitDecision(
                current_id=current_id,
                region_kind=current_block.kind,
                structural_path=current_block.structural_path,
                source_start=unit.source_start,
                source_end=unit.source_end,
                normalized_hash=hashlib.sha256(unit_key.encode("utf-8")).hexdigest(),
                candidate_parent_ids=candidates,
                state=state,
                proof=proof,
                visual_authorized=visual_authorized,
            )
            decisions.append(decision)
            if visual_authorized:
                assert change is not None
                pending_changes.append((decision, change))
            else:
                identities.append(
                    IdentityCertificate(
                        certificate_id=f"sci:id:i{len(identities) + 1:04d}",
                        current_id=current_id,
                        parent_ids=candidates,
                        proof=proof,
                    )
                )
    certificates = tuple(
        ChangeCertificate(
            event_id=f"sci:rev:e{number:04d}",
            current_id=decision.current_id,
            parent_ids=decision.candidate_parent_ids,
            state=decision.state,
            proof=decision.proof,
            change=change,
        )
        for number, (decision, change) in enumerate(pending_changes, 1)
    )
    return tuple(decisions), tuple(identities), certificates


def match_revisions(
    parent: ManuscriptProjection,
    current: ManuscriptProjection,
) -> RevisionMatchResult:
    """Select current revision units using same-context structural matching."""
    parent_groups = _group_blocks(parent)
    current_groups = _group_blocks(current)
    parent_equations = {
        block.normalized_content
        for block in parent.blocks
        if block.kind is RegionKind.DISPLAY_EQUATION
    }
    changes: list[ChangedUnit] = []
    structural_events: list[StructuralEvent] = []
    unchanged_blocks = 0
    equation_structural_events = 0
    ambiguous_duplicate_groups = 0
    for group_key, current_blocks in current_groups.items():
        parent_blocks = parent_groups.get(group_key, [])
        duplicate_contents = _duplicate_contents(parent_blocks) | _duplicate_contents(
            current_blocks
        )
        parent_identities = _unique_identities(parent_blocks)
        current_identities = _unique_identities(current_blocks)

        unresolved_duplicates = {
            content
            for content in duplicate_contents
            if not _duplicate_is_resolved_by_identity(
                content,
                parent_blocks,
                current_blocks,
                parent_identities,
                current_identities,
            )
            if [
                index
                for index, block in enumerate(parent_blocks)
                if block.normalized_content == content
            ]
            != [
                index
                for index, block in enumerate(current_blocks)
                if block.normalized_content == content
            ]
        }
        if unresolved_duplicates:
            ambiguous_duplicate_groups += 1
            raise WorkflowError(
                "REVISION_MATCH_AMBIGUOUS\n"
                f"region: {group_key[0].value}\n"
                f"structural path: {'/'.join(group_key[1])}\n"
                "duplicate candidates remain unresolved after ancestry and order"
            )
        parent_unique = _unique_positions(parent_blocks)
        current_unique = _unique_positions(current_blocks)
        reordered = _reordered_contents(parent_blocks, current_blocks)
        exact_pairs = {
            current_identities[identity]: parent_identities[identity]
            for identity in current_identities.keys() & parent_identities.keys()
            if current_blocks[current_identities[identity]].normalized_content
            == parent_blocks[parent_identities[identity]].normalized_content
        }
        exact_pairs.update(
            {
                current_unique[content]: parent_unique[content]
                for content in current_unique
                if content in parent_unique and content not in reordered
            }
        )
        paired_parent_indices = set(exact_pairs.values())
        for current_index, current_block in enumerate(current_blocks):
            content = current_block.normalized_content
            if current_index in exact_pairs:
                parent_index = exact_pairs[current_index]
                if (
                    current_block.kind is RegionKind.TABLE_ROW
                    and duplicate_contents
                    and parent_index != current_index
                ):
                    changes.extend(
                        _whole_or_units(current_block, ChangeReason.REORDERED)
                    )
                else:
                    unchanged_blocks += 1
                continue
            if (
                current_block.kind is RegionKind.DISPLAY_EQUATION
                and content in parent_equations
            ):
                unchanged_blocks += 1
                equation_structural_events += 1
                structural_events.append(
                    StructuralEvent(
                        event_id=f"sci:struct:e{len(structural_events) + 1:04d}",
                        region_kind=current_block.kind,
                        structural_path=current_block.structural_path,
                        source_start=current_block.source_start,
                        source_end=current_block.source_end,
                        state=ChangeState.MOVED_COMPATIBLE,
                        proof=ProofKind.STRUCTURAL_EVENT,
                    )
                )
                continue
            if content in duplicate_contents:
                same_ordinal = (
                    current_index < len(parent_blocks)
                    and parent_blocks[current_index].normalized_content == content
                )
                if same_ordinal:
                    paired_parent_indices.add(current_index)
                    unchanged_blocks += 1
                    continue
                changes.extend(_whole_or_units(current_block, ChangeReason.REORDERED))
                continue
            if content in reordered:
                unchanged_blocks += 1
                structural_events.append(
                    StructuralEvent(
                        event_id=f"sci:struct:e{len(structural_events) + 1:04d}",
                        region_kind=current_block.kind,
                        structural_path=current_block.structural_path,
                        source_start=current_block.source_start,
                        source_end=current_block.source_end,
                        state=ChangeState.MOVED_COMPATIBLE,
                        proof=ProofKind.STRUCTURAL_EVENT,
                    )
                )
                continue
            if current_block.kind in {
                RegionKind.HEADING_H1,
                RegionKind.HEADING_H2,
                RegionKind.HEADING_H3,
                RegionKind.HEADING_H4_PLUS,
                RegionKind.PROSE_PARAGRAPH,
            } and _same_kind_elsewhere(parent, current_block):
                unchanged_blocks += 1
                structural_events.append(
                    StructuralEvent(
                        event_id=f"sci:struct:e{len(structural_events) + 1:04d}",
                        region_kind=current_block.kind,
                        structural_path=current_block.structural_path,
                        source_start=current_block.source_start,
                        source_end=current_block.source_end,
                        state=ChangeState.STRUCTURAL_CHANGED,
                        proof=ProofKind.STRUCTURAL_EVENT,
                    )
                )
                continue
            candidates = [
                (index, block)
                for index, block in enumerate(parent_blocks)
                if index not in paired_parent_indices
            ]
            if not candidates:
                changes.extend(
                    _whole_or_units(current_block, ChangeReason.CURRENT_ONLY)
                )
                continue
            identity_candidate = next(
                (
                    item
                    for item in candidates
                    if current_block.identity is not None
                    and item[1].identity == current_block.identity
                ),
                None,
            )
            parent_index, parent_block = identity_candidate or min(
                candidates,
                key=lambda item: (
                    abs(item[1].ordinal - current_block.ordinal),
                    abs(item[0] - current_index),
                ),
            )
            paired_parent_indices.add(parent_index)
            changes.extend(
                _unit_changes(
                    parent_block,
                    current_block,
                    parent.text,
                    current.text,
                )
            )
    figure_asset_changes = _asset_replacement_count(parent, current)
    parent_figures = {
        (block.structural_path, block.identity): block
        for block in parent.blocks
        if block.kind is RegionKind.FIGURE
    }
    for figure in current.blocks:
        if figure.kind is not RegionKind.FIGURE:
            continue
        parent_figure = parent_figures.get((figure.structural_path, figure.identity))
        if (
            parent_figure is None
            or figure.asset_identity is None
            or parent_figure.asset_identity == figure.asset_identity
        ):
            continue
        structural_events.append(
            StructuralEvent(
                event_id=f"sci:struct:e{len(structural_events) + 1:04d}",
                region_kind=figure.kind,
                structural_path=figure.structural_path,
                source_start=figure.source_start,
                source_end=figure.source_end,
                state=ChangeState.STRUCTURAL_CHANGED,
                proof=ProofKind.STRUCTURAL_EVENT,
            )
        )
    row_ranges = [
        (item.source_start, item.source_end)
        for item in changes
        if item.region_kind is RegionKind.TABLE_ROW
    ]
    structural_row_ranges = [
        (item.source_start, item.source_end)
        for item in structural_events
        if item.region_kind is RegionKind.TABLE_ROW
    ]
    changes = [
        item
        for item in changes
        if item.region_kind is not RegionKind.TABLE_CELL
        or not any(
            start <= item.source_start and item.source_end <= end
            for start, end in (*row_ranges, *structural_row_ranges)
        )
    ]
    ordered = tuple(
        sorted(changes, key=lambda item: (item.source_start, item.source_end))
    )
    ordered_structural = tuple(
        sorted(
            structural_events,
            key=lambda item: (item.source_start, item.source_end, item.event_id),
        )
    )
    decisions, identities, certificates = _truth_records(
        parent,
        current,
        parent_groups,
        ordered,
        ordered_structural,
    )
    audit = RevisionMatchAudit(
        parent_blocks=sum(len(items) for items in parent_groups.values()),
        current_blocks=sum(len(items) for items in current_groups.values()),
        unchanged_blocks=unchanged_blocks,
        changed_units=len(ordered),
        structural_moves=sum(
            item.reason is ChangeReason.STRUCTURAL_MOVE for item in ordered
        ),
        reordered_units=sum(item.reason is ChangeReason.REORDERED for item in ordered),
        equation_structural_events=equation_structural_events,
        figure_asset_changes=figure_asset_changes,
        ambiguous_duplicate_groups=ambiguous_duplicate_groups,
        total_revision_units=len(decisions),
        unchanged_units=sum(item.state is ChangeState.UNCHANGED for item in decisions),
        added_units=sum(item.state is ChangeState.ADDED for item in decisions),
        structural_only_units=sum(
            item.state in {ChangeState.MOVED_COMPATIBLE, ChangeState.STRUCTURAL_CHANGED}
            for item in decisions
        ),
        ambiguous_units=sum(item.state is ChangeState.AMBIGUOUS for item in decisions),
        identity_certificates=len(identities),
        change_certificates=len(certificates),
    )
    return RevisionMatchResult(
        ordered,
        audit,
        decisions,
        identities,
        certificates,
        ordered_structural,
    )
