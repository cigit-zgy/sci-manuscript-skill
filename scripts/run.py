#!/usr/bin/env python3
"""Compatibility entry point for an installed development checkout."""

from __future__ import annotations

from pathlib import Path

from sci_manuscript.cli import main

if __name__ == "__main__":
    raise SystemExit(main(default_project=Path.cwd()))
