"""Command-line adapter for :mod:`sci_manuscript.api`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .api import (
    DoctorResult,
    LifecycleResult,
    ManuscriptProject,
    StatusResult,
    doctor,
    initialize_manuscript,
)
from .errors import ManuscriptError
from .metadata import (
    PUBLISHERS,
    configure_author_library,
    configured_author_library_path,
    load_author_library,
    resolve_author_library_path,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sci-manuscript",
        description="Manage a reproducible SCI LaTeX manuscript lifecycle.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser("doctor", help="Inspect the local toolchain.")
    doctor_parser.add_argument("--language", choices=("en", "zh"))
    doctor_parser.add_argument("--publisher", choices=PUBLISHERS)
    doctor_parser.add_argument(
        "--engine", choices=("auto", "tectonic", "latex"), default="auto"
    )
    authors = commands.add_parser("authors", help="Manage the user author library.")
    author_commands = authors.add_subparsers(dest="authors_command", required=True)
    configure = author_commands.add_parser("configure", help="Install a library.")
    configure.add_argument("path", type=Path)
    author_commands.add_parser("list", help="List configured author profiles.")
    show = author_commands.add_parser("show", help="Show one author profile.")
    show.add_argument("author_id")
    init = commands.add_parser("init", help="Create PROJECT/manuscript.")
    init.add_argument("--project", type=Path, required=True)
    for name in ("title", "journal", "article-type"):
        init.add_argument(f"--{name}")
    init.add_argument("--publisher", choices=PUBLISHERS)
    init.add_argument("--language", choices=("en", "zh"))
    for role in ("first-author", "corresponding-author", "other-author"):
        init.add_argument(f"--{role}", action="append", default=[])
    init.add_argument("--authors", type=Path)
    init.add_argument("--bib", type=Path)
    init.add_argument("--custom-template", type=Path)
    init.add_argument("--engine", choices=("auto", "tectonic", "latex"), default="auto")
    for command, help_text in (
        ("status", "Show project status."),
        ("build", "Compile clean output and a marked PDF for revisions."),
        ("submission", "Build submission artifacts."),
    ):
        child = commands.add_parser(command, help=help_text)
        child.add_argument("--project", type=Path, required=True)
        if command != "status":
            child.add_argument("--round")
            child.add_argument("--engine", choices=("auto", "tectonic", "latex"))
        if command == "submission":
            child.add_argument("--allow-placeholders", action="store_true")
        if command == "build":
            child.add_argument("--keep-temp", action="store_true")
    revision = commands.add_parser("revision", help="Create the next revision.")
    revision.add_argument("--project", type=Path, required=True)
    revision.add_argument("--reviews", type=Path)
    revision.add_argument("--yes", action="store_true")
    for command in ("rollback", "reindex"):
        child = commands.add_parser(command)
        child.add_argument("--project", type=Path, required=True)
        child.add_argument("--yes", action="store_true")
    sync = commands.add_parser("sync-bib", help="Replace shared references.bib.")
    sync.add_argument("--project", type=Path, required=True)
    sync.add_argument("--bib", type=Path, required=True)
    return parser


def _prompt(value: str | None, label: str) -> str:
    if value:
        return value
    option = label.replace("_", "-")
    if not sys.stdin.isatty():
        raise ManuscriptError(f"--{option} is required in non-interactive mode.")
    answer = input(f"{label.replace('_', ' ').title()}: ").strip()
    if not answer:
        raise ManuscriptError(f"{label} must not be empty.")
    return answer


def _selected_authors(
    args: argparse.Namespace,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    library_path = resolve_author_library_path(args.authors)
    library = load_author_library(library_path)
    selected = (
        tuple(args.first_author),
        tuple(args.corresponding_author),
        tuple(args.other_author),
    )
    if selected[0] and selected[1]:
        return selected
    if not sys.stdin.isatty():
        raise ManuscriptError(
            "--first-author and --corresponding-author are required in non-interactive mode."
        )
    print("Available authors:")
    for index, (author_id, author) in enumerate(library.authors.items(), 1):
        print(f"\n{index}. {author_id}")
        print(f"   {author.name_en} / {author.name_zh}")

    def choose(label: str, required: bool) -> tuple[str, ...]:
        raw = input(f"{label} author IDs (comma separated): ").strip()
        values = tuple(item.strip() for item in raw.split(",") if item.strip())
        if required and not values:
            raise ManuscriptError(f"{label} author IDs must not be empty.")
        return values

    return (
        selected[0] or choose("First", True),
        selected[1] or choose("Corresponding", True),
        selected[2] or choose("Other", False),
    )


def _confirm(operation: str, supplied: bool) -> bool:
    if supplied:
        return True
    if not sys.stdin.isatty():
        raise ManuscriptError(f"{operation} requires --yes in non-interactive mode.")
    if input(f"Confirm {operation}? [y/N] ").strip().lower() not in {"y", "yes"}:
        raise ManuscriptError(f"{operation} cancelled.")
    return True


def _relative(project: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return str(path)


def _print_lifecycle(result: LifecycleResult, project: Path) -> None:
    print(f"{result.operation}: {result.version}")
    if result.artifacts:
        print("Generated:")
        for artifact in result.artifacts:
            print(f"  {artifact.label}: {_relative(project, artifact.path)}")


def _print_status(result: StatusResult) -> None:
    print(f"Project: {result.project}")
    print(f"Version: {result.version} ({result.round})")
    print(f"Parent: {result.parent or 'none'}")
    print(f"Journal: {result.journal}")
    print(f"Publisher: {result.publisher}")
    print(f"Authors: {', '.join(result.authors)}")
    if result.artifacts:
        print("Artifacts:")
        for artifact in result.artifacts:
            print(f"  {_relative(result.project, artifact)}")


def _print_doctor(result: DoctorResult) -> None:
    print("Environment report")
    for check in result.checks:
        status = (
            "PASS" if check.available else ("MISSING" if check.required else "OPTIONAL")
        )
        print(f"  {status:<8} {check.name:<24} {check.detail}")
    print(f"Result: {'READY' if result.ready else 'BLOCKED'}")


def _print_author_library() -> None:
    path = resolve_author_library_path()
    library = load_author_library(path)
    print(f"Author library: {path}")
    for author_id, author in library.authors.items():
        print(f"  {author_id}: {author.name_en} / {author.name_zh}")


def _print_author(author_id: str) -> None:
    path = resolve_author_library_path()
    library = load_author_library(path)
    author = library.authors.get(author_id)
    if author is None:
        raise ManuscriptError(f"Unknown author ID: {author_id}")
    print(f"Author ID: {author.author_id}")
    print(f"English name: {author.name_en}")
    print(f"Chinese name: {author.name_zh}")
    print(f"Email: {author.email or 'not configured'}")
    print(f"Affiliations: {', '.join(author.affiliations)}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the console interface and return a stable process status."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            doctor_result = doctor(
                language=args.language,
                publisher=args.publisher,
                engine=args.engine,
            )
            _print_doctor(doctor_result)
            return 0 if doctor_result.ready else 2
        if args.command == "authors":
            if args.authors_command == "configure":
                target = configure_author_library(args.path)
                print(f"Author library configured: {target}")
            elif args.authors_command == "list":
                _print_author_library()
            elif args.authors_command == "show":
                _print_author(args.author_id)
            print(f"Configuration directory: {configured_author_library_path().parent}")
            return 0
        if args.command == "init":
            first, corresponding, other = _selected_authors(args)
            lifecycle_result = initialize_manuscript(
                args.project,
                title=_prompt(args.title, "title"),
                journal=_prompt(args.journal, "journal"),
                publisher=_prompt(args.publisher, "publisher"),
                language=_prompt(args.language, "language"),
                article_type=_prompt(args.article_type, "article_type"),
                first_authors=first,
                corresponding_authors=corresponding,
                other_authors=other,
                authors_path=args.authors,
                bibliography_path=args.bib,
                custom_template=args.custom_template,
                engine=args.engine,
            )
            _print_lifecycle(lifecycle_result, args.project)
            return 0
        project = ManuscriptProject(args.project)
        if args.command == "status":
            _print_status(project.status())
            return 0
        if args.command == "build":
            lifecycle_result = project.build(
                args.round, engine=args.engine, keep_temp=args.keep_temp
            )
        elif args.command == "revision":
            lifecycle_result = project.start_revision(
                reviews=args.reviews, confirmed=_confirm("revision creation", args.yes)
            )
        elif args.command == "rollback":
            lifecycle_result = project.rollback(
                confirmed=_confirm("rollback", args.yes)
            )
        elif args.command == "reindex":
            lifecycle_result = project.reindex(confirmed=_confirm("reindex", args.yes))
        elif args.command == "submission":
            lifecycle_result = project.prepare_submission(
                args.round,
                engine=args.engine,
                allow_placeholders=args.allow_placeholders,
            )
        elif args.command == "sync-bib":
            lifecycle_result = project.sync_bib(args.bib)
        else:  # pragma: no cover
            raise ManuscriptError(f"Unknown command: {args.command}")
        _print_lifecycle(lifecycle_result, project.root)
        return 0
    except (ManuscriptError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
