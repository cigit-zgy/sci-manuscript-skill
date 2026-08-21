"""Thin argparse adapter for the public manuscript lifecycle API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._runtime.rounds import parse_round, round_directory_name, round_name
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
    init = commands.add_parser("init", help="Initialize initial_submission (r00).")
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
        help="Create the next adjacent revision after confirmation (alias: revise).",
    )
    _add_project_argument(revision, project)
    revision.add_argument("--round", help="Advanced explicit next round selector.")
    revision.add_argument("--reviews", help="Reviewer-comments Markdown file.")
    revision.add_argument("--keep-temp", action="store_true")
    revision.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (non-interactive use).",
    )
    rollback = commands.add_parser(
        "rollback",
        help="Safely remove an unchanged accidental latest revision.",
    )
    _add_project_argument(rollback, project)
    rollback.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (non-interactive use).",
    )
    reindex = commands.add_parser(
        "reindex",
        help="Repair and renumber a broken revision sequence.",
    )
    _add_project_argument(reindex, project)
    reindex.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (non-interactive use).",
    )
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
    upgrade = commands.add_parser(
        "upgrade-project",
        help="Safely migrate recognized generated project infrastructure.",
    )
    _add_project_argument(upgrade, project)
    return parser


def _print_revision_chain(
    diagnostics: object,
) -> None:
    from .results import ChainDiagnosticsResult

    if not isinstance(diagnostics, ChainDiagnosticsResult):
        raise ManuscriptError("Invalid chain diagnostics.")
    if diagnostics.broken:
        print("Revision chain: BROKEN")
        print("\nDetected:")
        for name, label in diagnostics.versions:
            print(f"{name} ({label})")
        if diagnostics.missing:
            print("\nMissing:")
            for name in diagnostics.missing:
                print(name)
        print("\nSuggested command:")
        print("python -m sci_manuscript reindex")
        return
    print("Revision chain:")
    print()
    for index, (name, label) in enumerate(diagnostics.versions):
        if index == 0:
            print(f"{name} ({label})")
        else:
            indent = "    " * index
            marker = " [current]" if name == diagnostics.current else ""
            print(f"{indent}└── {name} ({label}){marker}")


def _confirm(prompt: str, yes: bool) -> bool:
    """Return whether the user explicitly confirmed a destructive action."""
    if yes:
        return True
    answer = input(prompt).strip().lower()
    return answer in {"y", "yes"}


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
        manuscript_for_status = ManuscriptProject(project)
        diagnostics = manuscript_for_status.chain_diagnostics()
        _print_revision_chain(diagnostics)
        if diagnostics.broken:
            return 0
        print()
        status = manuscript_for_status.status()
        print(f"Project: {status.project.name}")
        print(f"Current version: {status.version} ({round_name(status.round_number)})")
        print(f"Parent: {status.parent or 'none'}")
        print(f"Authors: {', '.join(status.authors)}")
        print(f"Publisher: {status.publisher}")
        print(f"Journal: {status.journal}")
        print(f"Project format: {status.project_format_version}")
        print("Generated:")
        if status.artifacts:
            for artifact in status.artifacts:
                print(f"  {_relative(status.project, artifact.path)}")
        else:
            print("  none")
        return 0
    if command == "upgrade-project":
        upgraded = manuscript.upgrade_project()
        print(f"Project upgrade: {upgraded.status.replace('_', ' ')}")
        print(f"Format: {upgraded.from_format} -> {upgraded.to_format}")
        print("Generated:")
        if upgraded.artifacts:
            for artifact in upgraded.artifacts:
                print(
                    f"  {artifact.label}: {_relative(upgraded.project, artifact.path)}"
                )
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
        latest = manuscript.status()
        target = parse_round(args.round, latest.round_number + 1)
        if target is None:
            raise ManuscriptError("Cannot determine the next revision round.")
        new_name = round_directory_name(target)
        print(f"Current revision: {latest.version} ({round_name(latest.round_number)})")
        print(f"New revision:     {new_name} ({round_name(target)})")
        print(f"Parent:           {latest.version} ({round_name(latest.round_number)})")
        if not _confirm(f"\nCreate {new_name}? [y/N]: ", args.yes):
            print("Cancelled.")
            return 0
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
    if command == "rollback":
        rollback_plan = manuscript.rollback_plan()
        print(f"Latest revision: {rollback_plan.version}")
        print(f"Parent:          {rollback_plan.parent}")
        if rollback_plan.changed_files:
            print("\nRollback refused.")
            print("User modifications detected:")
            for name in rollback_plan.changed_files:
                print(f"  {name}")
            print("\nNo files were removed.")
            return 1
        print("\nNo user source modifications detected.")
        if not _confirm(f"\nRemove {rollback_plan.version}? [y/N]: ", args.yes):
            print("Cancelled.")
            return 0
        manuscript.remove_latest_revision()
        print(f"Removed: {rollback_plan.version}")
        return 0
    if command == "reindex":
        plan = manuscript.reindex(apply=False)
        if not plan.renames:
            print("Revision chain is already ordered.")
            return 0
        print("Broken revision sequence detected.")
        print("\nPlanned changes:")
        for old_name, new_name in plan.renames:
            old_number = parse_round(old_name)
            new_number = parse_round(new_name)
            if old_number is None or new_number is None:
                raise ManuscriptError("Cannot map reindex round names.")
            print(
                f"  {old_name} ({round_name(old_number)}) "
                f"-> {new_name} ({round_name(new_number)})"
            )
        if plan.parent_updates:
            print("\nParent updates:")
            for version, old_label, new_label in plan.parent_updates:
                print(f"  {version}: {old_label} -> {new_label}")
        print("\nGenerated revision artifacts will be invalidated.")
        if not _confirm("\nProceed? [y/N]: ", args.yes):
            print("Cancelled.")
            return 0
        result = manuscript.reindex(apply=True)
        print("\nRevision chain reindexed successfully.")
        if result.invalidated:
            print("Generated revision artifacts were invalidated:")
            for name in result.invalidated:
                print(f"  {name}")
        print("\nRun:")
        print("  python -m sci_manuscript all")
        print("to regenerate outputs.")
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
