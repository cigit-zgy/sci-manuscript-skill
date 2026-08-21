"""Distribution-backed package version helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_DISTRIBUTION = "sci-manuscript-skill"


def package_version() -> str:
    """Return the installed distribution version without a duplicate constant."""
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError:
        return "0+unknown"
