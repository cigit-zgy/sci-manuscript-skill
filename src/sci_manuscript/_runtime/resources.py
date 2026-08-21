"""Access immutable runtime files shipped inside the installed package."""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

import yaml

RESOURCE_PACKAGE = "sci_manuscript.resources"

REVISION_CONTRACT_FILE = "revision_contract.yaml"
REVISION_FORBIDDEN_OPERATIONS = frozenset(
    {
        "scientific_content_change",
        "paragraph_rewrite",
        "section_restructure",
        "novelty_change",
        "interpretation_change",
        "unsupported_addition",
    }
)


def resource(*parts: str) -> Traversable:
    """Return one package resource without assuming a source checkout."""
    item = files(RESOURCE_PACKAGE)
    for part in parts:
        item = item.joinpath(part)
    return item


def read_resource_text(*parts: str) -> str:
    """Read one UTF-8 package resource."""
    item = resource(*parts)
    if not item.is_file():
        raise FileNotFoundError("Package resource is missing: " + "/".join(parts))
    return item.read_text(encoding="utf-8")


def load_revision_contract() -> dict[str, object]:
    """Load and validate the packaged revision content-boundary contract.

    Revision operations fail fast when the installed package ships a contract
    that no longer declares the no-content-edit boundary, so the documented
    rule in ``references/revision_contract.yaml`` is enforced by the runtime
    instead of remaining agent-facing prose only.
    """
    data = yaml.safe_load(read_resource_text(REVISION_CONTRACT_FILE))
    if not isinstance(data, dict):
        raise RuntimeError("The packaged revision contract must be a mapping.")
    revision = data.get("revision")
    if (
        not isinstance(revision, dict)
        or revision.get("default_permission") != "no_content_edit"
    ):
        raise RuntimeError(
            "The packaged revision contract must default to no_content_edit."
        )
    forbidden = data.get("forbidden_operations")
    if (
        not isinstance(forbidden, list)
        or not set(forbidden) >= REVISION_FORBIDDEN_OPERATIONS
    ):
        raise RuntimeError(
            "The packaged revision contract must forbid every scientific "
            "content-change operation."
        )
    return data


def copy_resource_file(parts: tuple[str, ...], target: Path) -> None:
    """Copy one packaged file to a project-owned path."""
    item = resource(*parts)
    if not item.is_file():
        raise FileNotFoundError("Package resource is missing: " + "/".join(parts))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(item.read_bytes())


def copy_resource_tree(parts: tuple[str, ...], target: Path) -> None:
    """Recursively copy one packaged directory without repository assumptions."""
    source = resource(*parts)
    if not source.is_dir():
        raise FileNotFoundError("Package resource is missing: " + "/".join(parts))
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite resource directory: {target}")
    target.mkdir(parents=True)

    def copy_children(item: Traversable, destination: Path) -> None:
        for child in item.iterdir():
            child_target = destination / child.name
            if child.is_dir():
                child_target.mkdir()
                copy_children(child, child_target)
            else:
                child_target.write_bytes(child.read_bytes())

    copy_children(source, target)
