"""Lightweight wall-clock telemetry for manuscript builds."""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

TIMING_STAGES = (
    "project_load",
    "round_resolution",
    "preflight",
    "source_projection",
    "bibliography_prepare",
    "latexdiff",
    "provenance_mapping",
    "highlight_render",
    "clean_compile",
    "marked_compile",
    "location_compile_or_passes",
    "location_extract",
    "response_render",
    "response_compile",
    "validation",
    "artifact_publish",
)


@dataclass(frozen=True)
class TimingReport:
    """Immutable build timing returned through the public lifecycle result."""

    stages: tuple[tuple[str, float], ...]
    total: float
    latex_invocations: int
    bibliography_invocations: int
    bibliography_cache_hits: int
    latexdiff_invocations: int

    def as_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible telemetry fields."""
        return {
            "stages": dict(self.stages),
            "total": self.total,
            "latex_invocation_count": self.latex_invocations,
            "bibliography_invocation_count": self.bibliography_invocations,
            "bibliography_cache_hits": self.bibliography_cache_hits,
            "latexdiff_invocation_count": self.latexdiff_invocations,
        }


@dataclass
class BuildTelemetry:
    """Accumulate deterministic stage timings and external invocation counts."""

    started: float = field(default_factory=time.perf_counter)
    durations: dict[str, float] = field(default_factory=dict)
    latex_invocations: int = 0
    bibliography_invocations: int = 0
    bibliography_cache_hits: int = 0
    latexdiff_invocations: int = 0

    @contextlib.contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        """Accumulate elapsed wall time for one named stage."""
        before = time.perf_counter()
        try:
            yield
        finally:
            self.durations[stage] = self.durations.get(stage, 0.0) + (
                time.perf_counter() - before
            )

    def report(self) -> TimingReport:
        """Freeze the current measurements in canonical display order."""
        ordered = tuple(
            (name, self.durations[name])
            for name in TIMING_STAGES
            if name in self.durations
        )
        extras = tuple(
            (name, duration)
            for name, duration in sorted(self.durations.items())
            if name not in TIMING_STAGES
        )
        return TimingReport(
            (*ordered, *extras),
            time.perf_counter() - self.started,
            self.latex_invocations,
            self.bibliography_invocations,
            self.bibliography_cache_hits,
            self.latexdiff_invocations,
        )

    def write(self, path: Path) -> Path:
        """Write detailed telemetry inside one internal run workspace."""
        path.write_text(
            json.dumps(self.report().as_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        return path
