"""Rendered regression tests for continuous Chinese revision marks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sci_manuscript.compile import stage_cjk_fonts


pytestmark = pytest.mark.integration

TARGETS = {
    "green": (0, 135, 90),
    "blue": (0, 92, 153),
    "red": (220, 45, 45),
}


def _require_tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        pytest.skip(f"{name} is required for rendered revision-mark validation")
    return executable


def _ppm(path: Path) -> tuple[int, int, bytes]:
    magic, dimensions, maximum, pixels = path.read_bytes().split(b"\n", 3)
    assert magic == b"P6"
    assert maximum == b"255"
    width, height = (int(value) for value in dimensions.split())
    assert len(pixels) == width * height * 3
    return width, height, pixels


def _target_coordinates(
    width: int,
    height: int,
    pixels: bytes,
    target: tuple[int, int, int],
    tolerance: int = 60,
) -> list[tuple[int, int]]:
    coordinates: list[tuple[int, int]] = []
    for y in range(height):
        row = y * width * 3
        for x in range(width):
            index = row + x * 3
            if all(
                abs(pixels[index + channel] - target[channel]) <= tolerance
                for channel in range(3)
            ):
                coordinates.append((x, y))
    return coordinates


def _y_clusters(coordinates: list[tuple[int, int]]) -> list[list[int]]:
    clusters: list[list[int]] = []
    current: list[int] = []
    previous: int | None = None
    for y in sorted({y for _, y in coordinates}):
        if previous is None or y <= previous + 2:
            current.append(y)
        else:
            clusters.append(current)
            current = [y]
        previous = y
    if current:
        clusters.append(current)
    return clusters


def _maximum_internal_gap(
    coordinates: list[tuple[int, int]],
    rows: list[int],
) -> int:
    selected_rows = set(rows)
    columns = sorted({x for x, y in coordinates if y in selected_rows})
    assert columns
    return max(
        (right - left - 1 for left, right in zip(columns, columns[1:])), default=0
    )


def test_starred_cjk_decorators_are_visually_continuous_across_punctuation(
    tmp_path: Path,
) -> None:
    """Rendered starred marks must bridge punctuation that legacy forms skip."""
    tectonic = _require_tool("tectonic")
    pdftoppm = _require_tool("pdftoppm")
    staged = stage_cjk_fonts(tmp_path)
    assert staged, "Fandol fonts must be staged by the integration environment"

    source = tmp_path / "continuity.tex"
    source.write_text(
        r"""\documentclass{article}
\usepackage[paperwidth=160mm,paperheight=90mm,margin=10mm]{geometry}
\usepackage{fontspec}
\usepackage{xeCJK}
\usepackage{xeCJKfntef}
\usepackage{xcolor}
\setCJKmainfont[Path=./]{FandolSong-Regular.otf}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\definecolor{RevisionBlue}{RGB}{0,92,153}
\definecolor{RevisionRed}{RGB}{220,45,45}
\definecolor{RevisionGreen}{RGB}{0,135,90}
\begin{document}
\fontsize{16}{24}\selectfont
STAR U: \CJKunderline*[format=\color{RevisionGreen},textformat=\color{black}]{甲，乙。丙；丁：戊（己）庚！辛？壬}\par
OLD U: \CJKunderline[format=\color{RevisionGreen},textformat=\color{black}]{甲，乙。丙；丁：戊（己）庚！辛？壬}\par
STAR W: \CJKunderwave*[format=\color{RevisionBlue},textformat=\color{black}]{甲，乙。丙；丁：戊（己）庚！辛？壬}\par
OLD W: \CJKunderwave[format=\color{RevisionBlue},textformat=\color{black}]{甲，乙。丙；丁：戊（己）庚！辛？壬}\par
STAR S: \CJKsout*[format=\color{RevisionRed},textformat=\color{black}]{甲，乙。丙；丁：戊（己）庚！辛？壬}\par
OLD S: \CJKsout[format=\color{RevisionRed},textformat=\color{black}]{甲，乙。丙；丁：戊（己）庚！辛？壬}\par
\end{document}
""",
        encoding="utf-8",
    )
    output = tmp_path / "build"
    output.mkdir()
    subprocess.run(
        [
            tectonic,
            "-X",
            "compile",
            f"--outdir={output}",
            str(source),
        ],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    prefix = tmp_path / "continuity"
    subprocess.run(
        [
            pdftoppm,
            "-f",
            "1",
            "-singlefile",
            "-r",
            "200",
            str(output / "continuity.pdf"),
            str(prefix),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    width, height, pixels = _ppm(prefix.with_suffix(".ppm"))
    for name, target in TARGETS.items():
        coordinates = _target_coordinates(width, height, pixels, target)
        clusters = _y_clusters(coordinates)
        assert len(clusters) == 2, f"{name}: expected starred and legacy mark rows"
        starred_gap = _maximum_internal_gap(coordinates, clusters[0])
        legacy_gap = _maximum_internal_gap(coordinates, clusters[1])
        assert starred_gap <= 8, f"{name}: starred mark contains {starred_gap}px gap"
        assert legacy_gap >= 20, (
            f"{name}: regression fixture no longer detects old gaps"
        )
