"""Revision creation manifest."""
from __future__ import annotations
from pathlib import Path
import yaml
from .hashing import source_hashes

MANIFEST = ".revision_creation.yaml"

def write_creation_manifest(round_dir: Path, parent: str) -> Path:
    hashes = source_hashes(round_dir)
    hashes.pop("manuscript.yaml", None)
    hashes.pop("response/response_letter.tex", None)
    target = round_dir / MANIFEST
    target.write_text(yaml.safe_dump({"parent": parent, "user_sources": hashes}, sort_keys=True), encoding="utf-8")
    return target

def load_creation_manifest(round_dir: Path) -> dict[str, object]:
    return yaml.safe_load((round_dir / MANIFEST).read_text(encoding="utf-8"))
