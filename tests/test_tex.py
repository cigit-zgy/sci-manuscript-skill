"""Low-level TeX syntax helper regression tests."""

from __future__ import annotations

import pytest
from sci_manuscript.tex import (
    command_at,
    extract_braced,
    is_commented,
    is_escaped,
    scan_tex_commands,
    skip_tex_space,
)


def test_is_escaped_counts_consecutive_backslashes() -> None:
    assert is_escaped(r"\%", 1)
    assert not is_escaped(r"\\%", 2)


def test_skip_tex_space_skips_whitespace_and_unescaped_comments() -> None:
    text = " \t% ignored { brace\n  {value}"
    assert skip_tex_space(text, 0) == text.index("{value}")


def test_extract_braced_preserves_nested_and_escaped_braces() -> None:
    text = r"  {outer {nested} \{literal\}} tail"
    value, end = extract_braced(text, 0)
    assert value == r"outer {nested} \{literal\}"
    assert text[end:] == " tail"


def test_extract_braced_ignores_braces_inside_comments() -> None:
    text = "{% unmatched }}}\nvisible {nested}}"
    value, end = extract_braced(text, 0)
    assert value.endswith("visible {nested}")
    assert end == len(text)


def test_extract_braced_rejects_unbalanced_input() -> None:
    with pytest.raises(ValueError, match="Unbalanced"):
        extract_braced("{missing", 0)


def test_command_at_rejects_longer_control_word() -> None:
    assert command_at(r"\review{1-1}{text}", 0, "review")
    assert not command_at(r"\reviewer{text}", 0, "review")


def test_is_commented_respects_escaped_percent() -> None:
    text = "active \\% text % disabled \\review{1-1}{x}\nnext"
    assert not is_commented(text, text.index("text"))
    assert is_commented(text, text.index(r"\review"))
    assert not is_commented(text, text.index("next"))


def test_tex_scanner_ignores_comments_and_parses_nested_fields() -> None:
    text = (
        "% \\review{1-1}{disabled}\n"
        "\\review{AE-1}{active {nested} body}\n"
        "% \\input{disabled}\n\\input{sections/active}\n"
    )
    reviews = scan_tex_commands(text, ("review",), field_count=2)
    inputs = scan_tex_commands(text, ("input", "include"), field_count=1)
    assert reviews[0].fields == ("AE-1", "active {nested} body")
    assert inputs[0].fields == ("sections/active",)
