"""Stable public project API."""
from __future__ import annotations
from pathlib import Path
from ..results import BuildResult, InitializationResult, ReindexResult, RevisionResult, RollbackResult, StatusResult, SubmissionResult
from ..workflow import bibliography, build, initialize, project as project_workflow, reindex, revision, rollback, submission, upgrade

class ManuscriptProject:
    def __init__(self, path: str | Path, *, engine: str = "auto") -> None:
        self.path = Path(path).expanduser().resolve()
        self.engine = engine

    def status(self) -> StatusResult:
        return project_workflow.status(self.path)

    def build(self, round: int | None = None) -> BuildResult:
        return build.build_manuscript(self.path, round, self.engine)

    def start_revision(self, reviews: str | Path | None = None, round: int | None = None) -> RevisionResult:
        return revision.start_revision(self.path, reviews, round)

    def rollback_plan(self) -> RollbackResult:
        return rollback.inspect_rollback(self.path)

    def remove_latest_revision(self) -> RollbackResult:
        return rollback.rollback_latest(self.path)

    def reindex_plan(self) -> ReindexResult:
        return reindex.plan_reindex(self.path)

    def reindex(self) -> ReindexResult:
        return reindex.execute_reindex(self.path)

    def prepare_submission(self, round: int | None = None, *, allow_placeholders: bool = False) -> SubmissionResult:
        return submission.prepare_submission(self.path, round, self.engine, allow_placeholders)

    def setup_zotero(self) -> tuple[Path, Path]:
        return bibliography.setup_zotero(self.path)

    def sync_bib(self, export: str | Path) -> Path:
        return bibliography.sync_bibliography(self.path, export)

    def upgrade_project(self) -> ReindexResult:
        return upgrade.upgrade_project(self.path)

def initialize_manuscript(path: str | Path, title: str, journal: str, publisher: str, language: str = "en", article_type: str = "Research Paper") -> InitializationResult:
    return initialize.initialize_manuscript(path, title, journal, publisher, language, article_type)
