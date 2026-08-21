#!/usr/bin/env python3
"""Project-local wrapper for the installed sci-manuscript-skill package."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from sci_manuscript.cli import main
except ModuleNotFoundError as exc:
    if exc.name != "sci_manuscript":
        raise
    print(
        "ERROR: sci-manuscript-skill is not installed in this Python environment.",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


if __name__ == "__main__":
    raise SystemExit(main(default_project=Path(__file__).resolve().parent))
