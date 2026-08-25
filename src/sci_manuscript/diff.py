"""Deterministic revision diffing, provenance classification, and marked output."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .compile import compile_tex, run_command, stage_runtime_resources
from .errors import WorkflowError
from .locations import build_review_locations
from .metadata import generate_metadata
from .provenance import ProvenanceSource, extract_provenance, split_by_review_provenance
from .templates import resources_root
from .tex import extract_braced, is_commented, is_escaped
from .workspace import ProjectConfig, strip_provenance_wrappers

INPUT_PATTERN = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
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

    def replace_input(match: re.Match[str]) -> str:
        if is_commented(text, match.start()):
            return match.group(0)
        name = match.group(1).strip()
        if name == "preamble" or name.startswith("preamble/"):
            return match.group(0)
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
            return match.group(0)
        nested = _flatten_tex(candidate, roots, (*active, resolved))
        return f"\n% BEGIN INPUT {name}\n{nested}\n% END INPUT {name}\n"

    return INPUT_PATTERN.sub(replace_input, text)


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


def _math_atoms(body: str) -> list[str] | None:
    """Split math into command/group-safe atoms for conservative refinement."""
    atoms: list[str] = []
    cursor = 0
    while cursor < len(body):
        if body[cursor] == "{":
            try:
                _, end = _diff_field(body, cursor)
            except WorkflowError:
                return None
            atoms.append(body[cursor:end])
            cursor = end
            continue
        if body[cursor] == "}":
            return None
        if body[cursor] == "\\":
            end = cursor + 1
            if end < len(body) and body[end].isalpha():
                while end < len(body) and body[end].isalpha():
                    end += 1
                if end < len(body) and body[end] == "*":
                    end += 1
            elif end < len(body):
                end += 1
            atoms.append(body[cursor:end])
            cursor = end
            continue
        atoms.append(body[cursor])
        cursor += 1
    return atoms


def _unwrap_inline_math(value: str) -> tuple[str, str, str] | None:
    for left, right in (("$$", "$$"), ("$", "$"), (r"\(", r"\)")):
        if value.startswith(left) and value.endswith(right):
            return left, value[len(left) : len(value) - len(right)], right
    return None


def _render_inline_math_refinement(
    old: str,
    new: str,
    addition_macro: str,
) -> str | None:
    old_math = _unwrap_inline_math(old)
    new_math = _unwrap_inline_math(new)
    if old_math is None or new_math is None or old_math[::2] != new_math[::2]:
        return None
    old_atoms = _math_atoms(old_math[1])
    new_atoms = _math_atoms(new_math[1])
    if old_atoms is None or new_atoms is None:
        return None
    matcher = SequenceMatcher(a=old_atoms, b=new_atoms, autojunk=False)
    pieces = [old_math[0]]
    add = r"\DIFaddReview" if "Review" in addition_macro else r"\DIFadd"
    changed = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pieces.extend(new_atoms[j1:j2])
            continue
        changed = True
        if tag in {"delete", "replace"}:
            pieces.append(f"\\DIFdel{{{''.join(old_atoms[i1:i2])}}}")
        if tag in {"insert", "replace"}:
            pieces.append(f"{add}{{{''.join(new_atoms[j1:j2])}}}")
    pieces.append(old_math[2])
    return "".join(pieces) if changed else new


def _refine_inline_math_replacements(text: str) -> str:
    """Refine paired inline-math replacements without crossing TeX groups."""
    deleted_macro = r"\DIFdelMath"
    additions = (r"\DIFaddReviewMath", r"\DIFaddMath")
    output: list[str] = []
    cursor = 0
    while True:
        start = text.find(f"{deleted_macro}{{", cursor)
        if start < 0:
            output.append(text[cursor:])
            break
        old, old_end = _diff_field(text, start + len(deleted_macro))
        old_wrapper = _math_macro_wrapper(text, start, old_end)
        if old_wrapper is None:
            output.append(text[cursor:old_end])
            cursor = old_end
            continue
        old_start, old_left, old_right, old_finish = old_wrapper
        candidates = [(text.find(f"{macro}{{", old_end), macro) for macro in additions]
        candidates = [item for item in candidates if item[0] >= 0]
        if not candidates:
            output.append(text[cursor:])
            break
        add_start, add_macro = min(candidates)
        new, add_end = _diff_field(text, add_start + len(add_macro))
        add_wrapper = _math_macro_wrapper(text, add_start, add_end)
        if add_wrapper is None:
            output.append(text[cursor:old_finish])
            cursor = old_finish
            continue
        new_start, new_left, new_right, new_finish = add_wrapper
        separator = text[old_finish:new_start]
        if not _separator_is_diff_only(separator):
            output.append(text[cursor:old_finish])
            cursor = old_finish
            continue
        refined = _render_inline_math_refinement(
            f"{old_left}{old}{old_right}",
            f"{new_left}{new}{new_right}",
            add_macro,
        )
        if refined is None:
            output.append(text[cursor:old_finish])
            cursor = old_finish
            continue
        output.extend((text[cursor:old_start], refined))
        cursor = new_finish
    return "".join(output)


def _math_macro_wrapper(
    text: str,
    macro_start: int,
    macro_end: int,
) -> tuple[int, str, str, int] | None:
    """Return delimiters surrounding one inline Math macro call."""
    for left, right in (("$$", "$$"), ("$", "$"), (r"\(", r"\)")):
        start = macro_start - len(left)
        if start < 0 or text[start:macro_start] != left:
            continue
        if text[macro_end : macro_end + len(right)] != right:
            continue
        return start, left, right, macro_end + len(right)
    return None


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
    generate_metadata(previous, old_runtime)
    generate_metadata(current, new_runtime)
    old_text = strip_provenance_wrappers(
        _flatten_tex(
            previous / "manuscript.tex",
            (previous, old_runtime, config.project),
        )
    )
    provenance = extract_provenance(
        _flatten_tex(
            current / "manuscript.tex",
            (current, new_runtime, config.project),
        )
    )
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

    command = [
        shutil.which("latexdiff") or "latexdiff",
        "--encoding=utf8",
        "--packages=none",
        "--math-markup=FINE",
        f"--preamble={style}",
        "--append-context2cmd=" + ",".join(PUBLISHER_METADATA_CONTEXT_COMMANDS),
        "--disable-citation-markup",
        "--ignore-warnings",
        str(old_source),
        str(new_source),
    ]
    if config.metadata.publisher == "chinese":
        command.insert(-3, f"--append-textcmd={','.join(CHINESE_TEXT_COMMANDS)}")
    result = run_command(command, cwd=source_dir)
    classified = _classify_reviewer_additions(result.stdout, provenance)
    marked_source = source_dir / "manuscript_marked.tex"
    separated = _separate_inline_math_from_diff_markup(classified)
    marked_source.write_text(
        _refine_inline_math_replacements(separated), encoding="utf-8"
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
    output.parent.mkdir(exist_ok=True)
    shutil.copy2(compiled.pdf, output)
    return MarkedResult(pdf=output, locations=locations)
