"""Zotero guidance, bibliography validation, and CLI compatibility tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from test_core import _config

from sci_manuscript import cli as lifecycle_run
from sci_manuscript._runtime import workspace


def test_init_creates_shared_bibliography_and_zotero_guide() -> None:
    """Initialization prepares one export target and a non-invasive setup guide."""
    with tempfile.TemporaryDirectory() as temp:
        project = Path(temp) / "project"
        workspace.initialize_project(_config(project))
        references = project / "references"
        bibliography = references / "references.bib"
        guide = references / "zotero_setup.md"

        assert bibliography.is_file()
        assert guide.is_file()
        text = guide.read_text(encoding="utf-8")
        assert "Better BibTeX" in text
        assert "Keep updated" in text
        assert "references/references.bib" in text
        assert "does not open Zotero" in text


def test_setup_zotero_recreates_missing_files_without_overwriting_guide() -> None:
    """The explicit setup command is idempotent and preserves user edits."""
    with tempfile.TemporaryDirectory() as temp:
        project = Path(temp) / "project"
        workspace.initialize_project(_config(project))
        references = project / "references"
        bibliography = references / "references.bib"
        guide = references / "zotero_setup.md"
        bibliography.unlink()
        guide.write_text("USER EDIT\n", encoding="utf-8")

        created_bibliography, retained_guide = workspace.setup_zotero(project)

        assert created_bibliography.is_file()
        assert created_bibliography.read_text(encoding="utf-8") == ""
        assert retained_guide.read_text(encoding="utf-8") == "USER EDIT\n"


def test_revision_never_copies_shared_references() -> None:
    """Adjacent revisions inherit editable state but not shared references."""
    with tempfile.TemporaryDirectory() as temp:
        project = Path(temp) / "project"
        r0 = workspace.initialize_project(_config(project))
        submission_note = r0.round_dir(0) / "submission" / "author-note.txt"
        submission_note.write_text("retain me\n", encoding="utf-8")
        response_attachment = r0.round_dir(0) / "response" / "editor-note.txt"
        response_attachment.parent.mkdir()
        response_attachment.write_text("retain attachment\n", encoding="utf-8")
        with workspace.temporary_run(project, keep=False) as run_dir:
            r1 = workspace.start_revision(r0, 1, run_dir)

        assert (r1.round_dir(1) / "submission" / "author-note.txt").is_file()
        assert (r1.round_dir(1) / "response" / "editor-note.txt").is_file()
        assert not (r1.round_dir(1) / "references").exists()
        assert (project / "references" / "references.bib").is_file()
        assert (project / "references" / "zotero_setup.md").is_file()


def test_citation_check_reports_only_missing_keys() -> None:
    """Citation validation ignores comments and accepts shared BibTeX keys."""
    with tempfile.TemporaryDirectory() as temp:
        project = Path(temp) / "project"
        config = workspace.initialize_project(_config(project))
        section = config.round_dir(0) / "sections" / "01_introduction.tex"
        section.write_text(
            "\\section{Introduction}\n"
            "\\citep[see][]{replace_me,missing2026}\n"
            "% \\cite{commented2026}\n",
            encoding="utf-8",
        )

        assert workspace.check_citations(config, 0) == ("missing2026",)


def test_sync_bib_remains_an_atomic_manual_fallback() -> None:
    """Manual synchronization still replaces the single shared database."""
    with tempfile.TemporaryDirectory() as temp:
        project = Path(temp) / "project"
        workspace.initialize_project(_config(project))
        export = Path(temp) / "better-bibtex.bib"
        export.write_text("@article{manual2026, title={Manual}}\n", encoding="utf-8")

        targets = workspace.sync_bibliography(project, export)

        assert targets == (project / "references" / "references.bib",)
        assert targets[0].read_text(encoding="utf-8") == export.read_text(
            encoding="utf-8"
        )


def test_cli_help_exposes_new_commands_and_compatibility_aliases() -> None:
    """The public parser retains canonical commands and explicit aliases."""
    parser = lifecycle_run.build_parser()
    expected = {
        "render": "render",
        "revise": "revise",
        "package": "package",
        "validation": "validation",
        "setup-zotero": "setup-zotero",
        "check": "check",
    }
    for arguments, parsed in expected.items():
        assert parser.parse_args([arguments]).command == parsed
