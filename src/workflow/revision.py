"""Adjacent revision creation and response scaffold workflow."""
from __future__ import annotations
from pathlib import Path
import shutil
from ..domain.manuscript import ManuscriptMetadata, dump_metadata
from ..domain.review import parse_reviews
from ..domain.revision import round_directory_name
from ..exceptions import WorkflowError
from ..infrastructure.filesystem import actual_round_directory
from ..infrastructure.manifest import write_creation_manifest
from ..results import Artifact, RevisionResult
from .common import COPY_DIRS, metadata_for_round, require_gap_free

def _response_template(review_file: Path | None) -> str:
    preamble = (
        "\\documentclass[11pt]{article}\n"
        "\\usepackage[margin=1in]{geometry}\n"
        "\\newcommand{\\ResponsePending}[1]{\\textbf{Response pending:} #1}\n"
        "\\begin{document}\n"
        "\\section*{Response to reviewers}\n"
    )
    if review_file is None:
        body = "\\ResponsePending{reviewer comments}\n"
    else:
        comments = parse_reviews(review_file)
        parts: list[str] = []
        for comment in comments:
            safe = comment.text.replace("%", "\\%")
            parts.extend([
                f"\\subsection*{{{comment.owner}-{comment.number}}}",
                f"\\textit{{Reviewer comment:}} {safe}",
                f"\\ResponsePending{{{comment.owner}-{comment.number}}}",
            ])
        body = "\n\n".join(parts) + "\n"
    return preamble + body + "\\end{document}\n"

def start_revision(
    project: str | Path,
    reviews: str | Path | None = None,
    requested_round: int | None = None,
) -> RevisionResult:
    state = require_gap_free(project)
    target_number = state.chain.next_round()
    if requested_round is not None and requested_round != target_number:
        raise WorkflowError(f"Revision must be adjacent; expected r{target_number:02d}.")
    parent_dir = actual_round_directory(state.root, state.chain.latest)
    target_dir = state.root / round_directory_name(target_number)
    if target_dir.exists():
        raise WorkflowError(f"Target revision already exists: {target_dir}")
    target_dir.mkdir()
    try:
        for dirname in COPY_DIRS:
            source = parent_dir / dirname
            if source.exists():
                shutil.copytree(source, target_dir / dirname, dirs_exist_ok=True)
        package = target_dir / "submission" / "package"
        if package.exists():
            shutil.rmtree(package)
        for dirname in ("figures", "tables", "output", "submission"):
            (target_dir / dirname).mkdir(exist_ok=True)
        parent_meta = metadata_for_round(state.root, state.chain.latest)
        metadata = ManuscriptMetadata(
            parent_meta.title,
            parent_meta.journal,
            parent_meta.publisher,
            parent_meta.language,
            parent_meta.article_type,
            target_number,
            state.chain.latest,
            parent_meta.format_version,
        )
        dump_metadata(metadata, target_dir / "manuscript.yaml")
        response_dir = target_dir / "response"
        response_dir.mkdir()
        review_path = Path(reviews).expanduser().resolve() if reviews else None
        if review_path is not None:
            if not review_path.is_file():
                raise WorkflowError(f"Reviewer comments are missing: {review_path}")
            shutil.copy2(review_path, response_dir / "reviewer_comments.md")
        response = response_dir / "response_letter.tex"
        response.write_text(_response_template(review_path), encoding="utf-8")
        write_creation_manifest(target_dir, round_directory_name(state.chain.latest))
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    return RevisionResult(state.root, round_directory_name(target_number), round_directory_name(state.chain.latest), (Artifact("Response source", response),))
