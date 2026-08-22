"""Stable source hashing."""
from __future__ import annotations
import hashlib
from pathlib import Path

USER_SOURCE_DIRS = ("sections", "figures", "tables", "submission")
USER_SOURCE_FILES = ("manuscript.yaml",)

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_hashes(round_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for filename in USER_SOURCE_FILES:
        path = round_dir / filename
        if path.is_file():
            result[filename] = sha256_file(path)
    for dirname in USER_SOURCE_DIRS:
        base = round_dir / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(round_dir).as_posix()
            if relative.startswith("submission/package/"):
                continue
            if path.is_file() and not path.name.startswith("."):
                result[relative] = sha256_file(path)
    response = round_dir / "response" / "response_letter.tex"
    if response.is_file():
        result[response.relative_to(round_dir).as_posix()] = sha256_file(response)
    return result
