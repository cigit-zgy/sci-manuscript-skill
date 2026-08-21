#!/usr/bin/env python3
"""Bootstrap the installed public CLI from a skill source or manuscript project."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print(
        "ERROR: sci-manuscript-skill requires Python 3.11 or newer; "
        f"found {sys.version.split()[0]}.",
        file=sys.stderr,
    )
    raise SystemExit(2)

_SKILL_ROOT_HINT = Path("%%SCI_MANUSCRIPT_SKILL_ROOT%%")


def _locations() -> tuple[Path, Path]:
    entrypoint = Path(__file__).resolve()
    source_root = entrypoint.parents[1]
    if (source_root / "src" / "sci_manuscript").is_dir():
        return source_root, Path.cwd().resolve()
    configured = os.environ.get("SCI_MANUSCRIPT_SKILL_ROOT")
    skill_root = Path(configured).expanduser() if configured else _SKILL_ROOT_HINT
    resolved = skill_root.resolve()
    if not (resolved / "src" / "sci_manuscript").is_dir():
        raise RuntimeError(
            "Cannot locate sci-manuscript-skill. Set SCI_MANUSCRIPT_SKILL_ROOT "
            "to the installed skill directory."
        )
    return resolved, entrypoint.parent


try:
    _SKILL_ROOT, _DEFAULT_PROJECT = _locations()
except RuntimeError as exc:  # pragma: no cover - installation boundary
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

sys.path.insert(0, str(_SKILL_ROOT / "src"))

from sci_manuscript.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(default_project=_DEFAULT_PROJECT))
