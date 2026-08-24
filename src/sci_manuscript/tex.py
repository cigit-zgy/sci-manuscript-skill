"""Small deterministic helpers for scanning TeX control sequences and fields."""

from __future__ import annotations


def is_escaped(text: str, index: int) -> bool:
    """Return whether the character at ``index`` follows an odd slash run."""
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def skip_tex_space(text: str, start: int) -> int:
    """Skip TeX whitespace and unescaped comments from ``start``."""
    cursor = start
    while cursor < len(text):
        if text[cursor].isspace():
            cursor += 1
            continue
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        break
    return cursor


def extract_braced(text: str, start: int) -> tuple[str, int]:
    """Extract one nested braced field while ignoring TeX comments."""
    opening = skip_tex_space(text, start)
    if opening >= len(text) or text[opening] != "{":
        raise ValueError("Expected a braced field.")
    depth = 0
    cursor = opening
    while cursor < len(text):
        character = text[cursor]
        if character == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        if character == "{" and not is_escaped(text, cursor):
            depth += 1
        elif character == "}" and not is_escaped(text, cursor):
            depth -= 1
            if depth == 0:
                return text[opening + 1 : cursor], cursor + 1
        cursor += 1
    raise ValueError("Unbalanced TeX command braces.")


def command_at(text: str, start: int, name: str) -> bool:
    """Return whether ``text`` contains the exact control word at ``start``."""
    command = f"\\{name}"
    if not text.startswith(command, start):
        return False
    end = start + len(command)
    return end >= len(text) or not (text[end].isalpha() or text[end] == "@")
