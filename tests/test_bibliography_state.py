"""Citation-resolved bibliography-state regression tests."""

from __future__ import annotations

from pathlib import Path

from sci_manuscript.bibliography import (
    bibliography_entry_count,
    citation_only_bibliography,
    resolved_citation_keys,
)


def test_citation_only_snapshot_keeps_dependencies_and_declarations() -> None:
    bibliography = r"""@string{journal = "Journal Name"}

@preamble{"Required preamble"}

@proceedings{parent,
  title = {Proceedings Parent},
  year = {2026}
}

@inproceedings{cited,
  author = {Example, A},
  title = {Cited Work},
  crossref = {parent}
}

@article{unused,
  title = {Unused Work}
}
"""

    snapshot = citation_only_bibliography(bibliography, ("cited",))

    assert bibliography_entry_count(snapshot) == 2
    assert "@string{journal" in snapshot
    assert "@preamble{" in snapshot
    assert "@proceedings{parent" in snapshot
    assert "@inproceedings{cited" in snapshot
    assert "@article{unused" not in snapshot


def test_resolved_citation_keys_use_aux_and_support_nocite_all(tmp_path: Path) -> None:
    aux = tmp_path / "manuscript.aux"
    aux.write_text(
        "\\relax\n\\citation{first,second}\n\\citation{second}\n\\citation{*}\n",
        encoding="utf-8",
    )

    assert resolved_citation_keys(aux) == ("first", "second", "*")


def test_resolved_citation_keys_exclude_build_auxiliary_databases(
    tmp_path: Path,
) -> None:
    aux = tmp_path / "manuscript.aux"
    aux.write_text(
        "\\citation{publisher-control}\n"
        "\\citation{article}\n"
        "\\bibdata{publisher-generated,references}\n",
        encoding="utf-8",
    )
    (tmp_path / "publisher-generated.bib").write_text(
        "@Control{publisher-control, setting={value}}\n",
        encoding="utf-8",
    )

    assert resolved_citation_keys(aux) == ("article",)


def test_nocite_all_intentionally_retains_every_entry() -> None:
    bibliography = "@article{a,title={A}}\n@article{b,title={B}}\n"

    snapshot = citation_only_bibliography(bibliography, ("*",))

    assert bibliography_entry_count(snapshot) == 2


def test_citation_only_snapshot_drops_local_attachment_paths() -> None:
    bibliography = r"""@article{used,
  title = {Portable metadata},
  file = {/Users/example/Zotero/storage/private.pdf},
  doi = {10.1000/example}
}
"""

    snapshot = citation_only_bibliography(bibliography, ("used",))

    assert "file =" not in snapshot
    assert "/Users/example" not in snapshot
    assert "doi = {10.1000/example}" in snapshot
