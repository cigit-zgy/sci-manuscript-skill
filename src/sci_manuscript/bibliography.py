"""Shared BibTeX synchronization and citation-resolved round snapshots."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import WorkflowError

AUX_CITATION_PATTERN = re.compile(r"\\citation\{([^}]*)\}")
AUX_BIBDATA_PATTERN = re.compile(r"\\bibdata\{([^}]*)\}")
BIBLATEX_CITATION_PATTERN = re.compile(r"\\abx@aux@cite\{[^}]*\}\{([^}]*)\}")
SOURCE_CITATION_PATTERN = re.compile(
    r"\\(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|nocite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}"
)
DEPENDENCY_PATTERN = re.compile(
    r"(?i)\b(?:crossref|xdata)\s*=\s*(?:\{([^}]*)\}|\"([^\"]*)\")"
)
ENTRY_HEADER_PATTERN = re.compile(r"@([A-Za-z]+)\s*[({]\s*([^,\s]+)\s*,")
LOCAL_ATTACHMENT_FIELD_PATTERN = re.compile(
    r"(?im)^[ \t]*file[ \t]*=[ \t]*"
    r'(?:\{(?:[^{}]|\{[^{}]*\})*\}|"(?:\\.|[^"\\])*")'
    r"[ \t]*,?[ \t]*(?:\n|$)"
)


@dataclass(frozen=True)
class BibTeXBlock:
    """One complete top-level BibTeX block in source order."""

    kind: str
    key: str | None
    text: str


def _bibtex_blocks(text: str) -> tuple[BibTeXBlock, ...]:
    """Scan complete BibTeX blocks without rewriting entry bytes."""
    blocks: list[BibTeXBlock] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "%":
            newline = text.find("\n", cursor)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if text[cursor] != "@":
            cursor += 1
            continue
        kind_match = re.match(r"@([A-Za-z]+)\s*", text[cursor:])
        if kind_match is None:
            cursor += 1
            continue
        opening = cursor + kind_match.end()
        if opening >= len(text) or text[opening] not in "{(":
            raise WorkflowError("Malformed BibTeX block opening.")
        opener = text[opening]
        closer = "}" if opener == "{" else ")"
        depth = 1
        brace_depth = 0
        quoted = False
        escaped = False
        end = opening + 1
        while end < len(text) and depth:
            character = text[end]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif opener == "{" and character == "{":
                depth += 1
            elif opener == "{" and character == "}":
                depth -= 1
            elif opener == "(" and character == "{" and not quoted:
                brace_depth += 1
            elif opener == "(" and character == "}" and not quoted and brace_depth:
                brace_depth -= 1
            elif opener == "(" and character == '"' and brace_depth == 0:
                quoted = not quoted
            elif (
                opener == "("
                and not quoted
                and brace_depth == 0
                and character == opener
            ):
                depth += 1
            elif (
                opener == "("
                and not quoted
                and brace_depth == 0
                and character == closer
            ):
                depth -= 1
            end += 1
        if depth:
            raise WorkflowError("Unbalanced BibTeX block.")
        raw = text[cursor:end]
        kind = kind_match.group(1).lower()
        key: str | None = None
        if kind not in {"comment", "preamble", "string"}:
            header = ENTRY_HEADER_PATTERN.match(raw)
            if header is None:
                raise WorkflowError(f"Malformed BibTeX @{kind} entry header.")
            key = header.group(2).strip()
        blocks.append(BibTeXBlock(kind, key, raw))
        cursor = end
    return tuple(blocks)


def resolved_citation_keys(aux_path: Path) -> tuple[str, ...]:
    """Read backend-resolved citation keys from one successful LaTeX AUX file."""
    if not aux_path.is_file():
        raise WorkflowError(f"Citation AUX file is missing: {aux_path}")
    text = aux_path.read_text(encoding="utf-8", errors="replace")
    values = [
        value
        for match in AUX_CITATION_PATTERN.finditer(text)
        for value in match.group(1).split(",")
    ]
    values.extend(match.group(1) for match in BIBLATEX_CITATION_PATTERN.finditer(text))
    auxiliary_keys: set[str] = set()
    for match in AUX_BIBDATA_PATTERN.finditer(text):
        for database in (value.strip() for value in match.group(1).split(",")):
            if not database or Path(database).name == "references":
                continue
            auxiliary = aux_path.parent / f"{database}.bib"
            if not auxiliary.is_file():
                continue
            auxiliary_keys.update(
                block.key
                for block in _bibtex_blocks(auxiliary.read_text(encoding="utf-8"))
                if block.key is not None
            )
    return tuple(
        dict.fromkeys(
            value.strip()
            for value in values
            if value.strip() and value.strip() not in auxiliary_keys
        )
    )


def source_citation_keys(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Fallback scanner for a round that has never produced an AUX snapshot."""
    values: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in SOURCE_CITATION_PATTERN.finditer(text):
            values.extend(match.group(1).split(","))
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def citation_only_bibliography(text: str, citation_keys: tuple[str, ...]) -> str:
    """Filter a canonical export to cited entries plus required dependencies."""
    blocks = _bibtex_blocks(text)
    entries = {block.key: block for block in blocks if block.key is not None}
    requested = set(entries) if "*" in citation_keys else set(citation_keys)
    missing = requested - entries.keys()
    if missing:
        raise WorkflowError(
            "Resolved citations are missing from references.bib: "
            + ", ".join(sorted(missing))
        )
    selected = set(requested)
    pending = list(requested)
    while pending:
        key = pending.pop()
        entry = entries[key]
        for match in DEPENDENCY_PATTERN.finditer(entry.text):
            raw = match.group(1) or match.group(2) or ""
            for dependency in (item.strip() for item in raw.split(",")):
                if not dependency or dependency in selected:
                    continue
                if dependency not in entries:
                    raise WorkflowError(
                        f"BibTeX dependency {dependency!r} required by {key!r} is missing."
                    )
                selected.add(dependency)
                pending.append(dependency)
    retained = [
        LOCAL_ATTACHMENT_FIELD_PATTERN.sub("", block.text).strip()
        for block in blocks
        if block.kind in {"preamble", "string"} or block.key in selected
    ]
    return ("\n\n".join(retained).rstrip() + "\n") if retained else ""


def bibliography_entry_count(text: str) -> int:
    """Count actual entries, excluding strings and preamble declarations."""
    return sum(block.key is not None for block in _bibtex_blocks(text))


def sync_bibliography(project: Path, explicit: Path) -> Path:
    """Atomically replace the single manuscript-level BibTeX database."""
    from .workspace import load_project, normalize_project

    root = normalize_project(project)
    config = load_project(root)
    source = explicit.expanduser().resolve()
    if not source.is_file():
        raise WorkflowError(f"Bibliography export is missing: {source}")
    text = source.read_text(encoding="utf-8")
    if "@" not in text or "{" not in text:
        raise WorkflowError(f"Bibliography does not contain BibTeX entries: {source}")
    target = config.references / "references.bib"
    temporary = target.with_suffix(".bib.new")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return target
