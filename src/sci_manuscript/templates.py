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
    """Resolve one built-in package publisher resource."""
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
    section_inputs = "\n".join(
        f"\\input{{sections/{Path(item['file']).stem}}}" for item in plan
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
            "FRONTMATTER_INPUT": frontmatter_input,
            "SECTION_INPUTS": section_inputs,
            "BIBLIOGRAPHY_STYLE": style,
            "BIBLIOGRAPHY_PATH": "references",
        },
    )
    defaults = resources_root() / "manuscript" / "sections" / "default"
    source_plan = ([frontmatter] if frontmatter is not None else []) + plan
    for item in source_plan:
        values = {"SECTION_TITLE": item["title"]}
        if frontmatter is not None and item is frontmatter:
            initial_title = config.metadata.title
            values.update(
                {
                    "TITLE_ZH": config.metadata.title_zh
                    or (initial_title if config.metadata.language == "zh" else ""),
                    "TITLE_EN": config.metadata.title_en
                    or (initial_title if config.metadata.language == "en" else ""),
                }
            )
        render_template(
            defaults / item["source"],
            version / "sections" / item["file"],
            values,
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
    bibliography_source: Path,
) -> None:
    """Install the shared bibliography and user-editable revision style."""
    shutil.copy2(bibliography_source, config.references / "references.bib")
    shutil.copy2(
        resources_root() / "revision_style.template.tex",
        config.references / "revision_style.tex",
    )
