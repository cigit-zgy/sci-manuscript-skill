"""Deterministic revision diffing, provenance classification, and marked output."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .compile import (
    compile_tex,
    publish_file_atomically,
    run_command,
    stage_runtime_resources,
)
from .errors import WorkflowError
from .locations import build_review_locations
from .provenance import ProvenanceSource, extract_provenance, split_by_review_provenance
from .templates import resources_root
from .tex import (
    command_at,
    extract_braced,
    is_commented,
    is_escaped,
    scan_tex_commands,
    skip_tex_space,
)
from .workspace import ProjectConfig, strip_provenance_wrappers

DIF_COMMENT_PATTERN = re.compile(r"(?m)^%DIF[^\n]*(?:\n|$)")
DIF_CONTROL_PATTERN = re.compile(r"\\DIF(?:add|del|mod)(?:begin|end)(?:FL)?\s*")
STYLE_BEGIN = "% SCI_DIFF_STYLE_BEGIN"
STYLE_END = "% SCI_DIFF_STYLE_END"
CHARACTER_REFINEMENT_THRESHOLD = 0.70
MAX_CHARACTER_REFINEMENT_CHARS = 2000
CHINESE_TEXT_COMMANDS = (
    "cnabstract",
    "cnkeywords",
    "enabstract",
    "enkeywords",
    "firstauthorcn",
    "firstauthoren",
    "funding",
    "entitle",
    "keywords",
)
PUBLISHER_METADATA_CONTEXT_COMMANDS = (
    "author",
    "enauthor",
    "affiliation",
    "enaffiliation",
    "firstauthorcn",
    "firstauthoren",
    "corrauthorcn",
    "corrauthoren",
    "funding",
    "cortext",
    "address",
    "email",
    "affil",
    "alsoaffiliation",
)

_REVISION_RUNTIME_TEMPLATE = (
    resources_root() / "revision" / "marked_runtime.tex"
).read_text(encoding="utf-8")

REVISION_RUNTIME = _REVISION_RUNTIME_TEMPLATE.replace("%%CJK_REVISION_PACKAGE%%", "")


def _revision_runtime(language: str) -> str:
    cjk_package = r"\RequirePackage{xeCJKfntef}" if language == "zh" else ""
    return _REVISION_RUNTIME_TEMPLATE.replace("%%CJK_REVISION_PACKAGE%%", cjk_package)


@dataclass(frozen=True)
class MarkedResult:
    """Published marked PDF and in-memory reviewer locations."""

    pdf: Path
    locations: dict[str, str]


@dataclass(frozen=True)
class _DiffSegment:
    kind: str
    content: str
    macro: str = ""


@dataclass(frozen=True)
class _BibliographyEntry:
    key: str
    command: str
    content: str


@dataclass(frozen=True)
class _BibliographyDocument:
    header: str
    entries: tuple[_BibliographyEntry, ...]
    footer: str


@dataclass(frozen=True)
class _DisplayEquation:
    """One labelled display equation and its exact source boundaries."""

    label: str
    start: int
    end: int
    body_without_label: str


def _optional_field_end(text: str, start: int) -> int:
    """Return the end of one optional TeX field, or ``start`` when absent."""
    opening = skip_tex_space(text, start)
    if opening >= len(text) or text[opening] != "[":
        return start
    depth = 1
    cursor = opening + 1
    while cursor < len(text):
        if text[cursor] == "%" and not is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        if text[cursor] == "[" and not is_escaped(text, cursor):
            depth += 1
        elif text[cursor] == "]" and not is_escaped(text, cursor):
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    raise WorkflowError("Unbalanced optional label in generated bibliography.")


def _parse_bibliography(text: str) -> _BibliographyDocument:
    """Parse generated ``\\bibitem`` boundaries while preserving rendered TeX."""
    commands: list[tuple[int, int, str]] = []
    cursor = 0
    while cursor < len(text):
        start = text.find(r"\bibitem", cursor)
        if start < 0:
            break
        if (
            is_escaped(text, start)
            or is_commented(text, start)
            or not command_at(text, start, "bibitem")
        ):
            cursor = start + 1
            continue
        field_start = start + len(r"\bibitem")
        optional_end = _optional_field_end(text, field_start)
        if optional_end != field_start:
            field_start = optional_end
        try:
            key, end = extract_braced(text, field_start)
        except ValueError as exc:
            raise WorkflowError(
                "Malformed \\bibitem in generated bibliography."
            ) from exc
        key = key.strip()
        if not key:
            raise WorkflowError(
                "Generated bibliography contains an empty citation key."
            )
        commands.append((start, end, key))
        cursor = end

    footer_start = len(text)
    search_from = commands[-1][1] if commands else 0
    try:
        endings = scan_tex_commands(text, ("end",), field_count=1)
    except ValueError as exc:
        raise WorkflowError("Malformed generated bibliography environment.") from exc
    for ending in endings:
        if ending.start >= search_from and ending.fields[0].endswith("bibliography"):
            footer_start = ending.start
            break
    if footer_start == len(text):
        raise WorkflowError("Generated bibliography has no closing environment.")

    entries: list[_BibliographyEntry] = []
    seen: set[str] = set()
    for index, (start, end, key) in enumerate(commands):
        if key in seen:
            raise WorkflowError(f"Duplicate generated bibliography key: {key}")
        seen.add(key)
        content_end = (
            commands[index + 1][0] if index + 1 < len(commands) else footer_start
        )
        entries.append(_BibliographyEntry(key, text[start:end], text[end:content_end]))
    header_end = commands[0][0] if commands else footer_start
    return _BibliographyDocument(
        text[:header_end],
        tuple(entries),
        text[footer_start:],
    )


def _align_bibliographies(old: str, current: str) -> tuple[str, str]:
    """Align rendered entries by citation key while retaining current numbering."""
    parent = _parse_bibliography(old)
    child = _parse_bibliography(current)
    parent_by_key = {entry.key: entry for entry in parent.entries}
    current_keys = {entry.key for entry in child.entries}
    old_parts = [child.header]
    new_parts = [child.header]
    for entry in child.entries:
        previous = parent_by_key.get(entry.key)
        old_parts.extend((entry.command, "" if previous is None else previous.content))
        new_parts.extend((entry.command, entry.content))
    for entry in parent.entries:
        if entry.key in current_keys:
            continue
        old_parts.append(f"\n\\SCIDeletedBibItem{{{entry.content}}}\n")
        new_parts.append("\n\\SCIDeletedBibItem{}\n")
    old_parts.append(child.footer)
    new_parts.append(child.footer)
    return "".join(old_parts), "".join(new_parts)


def _replace_bibliography(text: str, bibliography: str) -> str:
    """Replace BibTeX commands with one materialized visible bibliography."""
    try:
        commands = scan_tex_commands(
            text,
            ("bibliographystyle", "bibliography"),
            field_count=1,
        )
    except ValueError as exc:
        raise WorkflowError(
            "Malformed bibliography command in manuscript source."
        ) from exc
    bibliographies = [command for command in commands if command.name == "bibliography"]
    if len(bibliographies) != 1:
        raise WorkflowError(
            "Marked comparison requires exactly one active \\bibliography command."
        )
    pieces: list[str] = []
    cursor = 0
    for command in commands:
        pieces.append(text[cursor : command.start])
        if command.name == "bibliography":
            pieces.append(bibliography)
        cursor = command.end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _display_equations(text: str) -> tuple[_DisplayEquation, ...]:
    """Return active, labelled ``equation`` environments in source order."""
    try:
        commands = scan_tex_commands(text, ("begin", "end"), field_count=1)
    except ValueError as exc:
        raise WorkflowError(
            "Malformed display environment in manuscript source."
        ) from exc
    stack = []
    equations: list[_DisplayEquation] = []
    seen_labels: set[str] = set()
    for command in commands:
        environment = command.fields[0].strip()
        if command.name == "begin":
            stack.append(command)
            continue
        if not stack or stack[-1].fields[0].strip() != environment:
            raise WorkflowError("Unbalanced display environment in manuscript source.")
        opening = stack.pop()
        if environment != "equation":
            continue
        body = text[opening.end : command.start]
        try:
            labels = scan_tex_commands(body, ("label",), field_count=1)
        except ValueError as exc:
            raise WorkflowError(
                "Malformed equation label in manuscript source."
            ) from exc
        if not labels:
            continue
        if len(labels) != 1:
            raise WorkflowError(
                "A display equation must contain at most one active \\label command."
            )
        label = labels[0].fields[0].strip()
        if not label:
            raise WorkflowError("A display equation contains an empty label.")
        if label in seen_labels:
            raise WorkflowError(f"Duplicate display equation label: {label}")
        seen_labels.add(label)
        body_without_label = body[: labels[0].start] + body[labels[0].end :]
        equations.append(
            _DisplayEquation(
                label=label,
                start=opening.start,
                end=command.end,
                body_without_label=body_without_label,
            )
        )
    if stack:
        raise WorkflowError("Unbalanced display environment in manuscript source.")
    return tuple(equations)


def _normalized_equation_body(body: str) -> str:
    """Normalize insignificant whitespace for structural similarity testing."""
    return " ".join(body.split())


def _replace_spans(text: str, replacements: list[tuple[int, int, str]]) -> str:
    """Apply non-overlapping source replacements from right to left."""
    result = text
    for start, end, replacement in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def _align_changed_display_equations(old: str, current: str) -> tuple[str, str]:
    """Render each changed labelled equation atomically before ``latexdiff``.

    The old formula is rendered as an unnumbered deletion and the complete
    current formula as one numbered addition with preserved provenance.
    """
    old_equations = {equation.label: equation for equation in _display_equations(old)}
    current_equations = {
        equation.label: equation for equation in _display_equations(current)
    }
    current_provenance = extract_provenance(current)
    visible_current_equations = {
        equation.label: equation
        for equation in _display_equations(current_provenance.text)
    }
    old_replacements: list[tuple[int, int, str]] = []
    current_replacements: list[tuple[int, int, str]] = []
    for label in old_equations.keys() & current_equations.keys():
        previous = old_equations[label]
        revised = current_equations[label]
        old_body = _normalized_equation_body(previous.body_without_label)
        new_body = _normalized_equation_body(revised.body_without_label)
        if old_body == new_body:
            continue
        deleted_body = previous.body_without_label.strip()
        added_body = revised.body_without_label.strip()
        deleted = f"\\SCIDeletedEquation{{{deleted_body}}}\n"
        visible_revised = visible_current_equations[label]
        is_reviewer_change = any(
            span.start <= visible_revised.start and visible_revised.end <= span.end
            for span in current_provenance.review_spans
        )
        addition_command = (
            "SCIReviewerAddedEquation" if is_reviewer_change else "SCIAddedEquation"
        )
        replacement = (
            f"{deleted}\\{addition_command}{{{added_body}}}{{{revised.label}}}\n"
        )
        old_replacements.append((previous.start, previous.end, replacement))
        current_replacements.append((revised.start, revised.end, replacement))
    return (
        _replace_spans(old, old_replacements),
        _replace_spans(current, current_replacements),
    )


def _materialize_bibliography(
    source: Path,
    flattened: str,
    build_dir: Path,
    config: ProjectConfig,
    engine_override: str | None,
) -> str:
    """Compile one staged round and return its publisher-rendered ``.bbl``."""
    if not scan_tex_commands(flattened, ("bibliography",), field_count=1):
        raise WorkflowError("Manuscript has no active bibliography command.")
    compile_tex(
        source,
        build_dir,
        config,
        engine_override,
        keep_intermediates=True,
    )
    bibliography = build_dir / f"{source.stem}.bbl"
    if not bibliography.is_file():
        raise WorkflowError(
            "Compiler did not materialize the expected bibliography .bbl."
        )
    return bibliography.read_text(encoding="utf-8")


def _flatten_tex(
    path: Path,
    roots: tuple[Path, ...],
    active: tuple[Path, ...] = (),
) -> str:
    """Expand manuscript inputs for deterministic single-stream comparison."""
    resolved = path.resolve()
    if resolved in active:
        chain = " -> ".join(item.name for item in (*active, resolved))
        raise WorkflowError(f"Recursive TeX input detected: {chain}")
    if not any(resolved.is_relative_to(root.resolve()) for root in roots):
        raise WorkflowError(f"TeX input escapes permitted project roots: {resolved}")
    text = resolved.read_text(encoding="utf-8")

    def replace_input(name: str, original: str) -> str:
        name = name.strip()
        if name == "preamble" or name.startswith("preamble/"):
            return original
        candidate = resolved.parent / name
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".tex")
        if not candidate.exists():
            for root in roots:
                alternate = root / name
                if alternate.suffix == "":
                    alternate = alternate.with_suffix(".tex")
                if alternate.exists():
                    candidate = alternate
                    break
        if not candidate.exists():
            return original
        nested = _flatten_tex(candidate, roots, (*active, resolved))
        return f"\n% BEGIN INPUT {name}\n{nested}\n% END INPUT {name}\n"

    try:
        commands = scan_tex_commands(
            text,
            ("input", "include"),
            field_count=1,
        )
    except ValueError as exc:
        raise WorkflowError(f"Malformed active TeX input in {resolved}.") from exc
    pieces: list[str] = []
    cursor = 0
    for command in commands:
        pieces.append(text[cursor : command.start])
        original = text[command.start : command.end]
        pieces.append(replace_input(command.fields[0], original))
        cursor = command.end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _copy_resources(config: ProjectConfig, target: Path) -> None:
    stage_runtime_resources(
        config,
        config.current_round,
        target,
        include_manuscript=False,
    )


def _diff_field(text: str, start: int) -> tuple[str, int]:
    try:
        return extract_braced(text, start)
    except ValueError as exc:
        raise WorkflowError(
            "Unbalanced braces while processing revision diff output."
        ) from exc


def _split_diff_segments(text: str) -> list[_DiffSegment]:
    macros = (
        (r"\DIFaddReviewFL", "add-review"),
        (r"\DIFaddReview", "add-review"),
        (r"\DIFaddFL", "add"),
        (r"\DIFdelFL", "del"),
        (r"\DIFadd", "add"),
        (r"\DIFdel", "del"),
    )
    segments: list[_DiffSegment] = []
    cursor = 0
    while cursor < len(text):
        candidates: list[tuple[int, str, str]] = []
        for macro, kind in macros:
            index = text.find(f"{macro}{{", cursor)
            if index >= 0:
                candidates.append((index, macro, kind))
        if not candidates:
            segments.append(_DiffSegment("plain", text[cursor:]))
            break
        index, macro, kind = min(candidates, key=lambda item: item[0])
        if index > cursor:
            segments.append(_DiffSegment("plain", text[cursor:index]))
        content, end = _diff_field(text, index + len(macro))
        segments.append(_DiffSegment(kind, content, macro))
        cursor = end
    return segments


def _separator_is_diff_only(text: str) -> bool:
    stripped = DIF_COMMENT_PATTERN.sub("", text)
    stripped = DIF_CONTROL_PATTERN.sub("", stripped)
    return not stripped.strip()


def _character_refinement_matcher(old: str, new: str) -> SequenceMatcher[str] | None:
    """Return a matcher only for bounded, structurally safe, similar prose."""
    unsafe = set(r"\{}$%&#_^~")
    if any(char in unsafe for char in old + new):
        return None
    if max(len(old), len(new)) > MAX_CHARACTER_REFINEMENT_CHARS:
        return None
    matcher = SequenceMatcher(a=old, b=new, autojunk=False)
    if matcher.ratio() < CHARACTER_REFINEMENT_THRESHOLD:
        return None
    return matcher


def _safe_character_refinement(old: str, new: str) -> bool:
    """Return whether a replacement is eligible for character refinement."""
    return _character_refinement_matcher(old, new) is not None


class _AdditionLocator:
    """Map latexdiff additions back to exact offsets in the clean new source."""

    def __init__(self, source: ProvenanceSource) -> None:
        self.source = source
        self.cursor = 0

    def locate(self, content: str) -> tuple[int, int]:
        if not content:
            return self.cursor, self.cursor
        index = self.source.text.find(content, self.cursor)
        if index < 0:
            sample = " ".join(content.strip().split())[:120]
            raise WorkflowError(
                "Could not map a latexdiff addition back to the provenance-free "
                f"revision source: {sample!r}."
            )
        end = index + len(content)
        self.cursor = end
        return index, end


def _render_addition(
    provenance: ProvenanceSource,
    start: int,
    end: int,
    *,
    full_document: bool,
) -> str:
    pieces: list[str] = []
    for left, right, owner in split_by_review_provenance(provenance, start, end):
        content = provenance.text[left:right]
        if not content:
            continue
        if content.isspace():
            pieces.append(content)
            continue
        if owner:
            macro = r"\DIFaddReviewFL" if full_document else r"\DIFaddReview"
        else:
            macro = r"\DIFaddFL" if full_document else r"\DIFadd"
        pieces.append(f"{macro}{{{content}}}")
    return "".join(pieces)


def _refine_replacement(
    old: str,
    new: str,
    provenance: ProvenanceSource,
    new_start: int,
    matcher: SequenceMatcher[str],
    *,
    full_document: bool,
) -> str:
    pieces: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pieces.append(new[j1:j2])
            continue
        if tag in {"delete", "replace"} and i1 != i2:
            macro = r"\DIFdelFL" if full_document else r"\DIFdel"
            pieces.append(f"{macro}{{{old[i1:i2]}}}")
        if tag in {"insert", "replace"} and j1 != j2:
            pieces.append(
                _render_addition(
                    provenance,
                    new_start + j1,
                    new_start + j2,
                    full_document=full_document,
                )
            )
    return "".join(pieces)


def _replacement_shape(
    segments: list[_DiffSegment],
    index: int,
) -> tuple[int, str] | None:
    """Return the addition index and ignorable separator for one replacement."""
    if segments[index].kind != "del" or index + 1 >= len(segments):
        return None
    if segments[index + 1].kind == "add":
        return index + 1, ""
    if (
        index + 2 < len(segments)
        and segments[index + 1].kind == "plain"
        and segments[index + 2].kind == "add"
        and _separator_is_diff_only(segments[index + 1].content)
    ):
        return index + 2, segments[index + 1].content
    return None


def _classify_region(
    text: str,
    provenance: ProvenanceSource,
    locator: _AdditionLocator,
) -> str:
    """Classify one real manuscript region, excluding generated diff style."""
    segments = _split_diff_segments(text)
    output: list[str] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        replacement = _replacement_shape(segments, index)
        if replacement is not None:
            addition_index, separator = replacement
            addition = segments[addition_index]
            start, end = locator.locate(addition.content)
            full_document = addition.macro.endswith("FL")
            matcher = _character_refinement_matcher(segment.content, addition.content)
            if matcher is not None:
                output.append(
                    _refine_replacement(
                        segment.content,
                        addition.content,
                        provenance,
                        start,
                        matcher,
                        full_document=full_document,
                    )
                )
            else:
                output.append(f"{segment.macro}{{{segment.content}}}")
                output.append(separator)
                output.append(
                    _render_addition(
                        provenance,
                        start,
                        end,
                        full_document=full_document,
                    )
                )
            index = addition_index + 1
            continue

        if segment.kind == "add":
            start, end = locator.locate(segment.content)
            output.append(
                _render_addition(
                    provenance,
                    start,
                    end,
                    full_document=segment.macro.endswith("FL"),
                )
            )
        elif segment.kind == "add-review":
            raise WorkflowError(
                "Reviewer-specific diff markup appeared before provenance "
                "classification; the diff engine must remain provenance-free."
            )
        elif segment.kind == "del":
            output.append(f"{segment.macro}{{{segment.content}}}")
        else:
            output.append(segment.content)
        index += 1
    return "".join(output)


def _classify_reviewer_additions(
    latexdiff_output: str,
    provenance: ProvenanceSource,
) -> str:
    """Classify additions everywhere, including Chinese pre-document frontmatter."""
    start = latexdiff_output.find(STYLE_BEGIN)
    end = latexdiff_output.find(STYLE_END)
    locator = _AdditionLocator(provenance)
    if start < 0 and end < 0:
        return _classify_region(latexdiff_output, provenance, locator)
    if start < 0 or end < 0 or end < start:
        raise WorkflowError("Marked diff style boundaries are incomplete.")
    style_end = end + len(STYLE_END)
    prefix = latexdiff_output[:start]
    style = latexdiff_output[start:style_end]
    suffix = latexdiff_output[style_end:]
    return (
        _classify_region(prefix, provenance, locator)
        + style
        + _classify_region(suffix, provenance, locator)
    )


def _find_inline_math_end(text: str, start: int) -> int | None:
    if text.startswith("$$", start):
        delimiter = "$$"
        cursor = start + 2
    elif text[start] == "$":
        delimiter = "$"
        cursor = start + 1
    elif text.startswith(r"\(", start):
        delimiter = r"\)"
        cursor = start + 2
    else:
        return None
    while cursor < len(text):
        if text.startswith(delimiter, cursor) and not is_escaped(text, cursor):
            return cursor + len(delimiter)
        cursor += 1
    raise WorkflowError("Unbalanced inline mathematics in revision diff markup.")


def _split_inline_math(content: str, macro: str) -> str:
    if macro in {r"\DIFaddReview", r"\DIFaddReviewFL"}:
        math_macro = r"\DIFaddReviewMath"
    elif macro in {r"\DIFadd", r"\DIFaddFL"}:
        math_macro = r"\DIFaddMath"
    else:
        math_macro = r"\DIFdelMath"
    pieces: list[str] = []
    plain_start = 0
    cursor = 0
    found = False
    while cursor < len(content):
        if content[cursor] == "%" and not is_escaped(content, cursor):
            newline = content.find("\n", cursor)
            cursor = len(content) if newline == -1 else newline + 1
            continue
        is_math = (
            content[cursor] == "$" and not is_escaped(content, cursor)
        ) or content.startswith(r"\(", cursor)
        if not is_math:
            cursor += 1
            continue
        end = _find_inline_math_end(content, cursor)
        if end is None:
            cursor += 1
            continue
        plain = content[plain_start:cursor]
        if plain:
            pieces.append(plain if plain.isspace() else f"{macro}{{{plain}}}")
        if content.startswith("$$", cursor):
            left = right = "$$"
        elif content[cursor] == "$":
            left = right = "$"
        else:
            left, right = r"\(", r"\)"
        body = content[cursor + len(left) : end - len(right)]
        pieces.append(f"{left}{math_macro}{{{body}}}{right}")
        cursor = end
        plain_start = end
        found = True
    if not found:
        return f"{macro}{{{content}}}"
    plain = content[plain_start:]
    if plain:
        pieces.append(plain if plain.isspace() else f"{macro}{{{plain}}}")
    return "".join(pieces)


def _separate_inline_math_from_diff_markup(text: str) -> str:
    macros = (
        r"\DIFaddReviewFL",
        r"\DIFaddReview",
        r"\DIFaddFL",
        r"\DIFdelFL",
        r"\DIFadd",
        r"\DIFdel",
    )
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        candidates = [(text.find(f"{macro}{{", cursor), macro) for macro in macros]
        matches = [item for item in candidates if item[0] >= 0]
        if not matches:
            output.append(text[cursor:])
            break
        index, macro = min(matches, key=lambda item: item[0])
        output.append(text[cursor:index])
        content, end = _diff_field(text, index + len(macro))
        output.append(_split_inline_math(content, macro))
        cursor = end
    return "".join(output)


def build_marked_manuscript(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None = None,
) -> MarkedResult:
    """Build an adjacent revision diff with reviewer provenance classified in Python."""
    if round_number < 1:
        raise WorkflowError("R0 has no marked manuscript; build its clean PDF instead.")
    previous = config.round_dir(round_number - 1)
    current = config.round_dir(round_number)
    if not previous.is_dir() or not current.is_dir():
        raise WorkflowError(
            f"Revision requires both r{round_number - 1} and r{round_number}."
        )
    if shutil.which("latexdiff") is None:
        raise WorkflowError("latexdiff is required for structural LaTeX comparison.")
    if shutil.which("pdftotext") is None:
        raise WorkflowError("pdftotext is required for marked-manuscript validation.")

    source_dir = run_dir / "marked_source"
    build_dir = run_dir / "marked_build"
    source_dir.mkdir(parents=True)
    old_runtime = source_dir / "old_runtime"
    new_runtime = source_dir / "new_runtime"
    old_runtime_source = stage_runtime_resources(
        config,
        round_number - 1,
        old_runtime,
        include_manuscript=True,
    )
    new_runtime_source = stage_runtime_resources(
        config,
        round_number,
        new_runtime,
        include_manuscript=True,
    )
    old_flattened = _flatten_tex(
        old_runtime_source,
        (old_runtime,),
    )
    new_flattened = _flatten_tex(
        new_runtime_source,
        (new_runtime,),
    )
    old_bibliography = _materialize_bibliography(
        old_runtime_source,
        old_flattened,
        run_dir / "old_bibliography_build",
        config,
        engine_override,
    )
    new_bibliography = _materialize_bibliography(
        new_runtime_source,
        new_flattened,
        run_dir / "new_bibliography_build",
        config,
        engine_override,
    )
    aligned_old_bibliography, aligned_new_bibliography = _align_bibliographies(
        old_bibliography,
        new_bibliography,
    )
    old_visible = _replace_bibliography(old_flattened, aligned_old_bibliography)
    new_visible = _replace_bibliography(new_flattened, aligned_new_bibliography)
    old_visible, new_visible = _align_changed_display_equations(
        old_visible,
        new_visible,
    )
    old_text = strip_provenance_wrappers(old_visible)
    provenance = extract_provenance(new_visible)
    old_source = source_dir / "old.tex"
    new_source = source_dir / "new.tex"
    old_source.write_text(old_text, encoding="utf-8")
    new_source.write_text(provenance.text, encoding="utf-8")

    style = source_dir / "revision_preamble.tex"
    user_style = (config.references / "revision_style.tex").read_text(encoding="utf-8")
    style.write_text(
        f"{STYLE_BEGIN}\n{user_style}\n{_revision_runtime(config.language)}\n{STYLE_END}\n",
        encoding="utf-8",
    )
    _copy_resources(config, source_dir)

    text_commands = ["SCIDeletedBibItem", "SCIDeletedEquation"]
    if config.metadata.publisher == "chinese":
        text_commands.extend(CHINESE_TEXT_COMMANDS)
    command = [
        shutil.which("latexdiff") or "latexdiff",
        "--encoding=utf8",
        "--packages=none",
        "--math-markup=WHOLE",
        f"--preamble={style}",
        "--append-context2cmd=" + ",".join(PUBLISHER_METADATA_CONTEXT_COMMANDS),
        "--append-textcmd=" + ",".join(text_commands),
        "--append-safecmd=latin,nolinkurl",
        "--disable-citation-markup",
        "--ignore-warnings",
        str(old_source),
        str(new_source),
    ]
    result = run_command(command, cwd=source_dir)
    classified = _classify_reviewer_additions(result.stdout, provenance)
    marked_source = source_dir / "manuscript_marked.tex"
    marked_source.write_text(
        _separate_inline_math_from_diff_markup(classified), encoding="utf-8"
    )
    compiled = compile_tex(
        marked_source,
        build_dir,
        config,
        engine_override,
        keep_intermediates=True,
    )

    extracted_text = run_dir / "marked_manuscript.txt"
    run_command(
        [
            shutil.which("pdftotext") or "pdftotext",
            str(compiled.pdf),
            str(extracted_text),
        ],
        cwd=run_dir,
    )
    if not extracted_text.exists() or extracted_text.stat().st_size == 0:
        raise WorkflowError("Marked PDF text extraction produced no text.")

    locations = build_review_locations(
        config,
        round_number,
        run_dir,
        engine_override,
    )
    output = config.output_dir(round_number) / "manuscript_marked.pdf"
    publish_file_atomically(compiled.pdf, output)
    return MarkedResult(pdf=output, locations=locations)
