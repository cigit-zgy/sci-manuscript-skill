"""Audit wheel paths for the flattened src layout."""
from __future__ import annotations
import sys, zipfile
from pathlib import Path

def main() -> int:
    wheel=Path(sys.argv[1])
    with zipfile.ZipFile(wheel) as z:
        names=set(z.namelist())
    required={"sci_manuscript/__init__.py","sci_manuscript/api/project.py","sci_manuscript/workflow/reindex.py","sci_manuscript/resources/revision_contract.yaml"}
    missing=required-names
    forbidden=[n for n in names if n.startswith("sci_manuscript/sci_manuscript/") or "__pycache__" in n or n.endswith((".pyc", ".pyo"))]
    if missing or forbidden:
        raise SystemExit(f"distribution audit failed: missing={sorted(missing)}, forbidden={forbidden}")
    print("distribution audit passed")
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
