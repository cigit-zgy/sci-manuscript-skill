"""Transactional repair of broken revision numbering."""
from __future__ import annotations
from pathlib import Path
import shutil
from ..domain.manuscript import load_metadata, render_metadata, ManuscriptMetadata
from ..domain.revision import round_directory_name
from ..exceptions import WorkflowError
from ..infrastructure.filesystem import actual_round_directory, normalize_project, scan_round_directories, project_state
from ..infrastructure.hashing import source_hashes
from ..infrastructure.transactions import FilesystemTransaction
from ..results import ReindexResult

def plan_reindex(project: str | Path) -> ReindexResult:
    root = normalize_project(project)
    numbers = scan_round_directories(root)
    renames: list[tuple[str, str]] = []
    for index, number in enumerate(numbers):
        source = actual_round_directory(root, number).name
        target = round_directory_name(index)
        if source != target:
            renames.append((source, target))
    return ReindexResult(root, False, tuple(renames), status="planned")

def execute_reindex(project: str | Path, *, fault_after: int | None = None) -> ReindexResult:
    root = normalize_project(project)
    plan = plan_reindex(root)
    if not plan.renames:
        return ReindexResult(root, False, (), status="already_ordered")
    numbers = scan_round_directories(root)
    source_dirs = [actual_round_directory(root, n) for n in numbers]
    protected_before = {src.name: source_hashes(src) for src in source_dirs}
    (root / "tmp").mkdir(exist_ok=True)
    stage_root = root / "tmp" / "reindex_stage"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir()
    invalidated: list[str] = []
    with FilesystemTransaction(root) as tx:
        staged: list[Path] = []
        operations = 0
        for idx, source in enumerate(source_dirs):
            staged_path = stage_root / f"{idx:02d}_{source.name}"
            tx.move(source, staged_path)
            staged.append(staged_path)
            operations += 1
            if fault_after == operations:
                raise OSError("Injected reindex failure")
        for idx, staged_path in enumerate(staged):
            target = root / round_directory_name(idx)
            tx.move(staged_path, target)
            operations += 1
            if fault_after == operations:
                raise OSError("Injected reindex failure")
            if idx > 0:
                path = target / "manuscript.yaml"
                old = load_metadata(path)
                tx.write_text(path, render_metadata(ManuscriptMetadata(old.title, old.journal, old.publisher, old.language, old.article_type, idx, idx - 1, old.format_version)))
            output = target / "output"
            if output.is_dir():
                for item in output.glob("*.pdf"):
                    invalidated.append(item.relative_to(root).as_posix())
                    tx.remove(item)
            package = target / "submission" / "package"
            if package.is_dir():
                invalidated.append(package.relative_to(root).as_posix())
                tx.remove(package)
        after_state = project_state(root)
        after_state.chain.require_gap_free()
        for idx, source in enumerate(source_dirs):
            current = source_hashes(root / round_directory_name(idx))
            before = protected_before[source.name]
            for key, digest in before.items():
                if key == "manuscript.yaml":
                    continue
                if current.get(key) != digest:
                    raise WorkflowError(f"Protected source changed during reindex: {source.name}/{key}")
        tx.commit()
    shutil.rmtree(stage_root, ignore_errors=True)
    return ReindexResult(root, True, plan.renames, tuple(sorted(invalidated)), "reindexed")
