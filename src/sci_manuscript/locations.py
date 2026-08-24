"""Reviewer-location compilation and localized line-range formatting."""

from __future__ import annotations

import collections
import re
import shutil
from pathlib import Path

from .compile import compile_tex, stage_runtime_resources
from .errors import WorkflowError
from .review_ids import is_review_id
from .templates import resources_root
from .workspace import ProjectConfig

REVIEW_REGISTRY_HEADER = "sci-manuscript-reviewloc-v2"
LABEL_PATTERN = re.compile(r"\\newlabel\{review:(\d+):(start|end)\}\{\{(\d+)\}")


def _parse_registry(path: Path) -> list[tuple[str, int]]:
    if not path.exists():
        raise WorkflowError(f"Location build did not create a review registry: {path}")
    records: list[tuple[str, int]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or (number == 1 and line == REVIEW_REGISTRY_HEADER):
            continue
        fields = line.split("|")
        if len(fields) != 2 or not fields[1].isdigit():
            raise WorkflowError(f"Malformed review registry at line {number}: {raw}")
        records.append((fields[0], int(fields[1])))
    return records


def _parse_labels(path: Path) -> dict[tuple[int, str], int]:
    if not path.exists():
        raise WorkflowError(
            f"Location build did not create a line-number AUX file: {path}"
        )
    labels: dict[tuple[int, str], int] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for block, edge, line in LABEL_PATTERN.findall(text):
        labels[(int(block), edge)] = int(line)
    return labels


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


def calculate_locations(
    build_dir: Path,
    stem: str = "manuscript_marked",
    language: str = "en",
) -> dict[str, str]:
    """Calculate reviewer locations from the registry and line-label AUX files."""
    registry = _parse_registry(build_dir / f"{stem}.reviewloc")
    labels = _parse_labels(build_dir / f"{stem}.aux")
    by_comment: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    for ids, block in registry:
        start = labels.get((block, "start"))
        end = labels.get((block, "end"))
        if start is None or end is None:
            raise WorkflowError(f"Line labels are missing for reviewer block {block}.")
        location = (start, end)
        for review_id in (item.strip() for item in ids.split(",")):
            if not is_review_id(review_id):
                raise WorkflowError(
                    f"Invalid reviewer ID {review_id!r}; expected E-1 or 1-1."
                )
            if location not in by_comment[review_id]:
                by_comment[review_id].append(location)
    return {
        key: _format_locations(value, language) for key, value in by_comment.items()
    }


def build_review_locations(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None,
) -> dict[str, str]:
    """Compile transparent review wrappers solely for response locations."""
    source_dir = run_dir / "location_source"
    source = stage_runtime_resources(
        config,
        round_number,
        source_dir,
        include_manuscript=True,
    )
    runtime = source_dir / "revision_location_runtime.tex"
    runtime.write_text(
        (resources_root() / "revision" / "location_runtime.tex").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    text = source.read_text(encoding="utf-8")
    marker = r"\begin{document}"
    if marker not in text:
        raise WorkflowError("Manuscript source does not contain \\begin{document}.")
    source.write_text(
        text.replace(marker, f"\\input{{revision_location_runtime.tex}}\n{marker}", 1),
        encoding="utf-8",
    )
    build_dir = run_dir / "location_build"
    compile_tex(
        source,
        build_dir,
        config,
        engine_override,
        keep_intermediates=True,
    )
    locations = calculate_locations(build_dir, source.stem, config.language)

    marked_build = run_dir / "marked_build"
    marked_build.mkdir(exist_ok=True)
    for suffix in ("reviewloc", "aux"):
        candidate = build_dir / f"{source.stem}.{suffix}"
        if candidate.exists():
            shutil.copy2(candidate, marked_build / f"manuscript_marked.{suffix}")
    return locations
