"""Thin argparse adapter for the public manuscript lifecycle API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import ManuscriptError, ManuscriptProject, initialize_manuscript
from .results import Artifact, DoctorResult

COMMAND_ALIASES = {
    "render": "build",
    "revise": "revision",
    "package": "submission",
    "validation": "check",
}


def _relative(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def _report_artifacts(
    heading: str,
    version: str,
    project: Path,
    artifacts: tuple[Artifact, ...],
) -> None:
    print(f"{heading}: {version}")
    print("\nGenerated:")
    for artifact in artifacts:
        suffix = "/" if artifact.path.is_dir() else ""
        print(f"  {artifact.label}:")
        print(f"    {_relative(project, artifact.path)}{suffix}")


def _report_doctor(result: DoctorResult) -> int:
    print("Environment report")
    print("\nRequired dependencies:")
    for check in (item for item in result.checks if item.required):
        status = "PASS" if check.available else "MISSING"
        print(f"  {status:<7} {check.name:<24} {check.detail}")
    print("\nOptional dependencies:")
    for check in (item for item in result.checks if not item.required):
        status = (
            "MANUAL"
            if check.name == "Zotero Better BibTeX"
            else ("PASS" if check.available else "MISSING")
        )
        print(f"  {status:<7} {check.name:<24} {check.detail}")
    if not result.ready:
        missing = [
            check.name
            for check in result.checks
            if check.required and not check.available
        ]
        print("\nResult: BLOCKED")
        print("Missing required dependencies: " + ", ".join(missing))
        print(
            "No installation was attempted. Ask the user before changing any "
            "environment."
        )
        return 2
    print("\nResult: READY")
    print("All required dependencies are available; no installation was attempted.")
    return 0


def _add_project_argument(
    parser: argparse.ArgumentParser,
    default_project: Path,
) -> None:
    parser.add_argument(
        "--project",
        default=str(default_project),
        help="Project root; defaults to the copied run.py directory.",
    )


def _add_build_arguments(
    parser: argparse.ArgumentParser,
    default_project: Path,
) -> None:
    _add_project_argument(parser, default_project)
    parser.add_argument("--round", help="Optional rN or revision_N selector.")
    parser.add_argument("--engine", choices=("auto", "tectonic", "latex"))
    parser.add_argument("--keep-temp", action="store_true")


def build_parser(default_project: Path | None = None) -> argparse.ArgumentParser:
    """Create the public subcommand interface without executing workflow logic."""
    project = (default_project or Path.cwd()).expanduser().resolve()
    parser = argparse.ArgumentParser(
        description="Manage a complete LaTeX scientific-manuscript lifecycle.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check Python and LaTeX workflow tools.")
    init = commands.add_parser("init", help="Initialize initial_submission (r0).")
    _add_project_argument(init, project)
    init.add_argument("--title", required=True, help="Manuscript title.")
    init.add_argument("--journal", required=True, help="Target journal name.")
    init.add_argument(
        "--publisher",
        choices=("elsevier", "nature", "acs", "chinese"),
        required=True,
    )
    init.add_argument("--article-type", default="Research Paper")
    init.add_argument("--language", choices=("en", "zh"), default="en")
    init.add_argument("--authors", help="Existing authors.yaml to copy.")
    init.add_argument(
        "--author",
        action="append",
        help="Selected author name; repeat to preserve author order.",
    )
    init.add_argument("--bib", help="Existing references.bib to copy.")
    init.add_argument("--engine", choices=("auto", "tectonic", "latex"))
    init.add_argument("--keep-temp", action="store_true")
    build = commands.add_parser(
        "build",
        aliases=["render"],
        help="Compile the selected clean manuscript (alias: render).",
    )
    _add_build_arguments(build, project)
    revision = commands.add_parser(
        "revision",
        aliases=["revise"],
        help="Create the next adjacent revision and response source (alias: revise).",
    )
    _add_project_argument(revision, project)
    revision.add_argument("--round", help="Advanced explicit next round selector.")
    revision.add_argument("--reviews", help="Reviewer-comments Markdown file.")
    revision.add_argument("--keep-temp", action="store_true")
    submission = commands.add_parser(
        "submission",
        aliases=["package"],
        help="Build submission materials and package (alias: package).",
    )
    _add_build_arguments(submission, project)
    submission.add_argument("--allow-placeholders", action="store_true")
    all_command = commands.add_parser(
        "all",
        help="Build clean, diff, response, and submission outputs.",
    )
    _add_build_arguments(all_command, project)
    all_command.add_argument("--allow-placeholders", action="store_true")
    zotero = commands.add_parser(
        "setup-zotero",
        help="Prepare Better BibTeX Automatic Export guidance and target files.",
    )
    _add_project_argument(zotero, project)
    sync = commands.add_parser(
        "sync-bib",
        help="Manually synchronize a Better BibTeX export as a fallback.",
    )
    _add_project_argument(sync, project)
    sync.add_argument("--bib-export", help="Explicit Better BibTeX export path.")
    check = commands.add_parser(
        "check",
        aliases=["validation"],
        help="Validate manuscript citation keys (alias: validation).",
    )
    _add_project_argument(check, project)
    check.add_argument("--round", help="Optional rN or revision_N selector.")
    status = commands.add_parser("status", help="Show lifecycle state and outputs.")
    _add_project_argument(status, project)
    return parser


def execute(args: argparse.Namespace) -> int:
    """Translate parsed primitives into public API calls and formatted output."""
    command = COMMAND_ALIASES.get(args.command, args.command)
    if command == "doctor":
        return _report_doctor(ManuscriptProject(Path.cwd()).doctor())
    project = Path(args.project).expanduser().resolve()
    if command == "init":
        initialized = initialize_manuscript(
            path=project,
            title=args.title,
            journal=args.journal,
            publisher=args.publisher,
            language=args.language,
            authors=args.authors,
            bib=args.bib,
            selected_authors=args.author,
            article_type=args.article_type,
            engine=args.engine or "auto",
            keep_temp=args.keep_temp,
        )
        _report_artifacts(
            "Project initialized",
            initialized.version,
            initialized.project,
            initialized.artifacts,
        )
        if initialized.authors_need_review:
            print("\nACTION REQUIRED: replace references/authors.yaml.")
        if initialized.bibliography_needs_configuration:
            print(
                "ACTION REQUIRED: configure Better BibTeX Automatic Export using "
                "references/zotero_setup.md, or maintain references/references.bib "
                "manually."
            )
        return 0
    manuscript = ManuscriptProject(
        project,
        engine=getattr(args, "engine", None) or "auto",
    )
    if command == "status":
        status = manuscript.status()
        print(f"Project: {status.project.name}")
        print(f"Current version: {status.version} (r{status.round_number})")
        print(f"Parent: {status.parent or 'none'}")
        print(f"Authors: {', '.join(status.authors)}")
        print(f"Publisher: {status.publisher}")
        print(f"Journal: {status.journal}")
        print("Generated:")
        if status.artifacts:
            for artifact in status.artifacts:
                print(f"  {_relative(status.project, artifact.path)}")
        else:
            print("  none")
        return 0
    if command == "setup-zotero":
        zotero = manuscript.setup_zotero()
        _report_artifacts(
            "Zotero export target prepared",
            "manual setup required",
            zotero.project,
            zotero.artifacts,
        )
        print("\nNo Zotero settings were changed.")
        print("Next: in Zotero Better BibTeX, create an Automatic Export using")
        print("  Format: Better BibTeX")
        print(f"  Path: {zotero.artifacts[0].path.resolve()}")
        print("  Keep updated: Enabled")
        return 0
    if command == "sync-bib":
        synchronized = manuscript.sync_bib(args.bib_export)
        _report_artifacts(
            "Bibliography synchronized",
            f"{len(synchronized.artifacts)} shared file(s)",
            synchronized.project,
            synchronized.artifacts,
        )
        return 0
    if command == "revision":
        revision = manuscript.start_revision(
            args.reviews,
            round=args.round,
            keep_temp=args.keep_temp,
        )
        print(f"Revision created: {revision.version}")
        print(f"Parent: {revision.parent}")
        print("\nGenerated:")
        for artifact in revision.artifacts:
            print(f"  {artifact.label}: {_relative(revision.project, artifact.path)}")
        return 0
    if command == "check":
        checked = manuscript.check(args.round)
        if not checked.passed:
            print(f"Citation check failed: {checked.version}")
            for key in checked.missing_citations:
                print(f"Missing citation key {key}")
            print(
                "Run Zotero Better BibTeX Automatic Export or use the manual "
                "sync-bib fallback, then run check again."
            )
            return 1
        print(f"Citation check passed: {checked.version}")
        print("All manuscript citation keys exist in references/references.bib.")
        return 0
    if command == "build":
        built = manuscript.build(args.round, keep_temp=args.keep_temp)
        _report_artifacts(
            "Build completed", built.version, built.project, built.artifacts
        )
        return 0
    if command in {"submission", "all"}:
        if command == "submission":
            submission = manuscript.prepare_submission(
                args.round,
                allow_placeholders=args.allow_placeholders,
                keep_temp=args.keep_temp,
            )
        else:
            submission = manuscript.build_all(
                args.round,
                allow_placeholders=args.allow_placeholders,
                keep_temp=args.keep_temp,
            )
        _report_artifacts(
            "Submission completed",
            submission.version,
            submission.project,
            submission.artifacts,
        )
        return 0
    raise ManuscriptError(f"Unsupported command: {args.command}")


def main(
    argv: list[str] | None = None,
    *,
    default_project: Path | None = None,
) -> int:
    """Parse command-line arguments and return a stable process status."""
    args = build_parser(default_project).parse_args(argv)
    try:
        return execute(args)
    except ManuscriptError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
