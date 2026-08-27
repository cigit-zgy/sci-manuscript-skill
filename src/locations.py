"""TeX-native reviewer-location resolution and localized range formatting."""

from __future__ import annotations

import collections
import contextlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from .compile import compile_tex
from .errors import WorkflowError
from .review_ids import is_review_id
from .templates import resources_root
from .tex import is_commented
from .timing import BuildTelemetry
from .workspace import ProjectConfig

TEX_LOCATION_REGISTRY_HEADER = "sci-manuscript-reviewloc-tex-v1"
LOCATION_LABEL_PREFIX = "sci:loc:"

VISIBLE_REVIEW_REVISION = "VISIBLE_REVIEW_REVISION"
REVIEW_REFERENCE_LOCATION = "REVIEW_REFERENCE_LOCATION"
_ALLOWED_LOCATION_EVENT_KINDS = frozenset(
    {VISIBLE_REVIEW_REVISION, REVIEW_REFERENCE_LOCATION}
)
_LOCATION_SOURCE_KINDS = {
    "SCIReviewSpan": VISIBLE_REVIEW_REVISION,
    "SCIReviewDisplayBegin": VISIBLE_REVIEW_REVISION,
    "SCIReviewReferenceSpan": REVIEW_REFERENCE_LOCATION,
}
_PACKAGE_LABEL = re.compile(
    r"\\newlabel\{(?P<label>sci:loc:[^{}]+)\}"
    r"\{\{(?P<line>[^{}]*)\}\{"
)
_PACKAGE_LABEL_NAME = re.compile(r"sci:loc:r[0-9]+:e[0-9]+:(?:start|end)\Z")
_LOCATION_TOKEN = re.compile(
    r"\\(?:(?P<edge>begin|end)\{(?P<environment>[A-Za-z*]+)\}"
    r"|(?P<source>SCIReviewSpan|SCIReviewReferenceSpan|SCIReviewDisplayBegin)"
    r"\{(?P<review_ids>[^{}]+)\})"
)
_SUPPORTED_LOCATION_MATH_ENVIRONMENTS = frozenset({"equation", "equation*"})
_KNOWN_LOCATION_MATH_ENVIRONMENTS = frozenset(
    {
        "align",
        "align*",
        "displaymath",
        "equation",
        "equation*",
        "gather",
        "gather*",
        "multline",
        "multline*",
    }
)


@dataclass(frozen=True, slots=True)
class _LocationRecord:
    review_ids: str
    event_id: str
    event_kind: str
    event_source: str
    source_line: int
    start_label: str
    end_label: str


def _format_locations(ranges: list[tuple[int, int]], language: str) -> str:
    """Format line ranges as one complete Chinese or English phrase."""
    if not ranges:
        return "位置不可用" if language == "zh" else "Location unavailable"
    if language == "zh":
        parts = [
            f"第 {start if start == end else f'{start}--{end}'} 行"
            for start, end in ranges
        ]
        if len(parts) == 1:
            return parts[0]
        return (
            "和".join(parts)
            if len(parts) == 2
            else "、".join(parts[:-1]) + "和" + parts[-1]
        )
    values = [
        str(start) if start == end else f"{start}--{end}" for start, end in ranges
    ]
    if len(values) == 1:
        prefix = "Line" if ranges[0][0] == ranges[0][1] else "Lines"
        return f"{prefix} {values[0]}"
    joined = (
        f"{values[0]} and {values[1]}"
        if len(values) == 2
        else f"{', '.join(values[:-1])}, and {values[-1]}"
    )
    return f"Lines {joined}"


def _normalize_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge duplicate, overlapping, and adjacent already-valid ranges."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def parse_location_labels(aux_path: Path) -> dict[str, int]:
    """Read positive line numbers for package-owned labels from one AUX file."""
    if not aux_path.is_file():
        raise WorkflowError(
            f"LINE_LOCATION_RESOLUTION_ERROR: AUX file is missing: {aux_path}"
        )
    labels: dict[str, int] = {}
    for number, raw in enumerate(
        aux_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if rf"\newlabel{{{LOCATION_LABEL_PREFIX}" not in raw:
            continue
        match = _PACKAGE_LABEL.search(raw)
        if match is None:
            raise WorkflowError(
                "LINE_LOCATION_RESOLUTION_ERROR: malformed package-owned label "
                f"at {aux_path}:{number}."
            )
        label = match.group("label")
        value = match.group("line").strip()
        if _PACKAGE_LABEL_NAME.fullmatch(label) is None:
            raise WorkflowError(
                "LINE_LOCATION_RESOLUTION_ERROR: invalid package-owned label "
                f"{label!r} at {aux_path}:{number}."
            )
        if not value.isdigit() or int(value) < 1:
            raise WorkflowError(
                "LINE_LOCATION_RESOLUTION_ERROR: expected a positive integer for "
                f"label {label!r} at {aux_path}:{number}; got {value!r}."
            )
        line = int(value)
        previous = labels.get(label)
        if previous is not None and previous != line:
            raise WorkflowError(
                "LINE_LOCATION_RESOLUTION_ERROR: conflicting values for package "
                f"label {label!r}: {previous} and {line}."
            )
        labels[label] = line
    return labels


def _parse_tex_registry(path: Path) -> list[_LocationRecord]:
    """Read the deterministic event-to-label registry emitted by package TeX."""
    if not path.is_file():
        raise WorkflowError(
            f"LINE_LOCATION_RESOLUTION_ERROR: review registry is missing: {path}"
        )
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != TEX_LOCATION_REGISTRY_HEADER:
        raise WorkflowError(
            f"LINE_LOCATION_RESOLUTION_ERROR: unsupported review registry: {path}"
        )
    records: list[_LocationRecord] = []
    seen_event_ids: set[str] = set()
    for number, raw in enumerate(lines[1:], 2):
        fields = raw.strip().split("|")
        if (
            len(fields) != 7
            or re.fullmatch(r"e[0-9]+", fields[1]) is None
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", fields[2]) is None
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", fields[3]) is None
            or not fields[4].isdigit()
            or _PACKAGE_LABEL_NAME.fullmatch(fields[5]) is None
            or _PACKAGE_LABEL_NAME.fullmatch(fields[6]) is None
        ):
            raise WorkflowError(
                "LINE_LOCATION_RESOLUTION_ERROR: malformed review registry at "
                f"{path}:{number}: {raw}"
            )
        source_line = int(fields[4])
        if source_line < 1:
            raise WorkflowError(
                "LINE_LOCATION_RESOLUTION_ERROR: invalid source line at "
                f"{path}:{number}: {raw}"
            )
        if fields[1] in seen_event_ids:
            raise WorkflowError(
                "LINE_LOCATION_RESOLUTION_ERROR: duplicate event ID "
                f"{fields[1]!r} at {path}:{number}."
            )
        seen_event_ids.add(fields[1])
        records.append(
            _LocationRecord(
                review_ids=fields[0],
                event_id=fields[1],
                event_kind=fields[2],
                event_source=fields[3],
                source_line=source_line,
                start_label=fields[5],
                end_label=fields[6],
            )
        )
    return records


def _event_rejection_reason(record: _LocationRecord) -> str | None:
    """Return why an event is outside the frozen location allowlist."""
    if record.event_kind == "AUTHOR_REFERENCE_LOCATION":
        return "wrong_provenance"
    if record.event_kind not in _ALLOWED_LOCATION_EVENT_KINDS:
        return "generic_marker"
    if _LOCATION_SOURCE_KINDS.get(record.event_source) != record.event_kind:
        return "wrong_provenance"
    return None


def _source_offsets(source_path: Path | None, line_number: int) -> tuple[int, int]:
    """Return deterministic character offsets for one registry source line."""
    if source_path is None or not source_path.is_file():
        return 0, 0
    lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if line_number > len(lines):
        return 0, 0
    start = sum(len(line) for line in lines[: line_number - 1])
    return start, start + len(lines[line_number - 1])


def _resolution_error(
    record: _LocationRecord, source_file: str, detail: str
) -> NoReturn:
    raise WorkflowError(
        "LINE_LOCATION_RESOLUTION_ERROR: "
        f"{detail}; review ID {record.review_ids}; event ID {record.event_id}; "
        f"source {record.event_source}; source file {source_file}; "
        f"source line {record.source_line}."
    )


def calculate_tex_locations(
    registry_path: Path,
    aux_path: Path,
    language: str,
    source_path: Path | None = None,
) -> tuple[dict[str, str], dict[str, object]]:
    """Resolve allowed reviewer events exclusively from TeX line labels."""
    registry = _parse_tex_registry(registry_path)
    labels = parse_location_labels(aux_path)
    by_comment: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    location_events: list[dict[str, object]] = []
    rejected_events: list[dict[str, object]] = []
    source_file = str(source_path if source_path is not None else registry_path)
    expected_labels: set[str] = set()
    for record in registry:
        review_ids = [item.strip() for item in record.review_ids.split(",")]
        for review_id in review_ids:
            if not is_review_id(review_id):
                raise WorkflowError(
                    f"Invalid reviewer ID {review_id!r}; expected E-1, AE-1, or 1-1."
                )
        source_start, source_end = _source_offsets(source_path, record.source_line)
        event: dict[str, object] = {
            "review_id": record.review_ids,
            "event_id": record.event_id,
            "event_kind": record.event_kind,
            "event_source": record.event_source,
            "source_file": source_file,
            "source_line": record.source_line,
            "source_start": source_start,
            "source_end": source_end,
            "start_label": record.start_label,
            "end_label": record.end_label,
            "resolved_start": None,
            "resolved_end": None,
        }
        rejection = _event_rejection_reason(record)
        if rejection is not None:
            event["rejection_reason"] = rejection
            rejected_events.append(event)
            continue
        expected_labels.update((record.start_label, record.end_label))
        start = labels.get(record.start_label)
        end = labels.get(record.end_label)
        if start is None:
            _resolution_error(record, source_file, "missing start label")
        if end is None:
            _resolution_error(record, source_file, "missing end label")
        if start > end:
            _resolution_error(
                record,
                source_file,
                f"start {start} exceeds end {end}",
            )
        event["resolved_start"] = start
        event["resolved_end"] = end
        location_events.append(event)
        for review_id in review_ids:
            by_comment[review_id].append((start, end))

    locations = {
        review_id: _format_locations(_normalize_ranges(ranges), language)
        for review_id, ranges in by_comment.items()
    }
    return locations, {
        "location_backend": "tex-linelabel",
        "location_events": location_events,
        "resolved_labels": len(expected_labels),
        "unresolved_labels": [],
        "reported_locations": locations,
        "location_event_allowlist": sorted(_ALLOWED_LOCATION_EVENT_KINDS),
        "review_location_events_total": len(registry),
        "review_location_events_valid": len(location_events),
        "review_location_events_rejected": len(rejected_events),
        "rejected_location_events": rejected_events,
    }


def _event_id(number: int) -> str:
    return f"e{number:04d}"


def _validate_location_math_text(text: str, source_path: Path) -> None:
    """Reject reviewed display environments not proven safe with current lineno."""
    document_start = text.find(r"\begin{document}")
    scan_start = document_start if document_start >= 0 else 0
    stack: list[str] = []
    event_number = 0
    for match in _LOCATION_TOKEN.finditer(text, scan_start):
        if is_commented(text, match.start()):
            continue
        edge = match.group("edge")
        if edge == "begin":
            stack.append(match.group("environment"))
            continue
        if edge == "end":
            environment = match.group("environment")
            if environment in stack:
                reverse_index = stack[::-1].index(environment)
                del stack[len(stack) - reverse_index - 1 :]
            continue
        event_number += 1
        if match.group("source") != "SCIReviewDisplayBegin":
            continue
        environment = next(
            (
                item
                for item in reversed(stack)
                if item in _KNOWN_LOCATION_MATH_ENVIRONMENTS
            ),
            "unknown",
        )
        if environment in _SUPPORTED_LOCATION_MATH_ENVIRONMENTS:
            continue
        raise WorkflowError(
            "LINE_LOCATION_UNSUPPORTED_MATH_ENVIRONMENT: "
            f"environment={environment}; source file={source_path}; "
            f"review ID={match.group('review_ids')}; "
            f"event ID={_event_id(event_number)}."
        )


def validate_location_math_environments(source_path: Path) -> None:
    """Validate reviewed display environments in one generated marked source."""
    _validate_location_math_text(source_path.read_text(encoding="utf-8"), source_path)


def instrument_location_source(
    source_path: Path,
    round_number: int,
) -> None:
    """Add package-owned, layout-neutral location instrumentation in place."""
    text = source_path.read_text(encoding="utf-8")
    if r"\input{revision_location_runtime.tex}" in text:
        validate_location_math_environments(source_path)
        return
    _validate_location_math_text(text, source_path)
    documentclass = re.search(r"(?m)^[ \t]*\\documentclass\b", text)
    if documentclass is None:
        raise WorkflowError("Manuscript source does not contain \\documentclass.")
    document_start = r"\begin{document}"
    if text.count(document_start) != 1:
        raise WorkflowError("Manuscript source requires exactly one document start.")
    runtime_template = (
        resources_root() / "revision" / "location_runtime.tex"
    ).read_text(encoding="utf-8")
    if runtime_template.count("%%ROUND_NAMESPACE%%") != 2:
        raise WorkflowError("Location runtime has an invalid round-namespace token.")
    runtime = source_path.parent / "revision_location_runtime.tex"
    runtime.write_text(
        runtime_template.replace("%%ROUND_NAMESPACE%%", f"r{round_number:02d}"),
        encoding="utf-8",
    )
    text = (
        text[: documentclass.start()]
        + r"\PassOptionsToPackage{mathrefs}{lineno}"
        + "\n"
        + text[documentclass.start() :]
    )
    text = text.replace(
        document_start,
        "\\input{revision_location_runtime.tex}\n" + document_start,
        1,
    )
    source_path.write_text(text, encoding="utf-8")


def build_review_locations(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None,
    marked_source: Path,
    marked_pdf: Path,
    telemetry: BuildTelemetry | None = None,
) -> dict[str, str]:
    """Resolve reviewer locations from TeX labels, compiling only if needed."""
    del marked_pdf
    instrument_location_source(marked_source, round_number)
    build_dir = run_dir / "marked_build"
    aux_path = build_dir / f"{marked_source.stem}.aux"
    registry_path = build_dir / f"{marked_source.stem}.reviewloc"
    if not aux_path.is_file() or not registry_path.is_file():
        compile_stage = (
            telemetry.measure("location_compile_or_passes")
            if telemetry
            else contextlib.nullcontext()
        )
        with compile_stage:
            compile_tex(
                marked_source,
                build_dir,
                config,
                engine_override,
                keep_intermediates=True,
                telemetry=telemetry,
            )
    extract_stage = (
        telemetry.measure("location_extract") if telemetry else contextlib.nullcontext()
    )
    with extract_stage:
        locations, report = calculate_tex_locations(
            registry_path,
            aux_path,
            config.language,
            source_path=marked_source,
        )
        (run_dir / "review_location_events.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return locations
