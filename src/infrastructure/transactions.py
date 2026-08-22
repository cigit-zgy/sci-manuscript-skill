"""Filesystem transaction with explicit rollback journal."""
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path

class FilesystemTransaction:
    """Journaled project-local filesystem mutation."""
    def __init__(self, root: Path) -> None:
        self.root = root
        self.stage = Path(tempfile.mkdtemp(prefix="txn_", dir=root / "tmp"))
        self._undo: list[tuple[str, Path, Path | bytes | None]] = []
        self._committed = False

    def __enter__(self) -> "FilesystemTransaction":
        return self

    def move(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        self._undo.append(("move", target, source))

    def write_text(self, target: Path, text: str) -> None:
        previous = target.read_bytes() if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        self._undo.append(("write", target, previous))

    def remove(self, target: Path) -> None:
        backup = self.stage / f"backup_{len(self._undo):04d}"
        shutil.move(str(target), str(backup))
        self._undo.append(("remove", backup, target))

    def commit(self) -> None:
        self._committed = True

    def rollback(self) -> None:
        for kind, first, second in reversed(self._undo):
            if kind == "move":
                source = first
                target = second
                assert isinstance(target, Path)
                if source.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(target))
            elif kind == "write":
                target = first
                if second is None:
                    target.unlink(missing_ok=True)
                else:
                    assert isinstance(second, bytes)
                    target.write_bytes(second)
            elif kind == "remove":
                backup = first
                target = second
                assert isinstance(target, Path)
                if backup.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(backup), str(target))

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc is not None or not self._committed:
            self.rollback()
        shutil.rmtree(self.stage, ignore_errors=True)
