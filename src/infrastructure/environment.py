"""Environment discovery without mutation."""
from __future__ import annotations
import shutil

def tool_available(name: str) -> bool:
    return shutil.which(name) is not None
