"""Build a current-only highlighted revision from latexdiff additions."""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path

from .compile import (
    SciStateEvent,
    compile_tex,
    materialize_bibliography,
    parse_sci_state,
    publish_file_atomically,
    run_command,
    stage_runtime_resources,
)
from .errors import WorkflowError
from .locations import build_review_locations, instrument_location_source
from .provenance import (
    ProvenanceSource,
    extract_provenance,
    split_by_review_provenance,
)
from .regions import RegionKind, StructuralBlock, project_manuscript
from .review import parse_response_source, review_ids_from_sources
from .revision_match import (
    ChangeState,
    RevisionMatchAudit,
    RevisionMatchResult,
    match_revisions,
)
from .revision_render import (
    CitationProvenance,
    HighlightSpan,
    added_citation_provenance,
    apply_highlights,
    citation_spans,
    display_evidence_is_covered,
    preserve_topology_seams,
    protected_citation_spans,
    replace_special_spans,
    validate_topology_identity,
)
from .revision_render import strip_highlight_markup as _strip_highlight_markup
from .templates import resources_root
from .tex import (
    command_at,
    extract_braced,
    is_commented,
    is_escaped,
    scan_tex_commands,
    skip_tex_space,
)
from .timing import BuildTelemetry
from .workspace import (
    ProjectConfig,
    migrate_revision_style_file,
    strip_provenance_wrappers,
)

STYLE_BEGIN = "% SCI_DIFF_STYLE_BEGIN"
STYLE_END = "% SCI_DIFF_STYLE_END"
DETECTOR_STYLE_BEGIN = "% SCI_DETECTOR_STYLE_BEGIN"
DETECTOR_STYLE_END = "% SCI_DETECTOR_STYLE_END"
CHINESE_TEXT_COMMANDS = (
    "cnabstract",
    "cnkeywords",
    "enabstract",
    "enkeywords",
    "firstauthorcn",
    "firstauthoren",
    "funding",
    "entitle",
    "keywords",
)
CHINESE_SINGLE_VALUE_COMMANDS = tuple(
    dict.fromkeys((*CHINESE_TEXT_COMMANDS, "title", "enkeywords"))
)
CHINESE_SINGLE_VALUE_ENVIRONMENTS = ("abstract", "englishabstract")
PUBLISHER_METADATA_CONTEXT_COMMANDS = (
    "author",
    "enauthor",
    "affiliation",
    "enaffiliation",
    "firstauthorcn",
    "firstauthoren",
    "corrauthorcn",
    "corrauthoren",
    "funding",
    "cortext",
    "address",
    "email",
    "affil",
    "alsoaffiliation",
)

_REVISION_RUNTIME_TEMPLATE = (
    resources_root() / "revision" / "marked_runtime.tex"
).read_text(encoding="utf-8")
_COMMON_PREAMBLE = resources_root() / "manuscript_preamble" / "common.tex"
REVISION_RUNTIME = _REVISION_RUNTIME_TEMPLATE.replace("%%CJK_REVISION_PACKAGE%%", "")


def _revision_runtime(language: str) -> str:
    """Return the packaged marked-style runtime for one manuscript language."""
    del language
    return _REVISION_RUNTIME_TEMPLATE.replace("%%CJK_REVISION_PACKAGE%%", "")


def _validate_reference_style_contract() -> None:
    """Require one shared native xcolor blue contract for clean and marked output."""
    common = _COMMON_PREAMBLE.read_text(encoding="utf-8")
    required = (
        r"\newcommand{\RevisionReviewerColor}{RubineRed}",
        "citecolor=blue",
        "linkcolor=blue",
        "urlcolor=blue",
    )
    forbidden = (
        "definecolor{SciRevision",
        "SciLinkBlue",
        "ProcessBlue",
        "0,0,255",
        "0000FF",
        "citecolor=black",
        "linkcolor=black",
        "urlcolor=black",
    )
    if (
        any(token not in common for token in required)
        or "ForestGreen" not in REVISION_RUNTIME
        or r"\SCISetCitationColor{blue}\color{blue}#1" not in REVISION_RUNTIME
        or any(token in common + REVISION_RUNTIME for token in forbidden)
    ):
        raise WorkflowError("CLEAN_MARKED_REFERENCE_STYLE_MISMATCH")


@dataclass(frozen=True)
class MarkedResult:
    """Published marked PDF and in-memory reviewer locations."""

    pdf: Path
    locations: dict[str, str]
    bibliography_notices: tuple["BibliographyNotice", ...] = ()
    aux_path: Path | None = None
    audit_path: Path | None = None


@dataclass(frozen=True)
class BibliographyNotice:
    """One neutral machine-level ReviewReference result."""

    code: str
    review_id: str
    citation_key: str
    message: str
    path: Path


@dataclass(frozen=True)
class LatexdiffAddition:
    """One current-source addition reported by ``latexdiff``."""

    content: str
    macro: str


@dataclass(frozen=True)
class _BibliographyEntry:
    key: str
    command: str
    content: str


@dataclass(frozen=True)
class _BibliographyDocument:
    header: str
    entries: tuple[_BibliographyEntry, ...]
    footer: str


def _containing_display(
    blocks: tuple[StructuralBlock, ...], start: int, end: int
) -> StructuralBlock:
    displays = [
        block
        for block in blocks
        if block.kind is RegionKind.DISPLAY_EQUATION
        and block.source_start <= start
        and end <= block.source_end
    ]
    if len(displays) != 1:
        raise WorkflowError(
            "REGION_CLASSIFICATION_AMBIGUOUS\n"
            "region context: display equation render interval\n"
            f"nearby TeX: current offsets {start}:{end}"
        )
    return displays[0]


def structure_highlight_spans(
    parent: str,
    provenance: ProvenanceSource,
    *,
    evidence: list[HighlightSpan] | None = None,
    parent_asset_root: Path | None = None,
    current_asset_root: Path | None = None,
    truth_path: Path | None = None,
) -> tuple[list[HighlightSpan], RevisionMatchAudit]:
    """Select natural current units first, then split them by provenance."""
    projection_started = time.perf_counter()
    parent_projection = project_manuscript(
        parent,
        asset_root=parent_asset_root,
        source_name="parent flattened manuscript",
    )
    current_projection = project_manuscript(
        provenance.text,
        asset_root=current_asset_root,
        source_name="current flattened manuscript",
    )
    projection_seconds = time.perf_counter() - projection_started
    matching_started = time.perf_counter()
    matched = match_revisions(parent_projection, current_projection)
    matching_seconds = time.perf_counter() - matching_started
    detector_disagreements = tuple(
        decision.current_id
        for decision in matched.decisions
        if decision.state is ChangeState.UNCHANGED
        and any(
            item.start < decision.source_end and decision.source_start < item.end
            for item in evidence or ()
        )
    )
    certificate_started = time.perf_counter()
    spans: list[HighlightSpan] = []
    rendered_displays: set[tuple[int, int]] = set()
    event_number = 0

    def authorized(
        start: int,
        end: int,
        owner: tuple[str, ...] | None,
        kind: str = "text",
    ) -> HighlightSpan:
        nonlocal event_number
        event_number += 1
        return HighlightSpan(
            start,
            end,
            owner,
            kind,
            f"sci:rev:e{event_number:04d}",
        )

    for certificate in matched.change_certificates:
        change = certificate.change
        if change.region_kind is RegionKind.DISPLAY_EQUATION:
            display = _containing_display(
                current_projection.blocks, change.source_start, change.source_end
            )
            if display.container_start is None or display.container_end is None:
                raise WorkflowError("Display equation has no render container.")
            interval = (display.container_start, display.container_end)
            if interval in rendered_displays:
                continue
            owners = {
                item.review_ids
                for item in provenance.review_spans
                if item.start < change.source_end and change.source_start < item.end
            }
            if len(owners) > 1:
                raise WorkflowError(
                    "AMBIGUOUS_DISPLAY_PROVENANCE: changed display equation spans "
                    "multiple reviewer owners."
                )
            owner = next(iter(owners)) if owners else None
            spans.append(authorized(*interval, owner, "display"))
            rendered_displays.add(interval)
            continue
        spans.extend(
            authorized(left, right, owner)
            for left, right, owner in split_by_review_provenance(
                provenance, change.source_start, change.source_end
            )
        )
    audit = replace(
        matched.audit,
        changed_units=event_number,
        change_certificates=event_number,
    )
    ordered_spans = sorted(spans, key=lambda item: (item.start, item.end))
    _validate_truth_spans(ordered_spans, matched)
    certificate_seconds = time.perf_counter() - certificate_started
    if truth_path is not None:
        _write_revision_truth(
            truth_path,
            matched,
            ordered_spans,
            projection_seconds=projection_seconds,
            matching_seconds=matching_seconds,
            certificate_seconds=certificate_seconds,
            detector_disagreements=detector_disagreements,
        )
    return ordered_spans, audit


def _validate_truth_spans(
    spans: list[HighlightSpan], matched: RevisionMatchResult
) -> None:
    visual = [item for item in matched.decisions if item.visual_authorized]
    unchanged = [
        item for item in matched.decisions if item.state is ChangeState.UNCHANGED
    ]
    for span in spans:
        if span.kind == "citation":
            continue
        if not any(
            (decision.source_start <= span.start and span.end <= decision.source_end)
            or (
                span.kind == "display"
                and span.start <= decision.source_start
                and decision.source_end <= span.end
            )
            for decision in visual
        ):
            raise WorkflowError(
                "REVISION_RENDER_UNAUTHORIZED: highlight has no ChangeCertificate."
            )
        if any(
            span.start < decision.source_end and decision.source_start < span.end
            for decision in unchanged
        ):
            raise WorkflowError("REVISION_HIGHLIGHT_CROSSES_UNCHANGED_UNIT")
    for decision in visual:
        if not any(
            span.kind != "citation"
            and (
                (
                    decision.source_start <= span.start
                    and span.end <= decision.source_end
                )
                or (
                    span.kind == "display"
                    and span.start <= decision.source_start
                    and decision.source_end <= span.end
                )
            )
            for span in spans
        ):
            raise WorkflowError(
                "REVISION_RENDER_CERTIFICATE_MISMATCH: missing authorized highlight."
            )


def _write_revision_truth(
    path: Path,
    matched: RevisionMatchResult,
    spans: list[HighlightSpan],
    *,
    projection_seconds: float,
    matching_seconds: float,
    certificate_seconds: float,
    detector_disagreements: tuple[str, ...],
) -> None:
    """Persist compact proof records without copying scientific prose."""
    authorized_highlights: list[dict[str, object]] = []
    for span in spans:
        if span.kind == "citation":
            continue
        decision = next(
            (
                item
                for item in matched.decisions
                if item.visual_authorized
                and (
                    (item.source_start <= span.start and span.end <= item.source_end)
                    or (
                        span.kind == "display"
                        and span.start <= item.source_start
                        and item.source_end <= span.end
                    )
                )
            ),
            None,
        )
        if decision is None or span.event_id is None:
            raise WorkflowError(
                "REVISION_RENDER_UNAUTHORIZED: truth manifest has no proof owner."
            )
        authorized_highlights.append(
            {
                "event_id": span.event_id,
                "current_id": decision.current_id,
                "source_start": span.start,
                "source_end": span.end,
                "owner": "author" if span.review_ids is None else "reviewer",
                "review_ids": list(span.review_ids or ()),
            }
        )
    payload = {
        "schema": 1,
        "units": [
            {
                "current_id": item.current_id,
                "type": item.region_kind.value,
                "structural_path": list(item.structural_path),
                "source_start": item.source_start,
                "source_end": item.source_end,
                "normalized_hash": item.normalized_hash,
                "candidate_parent_ids": list(item.candidate_parent_ids),
                "final_state": item.state.value,
                "proof": item.proof.value,
                "visual_authorized": item.visual_authorized,
            }
            for item in matched.decisions
        ],
        "structural_events": [
            {
                "event_id": item.event_id,
                "type": item.region_kind.value,
                "structural_path": list(item.structural_path),
                "source_start": item.source_start,
                "source_end": item.source_end,
                "state": item.state.value,
                "proof": item.proof.value,
            }
            for item in matched.structural_events
        ],
        "detector_disagreements": list(detector_disagreements),
        "authorized_highlights": authorized_highlights,
        "summary": {
            "total_revision_units": matched.audit.total_revision_units,
            "unchanged_units": matched.audit.unchanged_units,
            "changed_units": sum(
                item.state is ChangeState.CHANGED for item in matched.decisions
            ),
            "added_units": matched.audit.added_units,
            "structural_only_units": len(matched.structural_events),
            "ambiguous_units": matched.audit.ambiguous_units,
            "identity_certificates": len(matched.identity_certificates),
            "unit_change_proofs": len(matched.change_certificates),
            "change_certificates": len(authorized_highlights),
            "visual_revision_events": len(authorized_highlights),
            "detector_disagreements": len(detector_disagreements),
        },
        "performance_seconds": {
            "source_projection": projection_seconds,
            "identity_and_matching": matching_seconds,
            "certificate_generation": certificate_seconds,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _complete_revision_truth(
    path: Path,
    render_events: tuple[SciStateEvent, ...],
    sidecar_seconds: float,
) -> None:
    """Attach the validated TeX registry to one compact truth manifest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["render_certificates"] = [
        {
            "event_id": event.fields[0],
            "owner": event.fields[1],
            "review_ids": event.fields[2].split(",") if len(event.fields) == 3 else [],
        }
        for event in sorted(render_events, key=lambda item: item.fields[0])
    ]
    summary = payload["summary"]
    summary.update(
        {
            "render_certificates": len(render_events),
            "false_positive_units": 0,
            "false_negative_units": 0,
            "unexpected_render_events": 0,
            "missing_render_events": 0,
            "duplicate_render_events": 0,
            "owner_conflicts": 0,
        }
    )
    payload["performance_seconds"]["tex_sidecar_validation"] = sidecar_seconds
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def revision_render_registry(
    spans: list[HighlightSpan],
) -> tuple[SciStateEvent, ...]:
    """Return the exact expected TeX render events for authorized highlights."""
    events: list[SciStateEvent] = []
    seen: dict[str, tuple[str, ...]] = {}
    for span in spans:
        if span.kind == "citation":
            continue
        if span.event_id is None:
            raise WorkflowError("REVISION_RENDER_UNAUTHORIZED: missing event ID.")
        fields = (
            (span.event_id, "author")
            if span.review_ids is None
            else (span.event_id, "reviewer", ",".join(span.review_ids))
        )
        previous = seen.get(span.event_id)
        if previous is not None:
            if previous != fields:
                raise WorkflowError(
                    "REVISION_RENDER_OWNER_CONFLICT: one event ID has multiple owners."
                )
            continue
        seen[span.event_id] = fields
        events.append(SciStateEvent("REVISION", fields))
    return tuple(events)


def _validate_revision_render_registry(
    expected: tuple[SciStateEvent, ...],
    actual: tuple[SciStateEvent, ...],
) -> None:
    """Require one TeX render certificate per authorized event.

    TeX may execute stored frontmatter after body-source macros, so execution
    order is not source order.  Event identity and ownership remain exact.
    """
    schema = SciStateEvent("MARKED_SCHEMA", ("1",))
    if not actual or actual[0] != schema:
        raise WorkflowError(
            "REVISION_RENDER_CERTIFICATE_MISMATCH: marked schema is missing."
        )
    rendered = actual[1:]
    rendered_by_id: dict[str, SciStateEvent] = {}
    for event in rendered:
        event_id = event.fields[0]
        if event_id in rendered_by_id:
            raise WorkflowError(
                "REVISION_RENDER_CERTIFICATE_MISMATCH: duplicate render event ID."
            )
        rendered_by_id[event_id] = event
    expected_by_id = {event.fields[0]: event for event in expected}
    if len(expected_by_id) != len(expected) or rendered_by_id != expected_by_id:
        raise WorkflowError(
            "REVISION_RENDER_CERTIFICATE_MISMATCH: marked SCI registry differs "
            "from expected ChangeCertificates."
        )


def prepare_change_detection_sources(
    parent: str,
    current: str,
) -> tuple[str, ProvenanceSource]:
    """Return provenance-free inputs and current ownership intervals.

    The current source is the only possible final-layout authority. Parent-only
    structure is supplied solely to ``latexdiff`` as change evidence.
    """
    return strip_provenance_wrappers(parent), extract_provenance(current)


def _mask_overridden_frontmatter_fields(
    text: str,
    publisher: str,
) -> tuple[str, int]:
    """Mask inactive last-definition-wins fields without changing offsets.

    The Chinese publisher template stores each frontmatter field in one macro,
    so a later declaration replaces every earlier declaration. Latexdiff must
    compare the declarations that the clean PDF actually renders. Masking keeps
    source length and newline offsets exact, allowing detector spans to map
    directly back to the untouched current source.
    """
    if publisher != "chinese":
        return text, 0

    occurrences: dict[str, list[tuple[int, int]]] = {}
    try:
        for command in scan_tex_commands(
            text,
            CHINESE_SINGLE_VALUE_COMMANDS,
            field_count=1,
        ):
            occurrences.setdefault(f"command:{command.name}", []).append(
                (command.start, command.end)
            )
    except ValueError as exc:
        raise WorkflowError("Malformed single-value frontmatter command.") from exc

    environment_pattern = re.compile(
        r"\\(?P<edge>begin|end)\{(?P<name>"
        + "|".join(map(re.escape, CHINESE_SINGLE_VALUE_ENVIRONMENTS))
        + r")\}"
    )
    open_environments: dict[str, list[int]] = {
        name: [] for name in CHINESE_SINGLE_VALUE_ENVIRONMENTS
    }
    for match in environment_pattern.finditer(text):
        if is_commented(text, match.start()):
            continue
        name = match.group("name")
        if match.group("edge") == "begin":
            open_environments[name].append(match.start())
            continue
        if not open_environments[name]:
            raise WorkflowError(f"Unmatched \\end{{{name}}} in frontmatter source.")
        start = open_environments[name].pop()
        occurrences.setdefault(f"environment:{name}", []).append((start, match.end()))
    unclosed = [name for name, starts in open_environments.items() if starts]
    if unclosed:
        raise WorkflowError(
            "Unclosed single-value frontmatter environment: " + ", ".join(unclosed)
        )

    inactive = sorted(
        span for spans in occurrences.values() for span in sorted(spans)[:-1]
    )
    if not inactive:
        return text, 0
    masked = list(text)
    for start, end in inactive:
        for index in range(start, end):
            if masked[index] not in "\r\n":
                masked[index] = " "
    return "".join(masked), len(inactive)


def _whitespace_events(text: str) -> tuple[tuple[int, str], ...]:
    """Return exact TeX whitespace tokens with their current-source offsets."""
    events: list[tuple[int, str]] = []
    cursor = 0
    while cursor < len(text):
        if text.startswith(r"\ ", cursor):
            events.append((cursor, r"\ "))
            cursor += 2
            continue
        if text[cursor].isspace() or text[cursor] == "~":
            events.append((cursor, text[cursor]))
        cursor += 1
    return tuple(events)


def _diff_field(text: str, start: int) -> tuple[str, int]:
    try:
        return extract_braced(text, start)
    except ValueError as exc:
        raise WorkflowError(
            "Unbalanced braces while parsing latexdiff change evidence."
        ) from exc


def extract_addition_evidence(
    latexdiff_output: str,
) -> tuple[LatexdiffAddition, ...]:
    """Extract current additions without treating latexdiff output as layout."""
    macros = (
        r"\DIFaddFL",
        r"\DIFadd",
    )
    additions: list[LatexdiffAddition] = []
    cursor = 0
    while cursor < len(latexdiff_output):
        candidates = [
            (latexdiff_output.find(f"{macro}{{", cursor), macro) for macro in macros
        ]
        matches = [candidate for candidate in candidates if candidate[0] >= 0]
        if not matches:
            break
        index, macro = min(matches, key=lambda item: item[0])
        content, end = _diff_field(latexdiff_output, index + len(macro))
        additions.append(LatexdiffAddition(content, macro))
        cursor = end
    return tuple(additions)


def run_latexdiff(
    parent_source: Path,
    current_source: Path,
    output_path: Path,
    *,
    preamble: Path | None = None,
    text_commands: tuple[str, ...] = (),
    context_commands: tuple[str, ...] = (),
) -> tuple[LatexdiffAddition, ...]:
    """Run ``latexdiff`` as a change detector and persist its raw evidence."""
    executable = shutil.which("latexdiff")
    if executable is None:
        raise WorkflowError("latexdiff is required for revision change detection.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        "--encoding=utf8",
        "--packages=none",
        "--math-markup=WHOLE",
        "--no-del",
        "--no-label",
        "--disable-citation-markup",
        "--ignore-warnings",
    ]
    if preamble is not None:
        command.append(f"--preamble={preamble}")
    if context_commands:
        command.append("--append-context2cmd=" + ",".join(context_commands))
    if text_commands:
        command.append("--append-textcmd=" + ",".join(text_commands))
    command.extend((str(parent_source), str(current_source)))
    result = run_command(command, cwd=output_path.parent)
    output_path.write_text(result.stdout, encoding="utf-8")
    return extract_addition_evidence(result.stdout)


def _locate_additions(
    output: str,
    provenance: ProvenanceSource,
    detector_current: str | None = None,
) -> tuple[list[HighlightSpan], tuple[str, ...]]:
    """Map native addition fields back to exact current-source intervals."""
    detector_text = (
        detector_current if detector_current is not None else provenance.text
    )
    if len(detector_text) != len(provenance.text):
        raise WorkflowError("Detector/current source offsets do not match.")
    spans: list[HighlightSpan] = []
    unresolved: list[str] = []
    cursor = 0
    for change in extract_addition_evidence(output):
        content = re.sub(r"(?m)^([ \t]*)%DIF > ", r"\1%", change.content)
        if not content:
            continue
        start = detector_text.find(content, cursor)
        if start < 0:
            if display_evidence_is_covered(provenance.text, content):
                continue
            unresolved.append(change.content)
            continue
        end = start + len(content)
        for left, right, owner in split_by_review_provenance(provenance, start, end):
            spans.append(HighlightSpan(left, right, owner))
        cursor = end
    return spans, tuple(unresolved)


def _optional_field_end(text: str, start: int) -> int:
    """Return the end of one optional TeX field, or ``start`` when absent."""
    opening = skip_tex_space(text, start)
    if opening >= len(text) or text[opening] != "[":
        return start
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
                return cursor + 1
        cursor += 1
    raise WorkflowError("Unbalanced optional label in generated bibliography.")


def _parse_bibliography(text: str) -> _BibliographyDocument:
    """Parse generated ``\bibitem`` boundaries while preserving rendered TeX."""
    commands: list[tuple[int, int, str]] = []
    cursor = 0
    while cursor < len(text):
        start = text.find(r"\bibitem", cursor)
        if start < 0:
            break
        if (
            is_escaped(text, start)
            or is_commented(text, start)
            or not command_at(text, start, "bibitem")
        ):
            cursor = start + 1
            continue
        field_start = start + len(r"\bibitem")
        optional_end = _optional_field_end(text, field_start)
        if optional_end != field_start:
            field_start = optional_end
        try:
            key, end = extract_braced(text, field_start)
        except ValueError as exc:
            raise WorkflowError(
                "Malformed \\bibitem in generated bibliography."
            ) from exc
        key = key.strip()
        if not key:
            raise WorkflowError(
                "Generated bibliography contains an empty citation key."
            )
        commands.append((start, end, key))
        cursor = end

    footer_start = len(text)
    search_from = commands[-1][1] if commands else 0
    try:
        endings = scan_tex_commands(text, ("end",), field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed generated bibliography environment.") from exc
    for ending in endings:
        if ending.start >= search_from and ending.fields[0].endswith("bibliography"):
            footer_start = ending.start
            break
    if footer_start == len(text):
        raise WorkflowError("Generated bibliography has no closing environment.")

    entries: list[_BibliographyEntry] = []
    seen: set[str] = set()
    for index, (start, end, key) in enumerate(commands):
        if key in seen:
            raise WorkflowError(f"Duplicate generated bibliography key: {key}")
        seen.add(key)
        content_end = (
            commands[index + 1][0] if index + 1 < len(commands) else footer_start
        )
        entries.append(_BibliographyEntry(key, text[start:end], text[end:content_end]))
    header_end = commands[0][0] if commands else footer_start
    return _BibliographyDocument(
        text[:header_end],
        tuple(entries),
        text[footer_start:],
    )


def _bibliography_change_states(old: str, current: str) -> dict[str, str]:
    """Compare rendered entries by BibTeX key, never rendered number."""
    parent = _parse_bibliography(old)
    child = _parse_bibliography(current)
    parent_by_key = {entry.key: entry for entry in parent.entries}
    child_by_key = {entry.key: entry for entry in child.entries}
    states: dict[str, str] = {}
    for key in parent_by_key.keys() | child_by_key.keys():
        previous = parent_by_key.get(key)
        revised = child_by_key.get(key)
        if previous is None:
            states[key] = "added"
        elif revised is None:
            states[key] = "deleted"
        elif " ".join(previous.content.split()) == " ".join(revised.content.split()):
            states[key] = "unchanged"
        else:
            states[key] = "modified"
    return states


def _current_bibliography_with_reference_provenance(
    old: str,
    current: str,
    response_path: Path,
    citation_provenance: dict[str, CitationProvenance] | None = None,
    citation_source_path: Path | None = None,
) -> tuple[str, tuple[BibliographyNotice, ...]]:
    """Track reviewer-owned current entries while rendering all entries black."""
    document = _parse_bibliography(current)
    states = _bibliography_change_states(old, current)
    try:
        declarations = parse_response_source(response_path).references
    except WorkflowError:
        declarations = ()
    owners: dict[str, list[str]] = {}
    declaration_lines: dict[str, list[int]] = {}
    notices: list[BibliographyNotice] = []
    for declaration in declarations:
        for key in declaration.citation_keys:
            state = states.get(key)
            if state is None:
                raise WorkflowError(
                    f"ReviewReference {declaration.review_id} uses unknown citation "
                    f"key {key!r}: {response_path.resolve()}"
                )
            if state == "unchanged":
                notices.append(
                    BibliographyNotice(
                        "REVIEW_REFERENCE_UNCHANGED",
                        declaration.review_id,
                        key,
                        f"ReviewReference {declaration.review_id} declares {key}, "
                        "but no visible bibliography change was detected.",
                        response_path.resolve(),
                    )
                )
                continue
            if state == "deleted":
                notices.append(
                    BibliographyNotice(
                        "REVIEW_REFERENCE_DELETED",
                        declaration.review_id,
                        key,
                        f"Reference {key!r} was removed in this revision; no current "
                        "marked-manuscript bibliography location exists.",
                        response_path.resolve(),
                    )
                )
                continue
            key_owners = owners.setdefault(key, [])
            if declaration.review_id not in key_owners:
                key_owners.append(declaration.review_id)
            declaration_lines.setdefault(key, []).append(declaration.source_line)

    for key, provenance in (citation_provenance or {}).items():
        declared = owners.get(key, [])
        if provenance.review_ids is None and declared:
            citation_location = (
                f"{citation_source_path.resolve()}:{provenance.source_lines}"
                if citation_source_path is not None
                else f"current projection lines: {provenance.source_lines}"
            )
            raise WorkflowError(
                "REFERENCE_PROVENANCE_CONFLICT\n"
                f"key: {key}\n"
                f"citation provenance: AUTHOR ({citation_location})\n"
                "ReviewReference provenance: REVIEWER "
                f"{tuple(declared)} ({response_path.resolve()}:"
                f"{tuple(declaration_lines.get(key, []))})"
            )
        if provenance.review_ids is not None:
            owners[key] = list(dict.fromkeys((*provenance.review_ids, *declared)))

    parts = [document.header]
    for entry in document.entries:
        parts.append(entry.command)
        rendered_owners = owners.get(entry.key)
        if rendered_owners:
            parts.append(
                f"\\SCIReviewReferenceSpan{{{','.join(rendered_owners)}}}"
                f"{{{entry.content}}}"
            )
        else:
            parts.append(entry.content)
    parts.append(document.footer)
    return "".join(parts), tuple(notices)


def _remove_revision_output_diagnostics(output_dir: Path) -> None:
    """Remove obsolete machine audit copies from the user-facing PDF directory."""
    for name in ("diff_audit.json", "highlight_audit.json"):
        path = output_dir / name
        if path.is_file():
            path.unlink()


def _replace_bibliography(text: str, bibliography: str) -> str:
    """Replace BibTeX commands with one materialized visible bibliography."""
    try:
        commands = scan_tex_commands(
            text,
            ("bibliographystyle", "bibliography"),
            field_count=1,
        )
    except ValueError as exc:
        raise WorkflowError(
            "Malformed bibliography command in manuscript source."
        ) from exc
    bibliographies = [command for command in commands if command.name == "bibliography"]
    if len(bibliographies) != 1:
        raise WorkflowError(
            "Marked comparison requires exactly one active \\bibliography command."
        )
    pieces: list[str] = []
    cursor = 0
    for command in commands:
        pieces.append(text[cursor : command.start])
        if command.name == "bibliography":
            pieces.append(bibliography)
        cursor = command.end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _flatten_tex(
    path: Path,
    roots: tuple[Path, ...],
    active: tuple[Path, ...] = (),
) -> str:
    """Expand manuscript inputs for deterministic single-stream comparison."""
    resolved = path.resolve()
    if resolved in active:
        chain = " -> ".join(item.name for item in (*active, resolved))
        raise WorkflowError(f"Recursive TeX input detected: {chain}")
    if not any(resolved.is_relative_to(root.resolve()) for root in roots):
        raise WorkflowError(f"TeX input escapes permitted project roots: {resolved}")
    text = resolved.read_text(encoding="utf-8")

    def replace_input(name: str, original: str) -> str:
        name = name.strip()
        if name == "preamble" or name.startswith("preamble/"):
            return original
        candidate = resolved.parent / name
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".tex")
        if not candidate.exists():
            for root in roots:
                alternate = root / name
                if alternate.suffix == "":
                    alternate = alternate.with_suffix(".tex")
                if alternate.exists():
                    candidate = alternate
                    break
        if not candidate.exists():
            return original
        nested = _flatten_tex(candidate, roots, (*active, resolved))
        return f"\n% BEGIN INPUT {name}\n{nested}\n% END INPUT {name}\n"

    try:
        commands = scan_tex_commands(
            text,
            ("input", "include"),
            field_count=1,
        )
    except ValueError as exc:
        raise WorkflowError(f"Malformed active TeX input in {resolved}.") from exc
    pieces: list[str] = []
    cursor = 0
    for command in commands:
        pieces.append(text[cursor : command.start])
        original = text[command.start : command.end]
        pieces.append(replace_input(command.fields[0], original))
        cursor = command.end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _inject_revision_style(text: str, config: ProjectConfig) -> str:
    marker = r"\begin{document}"
    if text.count(marker) != 1:
        raise WorkflowError("Current source requires exactly one document start.")
    user_style = (config.references / "revision_style.tex").read_text(encoding="utf-8")
    style = (
        f"{STYLE_BEGIN}\n{user_style}\n{_revision_runtime(config.language)}\n"
        f"{STYLE_END}\n"
    )
    return text.replace(marker, style + marker, 1)


_AUX_IDENTITY = re.compile(
    r"\\(?P<kind>newlabel|bibcite)\{(?P<key>[^}]+)\}"
    r"\{\{?(?P<value>[^{}]*)"
)


def _tex_identity_state(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Read label/citation identities from AUX and reject duplicate definitions."""
    if not path.is_file():
        raise WorkflowError(f"TeX identity AUX is missing: {path}")
    labels: dict[str, str] = {}
    citations: dict[str, str] = {}
    for match in _AUX_IDENTITY.finditer(
        path.read_text(encoding="utf-8", errors="replace")
    ):
        key = match.group("key")
        if key.endswith("@cref") or key.startswith("sci:loc:"):
            continue
        target = citations if match.group("kind") == "bibcite" else labels
        if key in target:
            raise WorkflowError(
                f"TeX identity AUX contains duplicate {match.group('kind')} key: "
                f"{key!r}: {path}"
            )
        target[key] = match.group("value")
    return labels, citations


def _latexdiff_version() -> str:
    executable = shutil.which("latexdiff")
    if executable is None:
        raise WorkflowError("latexdiff is required for revision change detection.")
    result = run_command([executable, "--version"], cwd=Path.cwd())
    output = "\n".join((result.stdout, result.stderr))
    return next((line.strip() for line in output.splitlines() if line.strip()), "")


def build_marked_manuscript(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None = None,
    *,
    validate_clean: bool = True,
    include_locations: bool = True,
    reuse_marked_pdf: Path | None = None,
    current_bibliography_text: str | None = None,
    telemetry: BuildTelemetry | None = None,
) -> MarkedResult:
    """Publish the current manuscript with addition-only revision highlights."""
    if round_number < 1:
        raise WorkflowError("R0 has no highlighted revision manuscript.")
    migrate_revision_style_file(
        config.references / "revision_style.tex",
        config.archive_root(),
    )
    parent_dir = config.round_dir(round_number - 1)
    current_dir = config.round_dir(round_number)
    if not parent_dir.is_dir() or not current_dir.is_dir():
        raise WorkflowError("Highlighted revision requires adjacent rounds.")
    _remove_revision_output_diagnostics(config.output_dir(round_number))

    source_stage = (
        telemetry.measure("source_projection")
        if telemetry
        else contextlib.nullcontext()
    )
    with source_stage:
        source_dir = run_dir / "marked_source"
        parent_source_dir = run_dir / "parent_source"
        parent_source = stage_runtime_resources(
            config, round_number - 1, parent_source_dir, include_manuscript=True
        )
        current_source = stage_runtime_resources(
            config, round_number, source_dir, include_manuscript=True
        )
        parent_flat = _flatten_tex(parent_source, (parent_source_dir,))
        current_flat = _flatten_tex(current_source, (source_dir,))

    bibliography_stage = (
        telemetry.measure("bibliography_prepare")
        if telemetry
        else contextlib.nullcontext()
    )
    with bibliography_stage:
        bibliography_cache = config.tmp_root() / "cache" / "bibliography"
        parent_bibliography = materialize_bibliography(
            parent_source,
            parent_flat,
            run_dir / "parent_bibliography_build",
            config,
            engine_override,
            telemetry,
            bibliography_cache,
        )
        current_bibliography = current_bibliography_text
        if current_bibliography is None:
            current_bibliography = materialize_bibliography(
                current_source,
                current_flat,
                run_dir / "current_bibliography_build",
                config,
                engine_override,
                telemetry,
                bibliography_cache,
            )

    provenance_stage = (
        telemetry.measure("provenance_mapping")
        if telemetry
        else contextlib.nullcontext()
    )
    with provenance_stage:
        parent_compare = _replace_bibliography(parent_flat, current_bibliography)
        current_compare = _replace_bibliography(current_flat, current_bibliography)
        parent_compare, provenance = prepare_change_detection_sources(
            parent_compare, current_compare
        )
        detector_parent_text, shadowed_parent_fields = (
            _mask_overridden_frontmatter_fields(
                parent_compare, config.metadata.publisher
            )
        )
        detector_current_text, shadowed_current_fields = (
            _mask_overridden_frontmatter_fields(
                provenance.text, config.metadata.publisher
            )
        )
        detector_parent = source_dir / "detector_parent.tex"
        detector_current = source_dir / "detector_current.tex"
        detector_parent.write_text(detector_parent_text, encoding="utf-8")
        detector_current.write_text(detector_current_text, encoding="utf-8")
        evidence_path = source_dir / "latexdiff_addition_evidence.tex"
        detector_preamble = source_dir / "detector_preamble.tex"
        detector_preamble.write_text(
            f"{DETECTOR_STYLE_BEGIN}\n"
            "\\providecommand{\\DIFadd}[1]{#1}\n"
            "\\providecommand{\\DIFaddbegin}{}\n"
            "\\providecommand{\\DIFaddend}{}\n"
            "\\providecommand{\\DIFaddFL}[1]{#1}\n"
            "\\providecommand{\\DIFaddbeginFL}{}\n"
            "\\providecommand{\\DIFaddendFL}{}\n"
            f"{DETECTOR_STYLE_END}\n",
            encoding="utf-8",
        )

    latexdiff_stage = (
        telemetry.measure("latexdiff") if telemetry else contextlib.nullcontext()
    )
    with latexdiff_stage:
        if telemetry is not None:
            telemetry.latexdiff_invocations += 1
        run_latexdiff(
            detector_parent,
            detector_current,
            evidence_path,
            preamble=detector_preamble,
            text_commands=CHINESE_TEXT_COMMANDS
            if config.metadata.publisher == "chinese"
            else (),
            context_commands=PUBLISHER_METADATA_CONTEXT_COMMANDS,
        )

    mapping_stage = (
        telemetry.measure("provenance_mapping")
        if telemetry
        else contextlib.nullcontext()
    )
    with mapping_stage:
        evidence = evidence_path.read_text(encoding="utf-8")
        evidence_additions, unresolved = _locate_additions(
            evidence, provenance, detector_current_text
        )
        if unresolved:
            raise WorkflowError(
                "Latexdiff additions could not be resolved onto the current source."
            )
        additions, region_audit = structure_highlight_spans(
            parent_compare,
            provenance,
            evidence=evidence_additions,
            parent_asset_root=parent_source_dir,
            current_asset_root=source_dir,
            truth_path=run_dir / "revision_truth.json",
        )
        equations = [item for item in additions if item.kind == "display"]
        citations = citation_spans(parent_compare, provenance, evidence_additions)
        citation_provenance = added_citation_provenance(
            parent_compare, provenance, evidence_additions
        )
        marked_bibliography, bibliography_notices = (
            _current_bibliography_with_reference_provenance(
                parent_bibliography,
                current_bibliography,
                config.response_dir(round_number) / "responses.tex",
                citation_provenance,
                detector_current,
            )
        )
        all_protected_citations = protected_citation_spans(
            provenance, additions, citations
        )
        protected_citations = [
            citation
            for citation in all_protected_citations
            if not any(
                equation.start < citation.end and equation.end > citation.start
                for equation in equations
            )
        ]
        additions = replace_special_spans(additions, [*protected_citations, *equations])
        additions = preserve_topology_seams(provenance.text, additions)
        expected_revision_events = revision_render_registry(additions)

    render_stage = (
        telemetry.measure("highlight_render") if telemetry else contextlib.nullcontext()
    )
    with render_stage:
        highlighted = apply_highlights(provenance.text, additions)
        (source_dir / "highlighted_pre_bibliography.tex").write_text(
            highlighted, encoding="utf-8"
        )
        if highlighted.count(current_bibliography) != 1:
            raise WorkflowError(
                "Current bibliography boundary changed during highlighting."
            )
        highlighted = highlighted.replace(current_bibliography, marked_bibliography, 1)
        current_projection = provenance.text
        marked_text = _inject_revision_style(highlighted, config)
        projected_marked = _strip_highlight_markup(marked_text, STYLE_BEGIN, STYLE_END)
        (source_dir / "current_projection.tex").write_text(
            current_projection, encoding="utf-8"
        )
        (source_dir / "marked_projection.tex").write_text(
            projected_marked, encoding="utf-8"
        )
        source_projection_identity = projected_marked == current_projection
        whitespace_seam_identity = _whitespace_events(
            projected_marked
        ) == _whitespace_events(current_projection)
        if not source_projection_identity or not whitespace_seam_identity:
            raise WorkflowError(
                "Highlighted source projection differs from the current clean source."
            )
        topology = validate_topology_identity(
            current_projection,
            projected_marked,
            source_dir / "marked_projection.tex",
        )

    marked_source = source_dir / "manuscript_marked.tex"
    marked_source.write_text(marked_text, encoding="utf-8")
    if include_locations:
        instrument_location_source(marked_source, round_number)
    marked_aux: Path | None = None
    if reuse_marked_pdf is None:
        compile_stage = (
            telemetry.measure("marked_compile")
            if telemetry
            else contextlib.nullcontext()
        )
        with compile_stage:
            compiled = compile_tex(
                marked_source,
                run_dir / "marked_build",
                config,
                engine_override,
                keep_intermediates=True,
                telemetry=telemetry,
            )
        marked_pdf = compiled.pdf
        marked_aux = compiled.state.aux
    else:
        if not reuse_marked_pdf.is_file():
            raise WorkflowError(
                f"Reusable marked artifact is missing: {reuse_marked_pdf}"
            )
        marked_pdf = reuse_marked_pdf

    validation_stage = (
        telemetry.measure("validation") if telemetry else contextlib.nullcontext()
    )
    with validation_stage:
        numbering_identity: bool | None = None
        citation_state_identity: bool | None = None
        bibliography_state_identity: bool | None = None
        if validate_clean:
            if marked_aux is None:
                raise WorkflowError(
                    "Full marked validation requires a fresh marked compilation."
                )
            clean_aux = run_dir / "clean_build" / "manuscript.aux"
            clean_labels, clean_citations = _tex_identity_state(clean_aux)
            marked_labels, marked_citations = _tex_identity_state(marked_aux)
            numbering_identity = clean_labels == marked_labels
            citation_state_identity = clean_citations == marked_citations
            bibliography_state_identity = tuple(
                entry.key for entry in _parse_bibliography(current_bibliography).entries
            ) == tuple(
                entry.key for entry in _parse_bibliography(marked_bibliography).entries
            )
            if not (
                numbering_identity
                and citation_state_identity
                and bibliography_state_identity
            ):
                raise WorkflowError(
                    "Clean/marked TeX numbering, citation, or bibliography state "
                    "identity validation failed."
                )

    locations: dict[str, str] = {}
    if include_locations:
        locations = build_review_locations(
            config,
            round_number,
            run_dir,
            engine_override,
            marked_source,
            marked_pdf,
            telemetry,
        )
    state_stage = (
        telemetry.measure("tex_state_parse") if telemetry else contextlib.nullcontext()
    )
    with state_stage:
        state_started = time.perf_counter()
        marked_sci = run_dir / "marked_build" / "manuscript_marked.sci"
        marked_state = parse_sci_state(marked_sci, "marked")
        _validate_revision_render_registry(
            expected_revision_events,
            marked_state.events,
        )
        _complete_revision_truth(
            run_dir / "revision_truth.json",
            tuple(event for event in marked_state.events if event.kind == "REVISION"),
            time.perf_counter() - state_started,
        )
    reviewer_ids = {
        review_id for span in additions for review_id in (span.review_ids or ())
    }
    pure_deletions: list[str] = []
    if include_locations:
        pure_deletions = sorted(
            review_ids_from_sources(config, round_number)
            - reviewer_ids
            - set(locations)
        )
        deletion_note = (
            "相关内容已删除，当前稿无对应高亮文本"  # noqa: RUF001
            if config.language == "zh"
            else "The relevant text has been removed; no corresponding highlighted "
            "text remains in the revised manuscript"
        )
        locations.update(dict.fromkeys(pure_deletions, deletion_note))

    bibliography_states = _bibliography_change_states(
        parent_bibliography, current_bibliography
    )
    _validate_reference_style_contract()
    bibliography_changes = sum(
        state in {"added", "modified"} for state in bibliography_states.values()
    )
    reviewer_bibliography_events = marked_bibliography.count(
        r"\SCIReviewReferenceSpan{"
    )
    audit = {
        "latexdiff_version": _latexdiff_version(),
        "region_parent_blocks": region_audit.parent_blocks,
        "region_current_blocks": region_audit.current_blocks,
        "region_unchanged_blocks": region_audit.unchanged_blocks,
        "region_changed_units": region_audit.changed_units,
        "region_structural_moves": region_audit.structural_moves,
        "region_reordered_units": region_audit.reordered_units,
        "region_equation_structural_events": region_audit.equation_structural_events,
        "region_figure_asset_changes": region_audit.figure_asset_changes,
        "region_ambiguous_duplicate_groups": region_audit.ambiguous_duplicate_groups,
        "reviewer_highlight_spans": sum(
            item.review_ids is not None and item.kind != "citation"
            for item in additions
        ),
        "author_highlight_spans": sum(
            item.review_ids is None and item.kind != "citation" for item in additions
        ),
        "equations_whole_highlighted": len(equations),
        "citation_groups_highlighted": 0,
        "bibliography_entries_highlighted": 0,
        "reference_visual_policy": "xcolor blue (#0000FF)",
        "clean_marked_reference_style_identity": True,
        "citation_changes_tracked": len(citations),
        "bibliography_changes_tracked": bibliography_changes,
        "reviewer_reference_location_events": sum(
            item.review_ids is not None for item in all_protected_citations
        )
        + reviewer_bibliography_events,
        "author_reference_changes": sum(item.review_ids is None for item in citations)
        + max(0, bibliography_changes - reviewer_bibliography_events),
        "protected_citation_spans": len(all_protected_citations),
        "pure_deletion_reviews": pure_deletions,
        "validation_scope": (
            "source+tex_state" if validate_clean else "source+marked_tex_state"
        ),
        "clean_marked_source_projection_identity": source_projection_identity,
        "clean_marked_numbering_identity": numbering_identity,
        "numbering_identity_from_tex_state": numbering_identity,
        "citation_state_identity_from_tex": citation_state_identity,
        "bibliography_state_identity_from_tex": bibliography_state_identity,
        "marked_tex_sidecar_registry_complete": True,
        "visual_revision_event_count": len(expected_revision_events),
        "change_certificate_count": len(expected_revision_events),
        "render_certificate_count": len(expected_revision_events),
        "unexpected_render_events": 0,
        "missing_render_events": 0,
        "duplicate_render_events": 0,
        "owner_conflicts": 0,
        "clean_marked_block_topology_identity": True,
        "clean_marked_paragraph_identity": True,
        "paragraph_boundary_count_clean": topology.paragraph_boundary_count_clean,
        "paragraph_boundary_count_marked": topology.paragraph_boundary_count_marked,
        "clean_paragraph_count": topology.paragraph_count_clean,
        "marked_paragraph_count": topology.paragraph_count_marked,
        "whitespace_seam_identity": whitespace_seam_identity,
        "shadowed_frontmatter_fields_parent": shadowed_parent_fields,
        "shadowed_frontmatter_fields_current": shadowed_current_fields,
        "reference_provenance_conflicts": 0,
        "unresolved_additions": len(unresolved),
    }
    audit_path = run_dir / "highlight_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output = config.output_dir(round_number) / "manuscript_marked.pdf"
    if reuse_marked_pdf is None:
        publish_stage = (
            telemetry.measure("artifact_publish")
            if telemetry
            else contextlib.nullcontext()
        )
        with publish_stage:
            output = publish_file_atomically(marked_pdf, output)
    aux_path = marked_aux
    if aux_path is None and include_locations:
        candidate = run_dir / "marked_build" / "manuscript_marked.aux"
        aux_path = candidate if candidate.is_file() else None
    return MarkedResult(
        output,
        locations,
        bibliography_notices,
        aux_path,
        audit_path,
    )
