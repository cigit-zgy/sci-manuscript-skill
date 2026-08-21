#!/usr/bin/env python3
"""Run the anonymous wheel-installed r0-to-r2 local release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sci_manuscript import ManuscriptProject, initialize_manuscript

PENDING = re.compile(r"\\ResponsePending\{([^}]+)\}")
LINE_NUMBER = re.compile(r"(?m)^[ \t]*\d+[ \t]+")


def source_hashes(project: Path) -> dict[str, str]:
    """Hash every user-controlled manuscript TeX source."""
    hashes: dict[str, str] = {}
    for version in (
        project / "initial_submission",
        *sorted(project.glob("revision_*")),
    ):
        if not version.is_dir():
            continue
        sources = [version / "manuscript.tex", version / "preamble.tex"]
        for directory in ("sections", "figures", "tables"):
            sources.extend(sorted((version / directory).rglob("*.tex")))
        for source in sources:
            if source.is_file():
                key = source.relative_to(project).as_posix()
                hashes[key] = hashlib.sha256(source.read_bytes()).hexdigest()
    return hashes


def run_wrapper(project: Path, command: str) -> str:
    """Run the generated project wrapper with the installed interpreter."""
    result = subprocess.run(
        [sys.executable, str(project / "run.py"), command],
        cwd=project,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Project wrapper failed ({command}):\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def complete_response(path: Path) -> None:
    """Apply explicit anonymous fixture responses to every pending ID."""
    text = path.read_text(encoding="utf-8")
    completed = PENDING.sub(
        lambda match: (
            "Thank you. The explicit anonymous fixture change for "
            f"{match.group(1)} was applied."
        ),
        text,
    )
    path.write_text(completed, encoding="utf-8")


def add_explicit_fixture_edit(version: Path, review_id: str, text: str) -> None:
    """Append one test-only edit explicitly authorized by this release fixture."""
    introduction = version / "sections" / "01_introduction.tex"
    introduction.write_text(
        introduction.read_text(encoding="utf-8")
        + f"\n\\review{{{review_id}}}{{{text}}}\n",
        encoding="utf-8",
    )


def assert_artifacts(project: Path, version: str) -> dict[str, str]:
    """Validate final artifacts and extract text from every user-facing PDF."""
    version_dir = project / version
    expected = {
        "clean": version_dir / "output" / "manuscript_clean.pdf",
        "marked": version_dir / "output" / "manuscript_marked.pdf",
        "response": version_dir / "output" / "response_letter.pdf",
        "cover": version_dir / "submission" / "package" / "cover_letter.pdf",
        "highlights": version_dir / "submission" / "package" / "highlights.pdf",
        "graphical": (
            version_dir / "submission" / "package" / "graphical_abstract.pdf"
        ),
        "checklist": version_dir / "submission" / "package" / "checklist.md",
        "packaged_manuscript": (
            version_dir / "submission" / "package" / "manuscript.pdf"
        ),
        "packaged_marked": (
            version_dir / "submission" / "package" / "marked_manuscript.pdf"
        ),
        "packaged_response": (
            version_dir / "submission" / "package" / "response_letter.pdf"
        ),
    }
    missing = [str(path) for path in expected.values() if not path.is_file()]
    if missing:
        raise RuntimeError("Missing release artifacts:\n  " + "\n  ".join(missing))
    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        raise RuntimeError("pdftotext is required for release PDF QA.")
    extracted: dict[str, str] = {}
    for label, path in expected.items():
        if path.suffix != ".pdf":
            continue
        result = subprocess.run(
            [pdftotext, str(path), "-"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"PDF text extraction failed: {path}\n{result.stderr}")
        extracted[label] = result.stdout
    if LINE_NUMBER.search(extracted["marked"]) is None:
        raise RuntimeError("Marked PDF does not expose continuous line numbers.")
    for label in ("response", "cover", "highlights"):
        if LINE_NUMBER.search(extracted[label]) is not None:
            raise RuntimeError(f"{label} PDF unexpectedly contains manuscript lines.")
    package = version_dir / "submission" / "package"
    if not package.is_dir():
        raise RuntimeError(f"Submission package directory is missing: {package}")
    expected["package"] = package
    return {label: str(path) for label, path in expected.items()}


def scan_portability(project: Path, forbidden: tuple[str, ...]) -> None:
    """Reject source-checkout paths and deprecated bootstrap markers."""
    blocked = (*forbidden, "SCI_MANUSCRIPT_SKILL_ROOT", "%%SCI_MANUSCRIPT")
    for path in project.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".pdf", ".png"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(value and value in text for value in blocked):
            raise RuntimeError(f"Generated project contains a forbidden path: {path}")


def run_gate(workspace: Path, forbidden: tuple[str, ...]) -> dict[str, object]:
    """Execute the complete installed-distribution lifecycle and move test."""
    origin = workspace / "Origin Project 科研测试"
    moved = workspace / "Moved Project 移动后"
    if origin.exists() or moved.exists():
        raise RuntimeError(f"Release workspace must start empty: {workspace}")
    initialize_manuscript(
        path=origin,
        title="Anonymous Portable Manuscript",
        journal="Example Journal",
        publisher="elsevier",
        language="en",
        selected_authors=("Guangyao Zhao", "Hong Liu"),
        engine="tectonic",
    )
    project = ManuscriptProject(origin, engine="tectonic")
    project.build()
    rounds = (
        (
            "# Editor\n\n1. Please clarify 10% A_B, x & y, $z$, #tag, "
            "{value}, C:\\path, ~10, ^ symbol, and 中文.\n"
            "   Preserve this second paragraph.\n\n"
            "# Reviewer #1\n\n1. Please add one explicit test sentence.\n",
            "E-1",
            "The user-approved anonymous revision one sentence.",
        ),
        (
            "# Associate Editor\n\n1. Please make a second explicit change.\n\n"
            "# Reviewer #2\n\n1. Please retain the revision chain.\n",
            "AE-1",
            "The user-approved anonymous revision two sentence.",
        ),
    )
    artifacts: dict[str, dict[str, str]] = {}
    for number, (review_text, review_id, edit_text) in enumerate(rounds, 1):
        parent_hashes = source_hashes(origin)
        reviews = workspace / f"reviews_{number}.md"
        reviews.write_text(review_text, encoding="utf-8")
        result = project.start_revision(reviews)
        after_revision = source_hashes(origin)
        if any(
            after_revision.get(path) != digest for path, digest in parent_hashes.items()
        ):
            raise RuntimeError("Revision creation changed an existing parent source.")
        version = origin / result.version
        add_explicit_fixture_edit(version, review_id, edit_text)
        complete_response(version / "response" / "response_letter.tex")
        before_build = source_hashes(origin)
        project.build_all()
        if source_hashes(origin) != before_build:
            raise RuntimeError("build_all changed scientific manuscript source.")
        artifacts[result.version] = assert_artifacts(origin, result.version)

    shutil.move(str(origin), moved)
    project = ManuscriptProject(moved, engine="tectonic")
    before_move_commands = source_hashes(moved)
    run_wrapper(moved, "status")
    run_wrapper(moved, "build")
    run_wrapper(moved, "check")
    all_output = run_wrapper(moved, "all")
    if source_hashes(moved) != before_move_commands:
        raise RuntimeError("Moved-project commands changed scientific source.")
    for label in (
        "Clean manuscript",
        "Marked manuscript",
        "Response letter",
        "Cover letter",
        "Highlights",
        "Graphical abstract",
        "Submission checklist",
        "Submission package",
    ):
        if label not in all_output:
            raise RuntimeError(f"CLI all omitted artifact label: {label}")
    upgrade = project.upgrade_project()
    if upgrade.status != "already_current":
        raise RuntimeError("Current project upgrade was not a no-op.")
    scan_portability(moved, forbidden)
    if any((moved / "tmp").iterdir()):
        raise RuntimeError("Successful release lifecycle left temporary files behind.")
    artifacts["revision_2_moved"] = assert_artifacts(moved, "revision_2")
    return {
        "project": str(moved),
        "rounds": artifacts,
        "source_files": len(source_hashes(moved)),
        "tmp_empty": True,
        "upgrade": upgrade.status,
    }


def main() -> int:
    """Parse a clean workspace and print machine-readable gate evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--forbid", action="append", default=[])
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=True)
    result = run_gate(args.workspace.resolve(), tuple(args.forbid))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
