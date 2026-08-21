#!/usr/bin/env python3
"""Audit a built wheel for release-critical runtime resources."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

REQUIRED = frozenset(
    {
        "sci_manuscript/__init__.py",
        "sci_manuscript/__main__.py",
        "sci_manuscript/api.py",
        "sci_manuscript/cli.py",
        "sci_manuscript/py.typed",
        "sci_manuscript/_runtime/workspace.py",
        "sci_manuscript/_runtime/compile.py",
        "sci_manuscript/_runtime/diff.py",
        "sci_manuscript/_runtime/metadata.py",
        "sci_manuscript/_runtime/response.py",
        "sci_manuscript/resources/authors.yaml",
        "sci_manuscript/resources/revision_style.tex",
        "sci_manuscript/resources/project_run.py",
        "sci_manuscript/resources/manuscript/preamble.tex",
        "sci_manuscript/resources/response/response_en.tex",
        "sci_manuscript/resources/response/response_zh.tex",
        "sci_manuscript/resources/submission/cover_letter_en.tex",
        "sci_manuscript/resources/submission/highlights.tex",
        "sci_manuscript/resources/journal_templates/elsevier/elsarticle.cls",
        "sci_manuscript/resources/journal_templates/elsevier/elsarticle-num.bst",
        "sci_manuscript/resources/journal_templates/nature/sn-jnl.cls",
        "sci_manuscript/resources/journal_templates/nature/sn-nature.bst",
        "sci_manuscript/resources/journal_templates/acs/achemso.cls",
        "sci_manuscript/resources/journal_templates/acs/achemso.dtx",
        "sci_manuscript/resources/journal_templates/acs/LICENSE.md",
        "sci_manuscript/resources/journal_templates/chinese/kxtbcas.cls",
    }
)


def verify_wheel(path: Path) -> None:
    """Raise a concise error if a wheel is incomplete or contaminated."""
    source_root = Path(__file__).resolve().parents[1] / "src" / "sci_manuscript"
    expected_source = {
        "sci_manuscript/" + source.relative_to(source_root).as_posix()
        for source in source_root.rglob("*")
        if source.is_file()
        if "__pycache__" not in source.relative_to(source_root).parts
        if source.suffix not in {".pyc", ".pyo"}
        if source.name != ".DS_Store"
    }
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = sorted((REQUIRED | expected_source) - names)
        if missing:
            raise RuntimeError("Wheel is missing:\n  " + "\n  ".join(missing))
        forbidden = sorted(
            name
            for name in names
            if "__pycache__" in name
            or name.endswith((".pyc", ".pdf", ".aux", ".log"))
            or name.startswith(("tests/", "tmp/", ".git/"))
        )
        if forbidden:
            raise RuntimeError(
                "Wheel contains forbidden files:\n  " + "\n  ".join(forbidden)
            )
        notices = [
            name
            for name in names
            if name.endswith("licenses/THIRD_PARTY_NOTICES.md")
        ]
        if len(notices) != 1:
            raise RuntimeError("Wheel must contain exactly one third-party notice.")
        private_paths = {"/Users/wenv/", str(Path(__file__).resolve().parents[1])}
        for name in sorted(names):
            if not name.endswith((".py", ".md", ".tex", ".yaml", ".txt")):
                continue
            try:
                text = archive.read(name).decode("utf-8")
            except UnicodeDecodeError:
                continue
            if any(private_path in text for private_path in private_paths):
                raise RuntimeError(f"Wheel contains a private absolute path: {name}")


def main() -> int:
    """Parse one wheel path and report a successful audit."""
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    verify_wheel(args.wheel)
    print(f"Wheel audit passed: {args.wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
