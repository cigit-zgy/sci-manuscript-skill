"""Hermetic test configuration shared across manuscript lifecycle tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from sci_manuscript.authors import CONFIG_DIRECTORY_ENV
from sci_manuscript.templates import resources_root


@pytest.fixture(autouse=True)
def isolated_author_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provide one isolated configured library without touching user config."""
    config = tmp_path / "sci-manuscript-config"
    config.mkdir()
    source = (resources_root() / "authors.yaml").read_text(encoding="utf-8")
    source += """

  author:
    name_en: Anonymous Author
    name_zh: 匿名作者
    email: author@example.invalid
    affiliations: [1]

  author_one:
    name_en: First Author
    name_zh: 第一作者
    email: first@example.invalid
    affiliations: [1]

  author_two:
    name_en: Corresponding Author
    name_zh: 通讯作者
    email: corresponding@example.invalid
    affiliations: [1]

  author_three:
    name_en: Other Author
    name_zh: 其他作者
    affiliations: [1]
"""
    (config / "authors.yaml").write_text(source, encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIRECTORY_ENV, str(config))
