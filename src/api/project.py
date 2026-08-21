"""Stable public API for the scientific-manuscript lifecycle."""

from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ..exceptions import ManuscriptError
from ..results import (
    BibliographySyncResult,
    BuildResult,
    ChainDiagnosticsResult,
    CheckResult,
    DependencyCheck,
    DoctorResult,
    InitializationResult,
    ReindexResult,
    RevisionResult,
    RollbackResult,
    StatusResult,
    SubmissionResult,
    UpgradeResult,
    ZoteroSetupResult,
)


def _run(operation: str, *args: object, **kwargs: object) -> object:
    """Dispatch one operation into the workflow layer."""
    try:
        from .. import workflow

        modules = {
            "initialize_manuscript": "initialize",
            "build": "build",
            "check": "project",
            "start_revision": "revision",
            "prepare_submission": "submission",
            "status": "project",
            "setup_zotero": "project",
            "sync_bib": "project",
            "upgrade_project": "initialize",
            "rollback_inspect": "rollback",
            "remove_revision": "rollback",
            "reindex_plan": "rollback",
            "reindex_execute": "rollback",
            "chain_diagnostics": "project",
        }
        module = getattr(workflow, modules[operation])
        action = getattr(module, operation)
        return action(*args, **kwargs)
    except (RuntimeError, OSError) as exc:
        if isinstance(exc, ManuscriptError):
            raise
        raise ManuscriptError(str(exc)) from exc


def _package_version(distribution: str) -> tuple[bool, str]:
    try:
        return True, importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False, "not installed"


def _tool_version(name: str) -> tuple[bool, str]:
    executable = shutil.which(name)
    if executable is None:
        return False, "not found"
    version_flag = "-v" if name in {"pdftotext", "pdftoppm"} else "--version"
    result = subprocess.run(
        [executable, version_flag],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = result.stdout.strip() or result.stderr.strip()
    return True, output.splitlines()[0] if output else executable

def inspect_environment() -> DoctorResult:
    """Inspect required tools without importing runtime dependencies or changing them."""
    yaml_ok, yaml_version = _package_version("PyYAML")
    tool_names = (
        "tectonic",
        "latexmk",
        "pdflatex",
        "xelatex",
        "latexdiff",
        "pdftotext",
        "pdftoppm",
        "bibtex",
        "biber",
        "ruff",
        "mypy",
    )
    tools = {name: _tool_version(name) for name in tool_names}
    tectonic_ok = tools["tectonic"][0]
    tex_live_ok = tools["latexmk"][0] and (tools["pdflatex"][0] or tools["xelatex"][0])
    latex_ok = tectonic_ok or tex_live_ok
    if tectonic_ok:
        latex_detail = tools["tectonic"][1]
    elif tex_live_ok:
        driver = "XeLaTeX" if tools["xelatex"][0] else "pdfLaTeX"
        latex_detail = f"latexmk with {driver}"
    else:
        latex_detail = "not found"
    poppler_ok = tools["pdftotext"][0] and tools["pdftoppm"][0]
    bibliography_ok = tectonic_ok or tools["bibtex"][0] or tools["biber"][0]
    if tectonic_ok:
        bibliography_detail = "Tectonic integrated BibTeX processing"
    elif tools["bibtex"][0]:
        bibliography_detail = tools["bibtex"][1]
    elif tools["biber"][0]:
        bibliography_detail = tools["biber"][1]
    else:
        bibliography_detail = "not found"
    checks = (
        DependencyCheck(
            "Python >= 3.11",
            sys.version_info >= (3, 11),
            sys.version.split()[0],
            True,
        ),
        DependencyCheck("PyYAML", yaml_ok, yaml_version, True),
        DependencyCheck("LaTeX engine", latex_ok, latex_detail, True),
        DependencyCheck("latexdiff", *tools["latexdiff"], True),
        DependencyCheck(
            "Poppler PDF tools",
            poppler_ok,
            f"pdftotext: {tools['pdftotext'][1]}; pdftoppm: {tools['pdftoppm'][1]}",
            True,
        ),
        DependencyCheck(
            "BibTeX/Biber backend",
            bibliography_ok,
            bibliography_detail,
            True,
        ),
        DependencyCheck(
            "Zotero Better BibTeX",
            False,
            "manual integration; the skill never controls Zotero",
            False,
        ),
        DependencyCheck("Ruff", *tools["ruff"], False),
        DependencyCheck("Mypy", *tools["mypy"], False),
    )
    ready = all(check.available for check in checks if check.required)
    return DoctorResult(ready=ready, checks=checks)

def initialize_manuscript(
    path: str | Path,
    title: str,
    journal: str,
    publisher: str,
    language: str = "en",
    authors: str | Path | None = None,
    bib: str | Path | None = None,
    *,
    selected_authors: Sequence[str] | None = None,
    article_type: str = "Research Paper",
    engine: str = "auto",
    keep_temp: bool = False,
) -> InitializationResult:
    """Initialize and compile a manuscript project from explicit user metadata."""
    result = _run(
        "initialize_manuscript",
        path=path,
        title=title,
        journal=journal,
        publisher=publisher,
        language=language,
        authors=authors,
        bib=bib,
        selected_authors=selected_authors,
        article_type=article_type,
        engine=engine,
        keep_temp=keep_temp,
    )
    if not isinstance(result, InitializationResult):
        raise ManuscriptError("Initialization returned an invalid result.")
    return result

class ManuscriptProject:
    """High-level lifecycle operations bound to one manuscript project root."""

    def __init__(self, path: str | Path, *, engine: str = "auto") -> None:
        self.path = Path(path).expanduser().resolve()
        self.engine = engine

    def doctor(self) -> DoctorResult:
        """Inspect workflow dependencies without modifying the environment."""
        return inspect_environment()

    def status(self) -> StatusResult:
        """Return current ancestry, metadata, and published artifact paths."""
        result = _run("status", self.path)
        if not isinstance(result, StatusResult):
            raise ManuscriptError("Status inspection returned an invalid result.")
        return result

    def build(
        self,
        round: str | int | None = None,
        *,
        keep_temp: bool = False,
    ) -> BuildResult:
        """Compile the selected clean manuscript without editing its sources."""
        result = _run("build", self.path, round, self.engine, keep_temp)
        if not isinstance(result, BuildResult):
            raise ManuscriptError("Build returned an invalid result.")
        return result

    def check(self, round: str | int | None = None) -> CheckResult:
        """Validate that manuscript citation keys exist in the shared BibTeX file."""
        result = _run("check", self.path, round)
        if not isinstance(result, CheckResult):
            raise ManuscriptError("Citation check returned an invalid result.")
        return result

    def start_revision(
        self,
        reviews: str | Path | None = None,
        *,
        round: str | int | None = None,
        keep_temp: bool = False,
    ) -> RevisionResult:
        """Create only the next workspace; no manuscript content is authored or edited."""
        result = _run(
            "start_revision",
            self.path,
            reviews,
            round,
            keep_temp,
        )
        if not isinstance(result, RevisionResult):
            raise ManuscriptError("Revision creation returned an invalid result.")
        return result

    def chain_diagnostics(self) -> ChainDiagnosticsResult:
        """Inspect the round sequence even when the chain is broken."""
        result = _run("chain_diagnostics", self.path)
        if not isinstance(result, ChainDiagnosticsResult):
            raise ManuscriptError("Chain inspection returned an invalid result.")
        return result

    def rollback_plan(self) -> RollbackResult:
        """Compare the latest revision against its parent at the user-source layer."""
        result = _run("rollback_inspect", self.path)
        if not isinstance(result, RollbackResult):
            raise ManuscriptError("Rollback inspection returned an invalid result.")
        return result

    def remove_latest_revision(self) -> None:
        """Delete the latest revision directory after explicit confirmation."""
        _run("remove_revision", self.path)

    def reindex(self, apply: bool = False) -> ReindexResult:
        """Plan (apply=False) or transactionally execute a round-sequence reindex."""
        operation = "reindex_execute" if apply else "reindex_plan"
        result = _run(operation, self.path)
        if not isinstance(result, ReindexResult):
            raise ManuscriptError("Reindex returned an invalid result.")
        return result

    def prepare_submission(
        self,
        round: str | int | None = None,
        *,
        allow_placeholders: bool = False,
        keep_temp: bool = False,
    ) -> SubmissionResult:
        """Build every enabled final artifact for the selected version."""
        result = _run(
            "prepare_submission",
            self.path,
            round,
            self.engine,
            allow_placeholders,
            keep_temp,
        )
        if not isinstance(result, SubmissionResult):
            raise ManuscriptError("Submission build returned an invalid result.")
        return result

    def build_all(
        self,
        round: str | int | None = None,
        *,
        allow_placeholders: bool = False,
        keep_temp: bool = False,
    ) -> SubmissionResult:
        """Build clean, marked, response, and submission artifacts when applicable."""
        return self.prepare_submission(
            round,
            allow_placeholders=allow_placeholders,
            keep_temp=keep_temp,
        )

    def setup_zotero(self) -> ZoteroSetupResult:
        """Prepare project files for user-configured Better BibTeX export."""
        result = _run("setup_zotero", self.path)
        if not isinstance(result, ZoteroSetupResult):
            raise ManuscriptError("Zotero setup returned an invalid result.")
        return result

    def upgrade_project(self) -> UpgradeResult:
        """Migrate only recognized generated infrastructure without editing content."""
        result = _run("upgrade_project", self.path)
        if not isinstance(result, UpgradeResult):
            raise ManuscriptError("Project upgrade returned an invalid result.")
        return result

    def sync_bib(self, export: str | Path | None = None) -> BibliographySyncResult:
        """Explicitly synchronize a Better BibTeX export into shared references."""
        result = _run("sync_bib", self.path, export)
        if not isinstance(result, BibliographySyncResult):
            raise ManuscriptError("Bibliography sync returned an invalid result.")
        return result
