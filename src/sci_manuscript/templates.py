"""Installed manuscript and publisher template resolution and rendering."""

from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .errors import WorkflowError

if TYPE_CHECKING:
    from .workspace import ProjectConfig


def resources_root() -> Path:
    """Return the installed package-resource directory."""
    resource = files("sci_manuscript.resources")
    return Path(str(resource))


def _latex_escape(value: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in value)


def template_values(config: ProjectConfig) -> dict[str, str]:
    """Return non-author replacements for editable correspondence sources."""
    return {
        "TITLE": _latex_escape(config.title),
        "JOURNAL": _latex_escape(config.journal),
        "ARTICLE_TYPE": _latex_escape(config.article_type),
        "EDITOR_NAME": "Editor",
    }


def render_template(source: Path, target: Path, values: dict[str, str]) -> None:
    """Render one tokenized UTF-8 template without overwriting user content."""
    if target.exists():
        raise WorkflowError(f"Refusing to overwrite user file: {target}")
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"Cannot read template: {source}") from exc
    for key, value in values.items():
        text = text.replace(f"%%{key}%%", value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def publisher_resource(config: ProjectConfig) -> Path:
    """Resolve a built-in package resource or one explicit custom template."""
    if config.metadata.publisher == "custom":
        custom = config.references / "journal_template"
        if not custom.is_dir():
            raise WorkflowError(f"Custom journal template is missing: {custom}")
        return custom
    resource = resources_root() / "journal_templates" / config.metadata.publisher
    if not resource.is_dir():
        raise WorkflowError(f"Publisher package resource is missing: {resource}")
    return resource


def _publisher_layout(
    config: ProjectConfig,
) -> tuple[dict[str, str] | None, list[dict[str, str]], str, str]:
    path = publisher_resource(config) / "sections.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkflowError(f"Cannot load publisher section mapping: {path}") from exc
    sections = data.get("sections") if isinstance(data, dict) else None
    bibliography = data.get("bibliography") if isinstance(data, dict) else None
    frontmatter = data.get("frontmatter") if isinstance(data, dict) else None
    if (
        not isinstance(sections, list)
        or not sections
        or not isinstance(bibliography, dict)
    ):
        raise WorkflowError(f"Invalid publisher section mapping: {path}")
    package = str(bibliography.get("package", "")).strip()
    style = str(bibliography.get("style", "")).strip()
    if not package or not style:
        raise WorkflowError(f"Publisher bibliography mapping is incomplete: {path}")
    frontmatter_plan: dict[str, str] | None = None
    if frontmatter is not None:
        if (
            not isinstance(frontmatter, dict)
            or "file" not in frontmatter
            or "source" not in frontmatter
        ):
            raise WorkflowError(f"Invalid publisher frontmatter mapping: {path}")
        frontmatter_plan = {
            "file": str(frontmatter["file"]),
            "source": str(frontmatter["source"]),
            "title": "",
        }
    plan: list[dict[str, str]] = []
    for index, item in enumerate(sections, 1):
        if not isinstance(item, dict) or "file" not in item or "source" not in item:
            raise WorkflowError(f"Invalid section mapping item {index}: {path}")
        plan.append(
            {
                "file": str(item["file"]),
                "source": str(item["source"]),
                "title": str(item.get("title", "")),
            }
        )
    return frontmatter_plan, plan, package, style


def initialize_manuscript_sources(config: ProjectConfig, version: Path) -> None:
    """Create user-owned manuscript composition and section sources."""
    frontmatter, plan, _package, style = _publisher_layout(config)
    abstract_input = ""
    body_plan = plan
    if frontmatter is None:
        abstract = plan[0]
        abstract_input = f"\\input{{sections/{Path(abstract['file']).stem}}}"
        body_plan = plan[1:]
    section_inputs = "\n".join(
        f"\\input{{sections/{Path(item['file']).stem}}}" for item in body_plan
    )
    frontmatter_input = (
        f"\\input{{sections/{Path(frontmatter['file']).stem}}}"
        if frontmatter is not None
        else ""
    )
    render_template(
        publisher_resource(config) / "workflow.tex",
        version / "manuscript.tex",
        {
            "ABSTRACT_INPUT": abstract_input,
            "FRONTMATTER_INPUT": frontmatter_input,
            "SECTION_INPUTS": section_inputs,
            "BIBLIOGRAPHY_STYLE": style,
            "BIBLIOGRAPHY_PATH": "references",
        },
    )
    defaults = resources_root() / "manuscript" / "sections" / "default"
    source_plan = ([frontmatter] if frontmatter is not None else []) + plan
    for item in source_plan:
        render_template(
            defaults / item["source"],
            version / "sections" / item["file"],
            {"SECTION_TITLE": item["title"]},
        )


def ensure_manuscript_sources(config: ProjectConfig, round_number: int) -> None:
    """Materialize sources for a metadata-first initial submission exactly once."""
    version = config.round_dir(round_number)
    manuscript = version / "manuscript.tex"
    if manuscript.is_file():
        return
    if round_number != 0:
        raise WorkflowError(f"Manuscript source is missing: {manuscript}")
    sections = version / "sections"
    existing = tuple(sections.iterdir()) if sections.is_dir() else ()
    if existing:
        raise WorkflowError(
            f"Refusing to overwrite draft manuscript sections: {sections}"
        )
    initialize_manuscript_sources(config, version)


def install_reference_resources(
    config: ProjectConfig,
    authors_source: Path,
    bibliography_source: Path,
    custom_template: Path | None,
) -> None:
    """Install shared author, bibliography, style, and custom template resources."""
    shutil.copy2(authors_source, config.references / "authors.yaml")
    shutil.copy2(bibliography_source, config.references / "references.bib")
    shutil.copy2(
        resources_root() / "revision_style.template.tex",
        config.references / "revision_style.tex",
    )
    if config.metadata.publisher == "custom":
        if custom_template is None or not custom_template.is_dir():
            raise WorkflowError(
                "publisher=custom requires --custom-template directory."
            )
        shutil.copytree(custom_template, config.references / "journal_template")
    elif custom_template is not None:
        raise WorkflowError("--custom-template requires publisher=custom.")
