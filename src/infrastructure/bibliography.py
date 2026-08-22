"""Bibliography filesystem primitive."""
from __future__ import annotations
from pathlib import Path
import shutil

def copy_bibliography(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target
