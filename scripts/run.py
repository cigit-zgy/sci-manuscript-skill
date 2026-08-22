#!/usr/bin/env python3
"""Single command-line entry for the scientific-manuscript lifecycle."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print(
        "ERROR: sci-manuscript-skill requires Python 3.11 or newer; "
        f"found {sys.version.split()[0]}.",
        file=sys.stderr,
    )
    raise SystemExit(2)

_SKILL_ROOT_HINT = Path("%%SCI_MANUSCRIPT_SKILL_ROOT%%")


def _package_version(distribution: str) -> tuple[bool, str]:
    """Return installed distribution status without importing the package."""
    try:
        return True, importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False, "not installed"


def _tool_version(name: str) -> tuple[bool, str]:
    """Return executable availability and its first version-output line."""
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
    first_line = output.splitlines()[0] if output else executable
    return True, first_line


def _print_check(status: str, dependency: str, detail: str) -> None:
    """Print one stable, human-readable environment check."""
    print(f"  {status:<7} {dependency:<24} {detail}")


def _doctor() -> int:
    """Inspect required and optional tools without changing the environment."""
    python_ok = sys.version_info >= (3, 11)
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
    poppler_ok = tools["pdftotext"][0] and tools["pdftoppm"][0]
    bibliography_ok = tectonic_ok or tools["bibtex"][0] or tools["biber"][0]

    latex_detail = "not found"
    if tectonic_ok:
        latex_detail = tools["tectonic"][1]
    elif tex_live_ok:
        driver = "XeLaTeX" if tools["xelatex"][0] else "pdfLaTeX"
        latex_detail = f"latexmk with {driver}"

    bibliography_detail = "not found"
    if tectonic_ok:
        bibliography_detail = "Tectonic integrated BibTeX processing"
    elif tools["bibtex"][0]:
        bibliography_detail = tools["bibtex"][1]
    elif tools["biber"][0]:
        bibliography_detail = tools["biber"][1]

    print("Environment report")
    print("\nRequired dependencies:")
    required = (
        (python_ok, "Python >= 3.11", sys.version.split()[0]),
        (yaml_ok, "PyYAML", yaml_version),
        (latex_ok, "LaTeX engine", latex_detail),
        (tools["latexdiff"][0], "latexdiff", tools["latexdiff"][1]),
        (
            poppler_ok,
            "Poppler PDF tools",
            (f"pdftotext: {tools['pdftotext'][1]}; pdftoppm: {tools['pdftoppm'][1]}"),
        ),
        (bibliography_ok, "BibTeX/Biber backend", bibliography_detail),
    )
    for available, dependency, detail in required:
        _print_check("PASS" if available else "MISSING", dependency, detail)

    print("\nOptional dependencies:")
    _print_check(
        "MANUAL",
        "Zotero Better BibTeX",
        "optional; provide an exported .bib file explicitly",
    )
    for name, label in (("ruff", "Ruff"), ("mypy", "Mypy")):
        available, detail = tools[name]
        _print_check("PASS" if available else "MISSING", label, detail)

    missing = [dependency for available, dependency, _ in required if not available]
    if missing:
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


# Keep the diagnostic usable even when PyYAML or the internal workflow imports are
# unavailable. Other commands load the full implementation below.
if __name__ == "__main__" and sys.argv[1:] == ["doctor"]:
    raise SystemExit(_doctor())


def _internal_scripts() -> Path:
    """Locate internal modules from the source or a copied project entrypoint."""
    local = Path(__file__).resolve().parent
    if (local / "workspace.py").is_file():
        return local
    environment = os.environ.get("SCI_MANUSCRIPT_SKILL_ROOT")
    root = Path(environment).expanduser() if environment else _SKILL_ROOT_HINT
    scripts = root.resolve() / "scripts"
    if not (scripts / "workspace.py").is_file():
        raise RuntimeError(
            "Cannot locate sci-manuscript-skill. Set SCI_MANUSCRIPT_SKILL_ROOT "
            "to the installed skill directory."
        )
    return scripts


def _default_project() -> Path:
    """Use the copied entrypoint directory, or caller cwd for the source entry."""
    entrypoint_directory = Path(__file__).resolve().parent
    if (entrypoint_directory / "workspace.py").is_file():
        return Path.cwd()
    return entrypoint_directory


try:
    sys.path.insert(0, str(_internal_scripts()))
except RuntimeError as exc:  # pragma: no cover - installation boundary
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

try:
    from metadata import (
        PUBLISHER_TEMPLATES,
        ManuscriptMetadata,
        MetadataError,
        SubmissionSettings,
        generate_author_metadata,
        load_author_library,
    )
except RuntimeError as exc:  # pragma: no cover - dependency boundary
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

from compile import build_clean_manuscript, compile_tex  # noqa: E402
from diff import MarkedResult, build_marked_manuscript  # noqa: E402
from response import build_response, init_response, parse_reviews  # noqa: E402
from workspace import (  # noqa: E402
    ProjectConfig,
    WorkflowError,
    ensure_submission_workspace,
    initialize_project,
    is_initialized,
    load_project,
    normalize_project,
    parse_round,
    round_directory_name,
    round_name,
    start_revision,
    sync_bibliography,
    temporary_run,
)


def _new_config(args: argparse.Namespace, project: Path) -> ProjectConfig:
    author_library = (
        load_author_library(Path(args.authors).expanduser().resolve())
        if args.authors
        else load_author_library(_internal_scripts().parent / "assets" / "authors.yaml")
    )
    selected_authors = (
        tuple(args.author) if args.author else tuple(author_library.authors)
    )
    missing = [name for name in selected_authors if name not in author_library.authors]
    if missing:
        raise MetadataError(
            "Selected authors are missing from authors.yaml: " + ", ".join(missing)
        )
    first_authors = (
        tuple(
            name
            for name in selected_authors
            if author_library.authors[name].role == "first_author"
        )
        or selected_authors[:1]
    )
    corresponding_authors = tuple(
        name
        for name in selected_authors
        if author_library.authors[name].role == "corresponding_author"
    )
    if not corresponding_authors:
        raise MetadataError(
            "Selected authors must include at least one corresponding_author."
        )
    ordinary_authors = tuple(
        name
        for name in selected_authors
        if name not in {*first_authors, *corresponding_authors}
    )
    metadata = ManuscriptMetadata(
        title=args.title,
        article_type=args.article_type,
        language=args.language,
        journal_name=args.journal,
        publisher=args.publisher,
        journal_template=PUBLISHER_TEMPLATES[args.publisher],
        round_number=0,
        parent_round=None,
        submission=SubmissionSettings(True, True, True),
        first_authors=first_authors,
        corresponding_authors=corresponding_authors,
        authors=ordinary_authors,
    )
    return ProjectConfig(project, metadata, args.engine or "auto")


def _relative(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def _report_generated(
    heading: str,
    version: str,
    project: Path,
    artifacts: list[tuple[str, Path]],
) -> None:
    print(f"{heading}: {version}")
    print("\nGenerated:")
    for label, path in artifacts:
        suffix = "/" if path.is_dir() else ""
        print(f"  {label}: {_relative(project, path)}{suffix}")


def _build_lifecycle(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str | None,
    allow_placeholders: bool,
) -> tuple[Path, MarkedResult | None, Path | None]:
    if round_number != config.current_round:
        raise WorkflowError("Build config must match the selected version.")
    generate_author_metadata(config.project, config.round_dir(round_number))
    clean = build_clean_manuscript(config, round_number, run_dir, engine)
    if round_number == 0:
        return clean, None, None
    marked = build_marked_manuscript(config, round_number, run_dir, engine)
    response_source = (
        config.round_dir(round_number) / "response" / "response_letter.tex"
    )
    if not response_source.exists():
        raise WorkflowError(f"Response source is missing: {response_source}")
    response_pdf = build_response(
        config,
        round_number,
        marked.locations,
        run_dir,
        engine,
        allow_placeholders,
    )
    return clean, marked, response_pdf


def _compile_submission_source(
    source: Path,
    name: str,
    config: ProjectConfig,
    run_dir: Path,
    engine: str | None,
) -> Path:
    result = compile_tex(source, run_dir / f"submission_{name}", config, engine)
    target = run_dir / "package_stage" / f"{name}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result.pdf, target)
    return target


def _prepare_submission(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine: str | None,
    allow_placeholders: bool,
) -> list[tuple[str, Path]]:
    clean, marked, response_pdf = _build_lifecycle(
        config,
        round_number,
        run_dir,
        engine,
        allow_placeholders,
    )
    submission = ensure_submission_workspace(config, round_number)
    stage = run_dir / "package_stage"
    stage.mkdir(parents=True, exist_ok=True)
    settings = config.metadata.submission
    optional_artifacts: list[Path] = []
    if settings.cover_letter:
        optional_artifacts.append(
            _compile_submission_source(
                submission / "cover_letter.tex",
                "cover_letter",
                config,
                run_dir,
                engine,
            )
        )
    if settings.highlights:
        optional_artifacts.append(
            _compile_submission_source(
                submission / "highlights.tex",
                "highlights",
                config,
                run_dir,
                engine,
            )
        )
    if settings.graphical_abstract:
        graphical_dir = submission / "graphical_abstract"
        supplied_graphical = graphical_dir / "graphical_abstract.pdf"
        if supplied_graphical.exists():
            graphical = stage / "graphical_abstract.pdf"
            shutil.copy2(supplied_graphical, graphical)
        else:
            graphical = _compile_submission_source(
                graphical_dir / "graphical_abstract.tex",
                "graphical_abstract",
                config,
                run_dir,
                engine,
            )
        optional_artifacts.append(graphical)
    shutil.copy2(clean, stage / "manuscript.pdf")
    if marked is not None:
        shutil.copy2(marked.pdf, stage / "marked_manuscript.pdf")
        if response_pdf is None:
            raise WorkflowError("A revision package requires response_letter.pdf.")
        shutil.copy2(response_pdf, stage / "response_letter.pdf")
    shutil.copy2(submission / "checklist.md", stage / "checklist.md")
    for artifact in optional_artifacts:
        if not artifact.exists():
            raise WorkflowError(f"Submission artifact is missing: {artifact}")
    package = submission / "package"
    package.mkdir(exist_ok=True)
    known = {
        "manuscript.pdf",
        "marked_manuscript.pdf",
        "response_letter.pdf",
        "cover_letter.pdf",
        "highlights.pdf",
        "graphical_abstract.pdf",
        "checklist.md",
    }
    for name in known:
        path = package / name
        if path.exists():
            path.unlink()
    for artifact in stage.iterdir():
        shutil.copy2(artifact, package / artifact.name)
    generated: list[tuple[str, Path]] = [("Clean manuscript", clean)]
    if marked is not None and response_pdf is not None:
        generated.extend(
            [
                ("Marked manuscript", marked.pdf),
                ("Response letter", response_pdf),
            ]
        )
    generated.append(("Submission package", package))
    return generated


def _status(project: Path) -> None:
    latest = load_project(project)
    parent = latest.metadata.parent_round
    parent_label = (
        "none"
        if parent is None
        else f"{round_directory_name(parent)} ({round_name(parent)})"
    )
    print(f"Project: {project.name}")
    print(
        "Current version: "
        f"{round_directory_name(latest.current_round)} "
        f"({round_name(latest.current_round)})"
    )
    print(f"Parent: {parent_label}")
    print(f"Authors: {', '.join(latest.metadata.author_names)}")
    print(f"Publisher: {latest.metadata.publisher}")
    print(f"Journal: {latest.journal}")
    print("Generated:")
    found = False
    for number in range(latest.current_round + 1):
        config = load_project(project, number)
        version_dir = config.round_dir(number)
        paths = sorted((version_dir / "output").glob("*.pdf"))
        paths.extend(sorted((version_dir / "submission" / "package").glob("*")))
        for path in paths:
            found = True
            print(f"  {_relative(project, path)}")
    if not found:
        print("  none")


def _load_selected_project(args: argparse.Namespace) -> tuple[Path, ProjectConfig, int]:
    project = normalize_project(args.project)
    if not is_initialized(project):
        raise WorkflowError(
            f"Project is not initialized: {project}. Run the init command first."
        )
    latest = load_project(project)
    selected = parse_round(getattr(args, "round", None), latest.current_round)
    return project, load_project(project, selected), selected


def execute(args: argparse.Namespace) -> int:
    """Execute one explicit lifecycle command."""
    if args.command == "doctor":
        return _doctor()
    project = normalize_project(args.project)
    if args.command == "init":
        authors_source = (
            Path(args.authors).expanduser().resolve() if args.authors else None
        )
        bibliography_source = (
            Path(args.bib).expanduser().resolve() if args.bib else None
        )
        config = initialize_project(
            _new_config(args, project),
            authors_source,
            bibliography_source,
        )
        with temporary_run(project, args.keep_temp) as run_dir:
            generate_author_metadata(config.project, config.round_dir(0))
            manuscript = build_clean_manuscript(config, 0, run_dir, args.engine)
        _report_generated(
            "Project initialized",
            round_directory_name(0),
            project,
            [("Initial manuscript", manuscript)],
        )
        if args.authors is None:
            print("\nACTION REQUIRED: replace references/authors.yaml.")
        if args.bib is None:
            print("ACTION REQUIRED: replace references/references.bib.")
        return 0
    if args.command == "status":
        if not is_initialized(project):
            raise WorkflowError(f"Project is not initialized: {project}")
        _status(project)
        return 0
    if args.command == "sync-bib":
        if not is_initialized(project):
            raise WorkflowError(f"Project is not initialized: {project}")
        explicit = Path(args.bib_export) if args.bib_export else None
        targets = sync_bibliography(project, explicit)
        _report_generated(
            "Bibliography synchronized",
            f"{len(targets)} shared file(s)",
            project,
            [("Bibliography", target) for target in targets],
        )
        return 0
    if args.command == "revision":
        latest = load_project(project)
        target = parse_round(args.round, latest.current_round + 1)
        reviews = Path(args.reviews).expanduser().resolve() if args.reviews else None
        if reviews is not None:
            parse_reviews(reviews)
        with temporary_run(project, args.keep_temp) as run_dir:
            config = start_revision(latest, target, run_dir)
            local_reviews = (
                config.round_dir(target) / "response" / "reviewer_comments.md"
            )
            response_source = init_response(
                config,
                target,
                reviews or local_reviews,
            )
        version = round_directory_name(target)
        print(f"Revision created: {version}")
        print(f"Parent: {round_directory_name(target - 1)} ({round_name(target - 1)})")
        print("\nGenerated:")
        print(f"  Response source: {_relative(project, response_source)}")
        return 0
    project, config, round_number = _load_selected_project(args)
    version = round_directory_name(round_number)
    if args.command == "build":
        with temporary_run(project, args.keep_temp) as run_dir:
            generate_author_metadata(config.project, config.round_dir(round_number))
            clean = build_clean_manuscript(config, round_number, run_dir, args.engine)
        _report_generated(
            "Build completed",
            version,
            project,
            [("Clean manuscript", clean)],
        )
        return 0
    if args.command in {"submission", "all"}:
        with temporary_run(project, args.keep_temp) as run_dir:
            generated = _prepare_submission(
                config,
                round_number,
                run_dir,
                args.engine,
                args.allow_placeholders,
            )
        _report_generated("Submission completed", version, project, generated)
        return 0
    raise WorkflowError(f"Unsupported command: {args.command}")


def _add_project_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project",
        default=str(_default_project()),
        help="Project root; defaults to the copied run.py directory.",
    )


def _add_build_arguments(parser: argparse.ArgumentParser) -> None:
    _add_project_argument(parser)
    parser.add_argument("--round", help="Optional rN or revision_N selector.")
    parser.add_argument("--engine", choices=("auto", "tectonic", "latex"))
    parser.add_argument("--keep-temp", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    """Create the explicit public subcommand interface."""
    parser = argparse.ArgumentParser(
        description="Manage a complete LaTeX scientific-manuscript lifecycle.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="Check Python and LaTeX workflow tools.")

    init = commands.add_parser("init", help="Initialize initial_submission (r0).")
    _add_project_argument(init)
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

    build = commands.add_parser("build", help="Compile the selected clean manuscript.")
    _add_build_arguments(build)

    revision = commands.add_parser(
        "revision",
        help="Create the next adjacent revision and response source.",
    )
    _add_project_argument(revision)
    revision.add_argument("--round", help="Advanced explicit next round selector.")
    revision.add_argument("--reviews", help="Reviewer-comments Markdown file.")
    revision.add_argument("--keep-temp", action="store_true")

    submission = commands.add_parser(
        "submission",
        help="Build submission materials and the selected version package.",
    )
    _add_build_arguments(submission)
    submission.add_argument("--allow-placeholders", action="store_true")

    all_command = commands.add_parser(
        "all",
        help="Build clean, diff, response, and submission outputs.",
    )
    _add_build_arguments(all_command)
    all_command.add_argument("--allow-placeholders", action="store_true")

    sync = commands.add_parser("sync-bib", help="Synchronize a Better BibTeX export.")
    _add_project_argument(sync)
    sync.add_argument("--bib-export", help="Explicit Better BibTeX export path.")

    status = commands.add_parser("status", help="Show lifecycle state and outputs.")
    _add_project_argument(status)
    return parser


def main() -> int:
    """Parse command-line arguments and return a stable process status."""
    args = build_parser().parse_args()
    try:
        return execute(args)
    except (MetadataError, WorkflowError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
