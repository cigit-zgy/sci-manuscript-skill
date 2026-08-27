"""TeX-native intermediate and package sidecar contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import sci_manuscript.response as response_module
from sci_manuscript.compile import (
    SciState,
    SciStateEvent,
    TeXStateFiles,
    parse_sci_state,
)
from sci_manuscript.errors import WorkflowError
from sci_manuscript.response import ResponseTexRegistry, validate_response_tex_state

ROOT = Path(__file__).resolve().parents[1]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_tex_state_files_discovers_only_existing_known_intermediates(
    tmp_path: Path,
) -> None:
    for suffix in (".aux", ".bbl", ".sci", ".compiler.log"):
        tmp_path.joinpath(f"manuscript{suffix}").write_text("state\n", encoding="utf-8")

    state = TeXStateFiles.discover(tmp_path, "manuscript")

    assert state.aux == tmp_path / "manuscript.aux"
    assert state.bbl == tmp_path / "manuscript.bbl"
    assert state.sci == tmp_path / "manuscript.sci"
    assert state.compiler_log == tmp_path / "manuscript.compiler.log"
    assert state.toc is None
    assert state.lof is None
    assert state.lot is None


def test_parse_sci_state_accepts_compact_response_events(tmp_path: Path) -> None:
    response_hash = _digest("Stable source response")
    path = tmp_path / "response_letter.sci"
    path.write_text(
        "\n".join(
            (
                "SCI_SCHEMA|1",
                "DOCUMENT|response",
                "RESPONSE_SCHEMA|1",
                "TEMPLATE|1",
                "CORRESPONDENCE|liu_hong",
                "COMMENT|1-1",
                f"RESPONSE|1-1|{response_hash}",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    state = parse_sci_state(path, "response")

    assert state.schema == 1
    assert state.document == "response"
    assert state.events[-1] == SciStateEvent("RESPONSE", ("1-1", response_hash))


def test_parse_sci_state_accepts_proof_carrying_revision_events(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manuscript_marked.sci"
    path.write_text(
        "SCI_SCHEMA|1\n"
        "DOCUMENT|marked\n"
        "MARKED_SCHEMA|1\n"
        "REVISION|sci:rev:r01:e0001|author\n"
        "REVISION|sci:rev:r01:e0002|reviewer|1-1,2-3\n",
        encoding="utf-8",
    )

    state = parse_sci_state(path, "marked")

    assert state.events[-2:] == (
        SciStateEvent("REVISION", ("sci:rev:r01:e0001", "author")),
        SciStateEvent("REVISION", ("sci:rev:r01:e0002", "reviewer", "1-1,2-3")),
    )


@pytest.mark.parametrize(
    "invalid_event",
    (
        "RESPONSE|1-1|raw scientific prose",
        "COMMENT|not-a-review-id",
        "UNKNOWN|value",
    ),
)
def test_parse_sci_state_rejects_unbounded_or_raw_fields(
    tmp_path: Path,
    invalid_event: str,
) -> None:
    path = tmp_path / "invalid.sci"
    path.write_text(
        f"SCI_SCHEMA|1\nDOCUMENT|response\n{invalid_event}\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError, match="malformed SCI event"):
        parse_sci_state(path, "response")


def test_parse_sci_state_rejects_duplicate_events(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.sci"
    path.write_text(
        "SCI_SCHEMA|1\nDOCUMENT|marked\nMARKED_SCHEMA|1\nMARKED_SCHEMA|1\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError, match="duplicate SCI event"):
        parse_sci_state(path, "marked")


def test_response_tex_registry_requires_exact_expected_event_order() -> None:
    response_hash = _digest("Response body")
    location_hash = _digest("Lines 10--12")
    expected = ResponseTexRegistry(
        corresponding_author_ids=("liu_hong",),
        comment_ids=("1-1",),
        response_hashes=(("1-1", response_hash),),
        location_hashes=(("1-1", location_hash),),
    )
    emitted = SciState(1, "response", expected.events())

    assert validate_response_tex_state(expected, emitted)

    reordered = SciState(1, "response", tuple(reversed(expected.events())))
    with pytest.raises(WorkflowError, match="RESPONSE_TEX_STATE_CONSISTENCY_FAILED"):
        validate_response_tex_state(expected, reordered)


def test_response_registry_hashes_source_owned_bodies_and_locations() -> None:
    registry = response_module.build_response_tex_registry(
        ("liu_hong", "second_author"),
        ("1-1", "2-1"),
        {"1-1": "First response.", "2-1": "第二条回复。"},
        {"1-1": "Lines 10--12"},
    )

    assert registry.corresponding_author_ids == ("liu_hong", "second_author")
    assert registry.response_hashes == (
        ("1-1", _digest("First response.")),
        ("2-1", _digest("第二条回复。")),
    )
    assert registry.location_hashes == (("1-1", _digest("Lines 10--12")),)


def test_package_tex_resources_emit_compiled_state_without_raw_prose() -> None:
    runtime = ROOT.joinpath("src/resources/revision/marked_runtime.tex").read_text(
        encoding="utf-8"
    )
    assert "SCI_SCHEMA|1" in runtime
    assert "DOCUMENT|marked" in runtime
    assert "MARKED_SCHEMA|1" in runtime

    for language in ("zh", "en"):
        template = ROOT.joinpath(
            f"src/resources/correspondence_templates/response/response_{language}.tex"
        ).read_text(encoding="utf-8")
        assert "SCI_SCHEMA|1" in template
        assert "DOCUMENT|response" in template
        assert r"\SCIStateResponseSchema{1}" in template
        assert r"\SCIStateTemplate{1}" in template
        assert template.count("%%RESPONSE_CORRESPONDENCE_STATE%%") == 1
