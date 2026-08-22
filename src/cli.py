"""Command-line interface."""
from __future__ import annotations
import argparse
from pathlib import Path
from .api import ManuscriptProject, initialize_manuscript
from .exceptions import ManuscriptError

def _confirm(message: str, yes: bool) -> bool:
    if yes:
        return True
    answer = input(f"{message} [y/N] ").strip().lower()
    return answer in {"y", "yes"}

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sci-manuscript")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--project", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--journal", required=True)
    init.add_argument("--publisher", required=True)
    init.add_argument("--language", default="en")
    for name in ("status", "build", "revision", "rollback", "reindex", "submission", "setup-zotero", "upgrade-project"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--project", default=".")
        if name in {"revision", "rollback", "reindex"}:
            cmd.add_argument("--yes", action="store_true")
        if name == "revision":
            cmd.add_argument("--reviews")
        if name == "submission":
            cmd.add_argument("--allow-placeholders", action="store_true")
    sync = sub.add_parser("sync-bib")
    sync.add_argument("--project", default=".")
    sync.add_argument("--bib-export", required=True)
    return p

def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_manuscript(args.project, args.title, args.journal, args.publisher, args.language)
            print(result.project)
            return 0
        project = ManuscriptProject(Path(args.project))
        if args.command == "status":
            print(project.status())
        elif args.command == "build":
            print(project.build())
        elif args.command == "revision":
            if _confirm("Create the next adjacent revision?", args.yes):
                print(project.start_revision(args.reviews))
        elif args.command == "rollback":
            plan = project.rollback_plan()
            if plan.changed_files:
                raise ManuscriptError("Rollback refused; user source modifications detected.")
            if _confirm(f"Remove {plan.version}?", args.yes):
                print(project.remove_latest_revision())
        elif args.command == "reindex":
            plan = project.reindex_plan()
            print(plan)
            if plan.renames and _confirm("Apply this reindex plan?", args.yes):
                print(project.reindex())
        elif args.command == "submission":
            print(project.prepare_submission(allow_placeholders=args.allow_placeholders))
        elif args.command == "setup-zotero":
            print(project.setup_zotero())
        elif args.command == "sync-bib":
            print(project.sync_bib(args.bib_export))
        elif args.command == "upgrade-project":
            print(project.upgrade_project())
        return 0
    except ManuscriptError as exc:
        print(f"ERROR: {exc}")
        return 2
