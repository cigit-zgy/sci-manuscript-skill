"""Deterministic revision diffing, provenance classification, and marked output."""

from __future__ import annotations

import collections
import re
import shutil
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .compile import compile_tex, run_command, stage_runtime_resources
from .provenance import ProvenanceSource, extract_provenance, split_by_review_provenance
from .response import is_review_id
from .workspace import ProjectConfig, WorkflowError, strip_provenance_wrappers

INPUT_PATTERN = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
LABEL_PATTERN = re.compile(r"\\newlabel\{review:(\d+):(start|end)\}\{\{(\d+)\}")
DIF_COMMENT_PATTERN = re.compile(r"(?m)^%DIF[^\n]*(?:\n|$)")
DIF_CONTROL_PATTERN = re.compile(r"\\DIF(?:add|del|mod)(?:begin|end)(?:FL)?\s*")
REVIEW_REGISTRY_HEADER = "sci-manuscript-reviewloc-v2"
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

_REVISION_RUNTIME_TEMPLATE = r"""
% Internal marked-manuscript runtime. Reviewer provenance has already been
% classified in Python; TeX only renders deterministic semantic macros.
\RequirePackage{lineno}
\RequirePackage[normalem]{ulem}
%%CJK_REVISION_PACKAGE%%
\RequirePackage{xcolor}
\AtBeginDocument{\linenumbers}

\newbox\RevisionMathMeasureBox
\newcommand{\RevisionMathStyle}{\ifinner\textstyle\else\displaystyle\fi}
\newcommand{\RevisionGobble}[1]{}
\newcommand{\RevisionMeasureMath}[1]{%
  \setbox\RevisionMathMeasureBox=\hbox{\mathsurround=0pt$\RevisionMathStyle
    \let\label\RevisionGobble #1$}%
}
\newcommand{\RevisionMathStrikeout}[2]{%
  \begingroup
    \RevisionMeasureMath{#2}%
    \dimen0=.5\ht\RevisionMathMeasureBox
    \advance\dimen0 by -.5\dp\RevisionMathMeasureBox
    \rlap{\raise\dimen0\hbox{\color{#1}%
      \rule{\wd\RevisionMathMeasureBox}{\RevisionDeletionThickness}}}%
    {\color{#1}#2}%
  \endgroup
}
\providecommand{\DIFaddMath}[1]{%
  {\RevisionAddedFont\color{RevisionAddedColor}#1}%
}
\providecommand{\DIFaddReviewMath}[1]{%
  {\RevisionReviewFont\color{RevisionReviewColor}#1}%
}
\providecommand{\DIFdelMath}[1]{%
  {\RevisionDeletedFont\RevisionMathStrikeout{RevisionDeletedColor}{#1}}%
}
\providecommand{\DIFadd}[1]{%
  \ifmmode
    \DIFaddMath{#1}%
  \else
    \RevisionAddedBackground{{\RevisionAddedFont\color{RevisionAddedColor}#1}}%
  \fi}
\providecommand{\DIFaddReview}[1]{%
  \ifmmode
    \DIFaddReviewMath{#1}%
  \else
    \RevisionReviewBackground{{\RevisionReviewFont\color{RevisionReviewColor}#1}}%
  \fi}
\providecommand{\DIFdel}[1]{%
  \ifmmode
    \DIFdelMath{#1}%
  \else
    \RevisionDeletedBackground{{\RevisionDeletedFont\color{RevisionDeletedColor}%
      \RevisionDeletedStrikeout{#1}}}%
  \fi}
\providecommand{\DIFaddbegin}{}
\providecommand{\DIFaddend}{}
\providecommand{\DIFdelbegin}{}
\providecommand{\DIFdelend}{}
\providecommand{\DIFmodbegin}{}
\providecommand{\DIFmodend}{}
\providecommand{\DIFaddFL}[1]{\DIFadd{#1}}
\providecommand{\DIFaddReviewFL}[1]{\DIFaddReview{#1}}
\providecommand{\DIFdelFL}[1]{\DIFdel{#1}}
\providecommand{\DIFaddbeginFL}{}
\providecommand{\DIFaddendFL}{}
\providecommand{\DIFdelbeginFL}{}
\providecommand{\DIFdelendFL}{}
\providecommand{\review}[2]{#2}
\providecommand{\user}[1]{#1}
\providecommand{\selfadd}[1]{#1}

% Keep the historical empty registry contract for standalone runtime probes.
% Real reviewer locations are compiled independently and copied over this file.
\newwrite\MarkedReviewLocationFile
\AtBeginDocument{%
  \immediate\openout\MarkedReviewLocationFile=\jobname.reviewloc
  \immediate\write\MarkedReviewLocationFile{sci-manuscript-reviewloc-v2}%
}
\AtEndDocument{\immediate\closeout\MarkedReviewLocationFile}
"""

_LOCATION_RUNTIME = rf"""
% Internal reviewer-location runtime. It never changes text color.
\RequirePackage{{lineno}}
\AtBeginDocument{{\linenumbers}}
\newcounter{{reviewblock}}
\newwrite\ReviewLocationFile
\AtBeginDocument{{%
  \immediate\openout\ReviewLocationFile=\jobname.reviewloc
  \immediate\write\ReviewLocationFile{{{REVIEW_REGISTRY_HEADER}}}%
}}
\AtEndDocument{{\immediate\closeout\ReviewLocationFile}}
\newcommand{{\ReviewLineLabel}}[1]{{%
  \begingroup
  \edef\ReviewExpandedLabel{{#1}}%
  \expandafter\endgroup
  \expandafter\linelabel\expandafter{{\ReviewExpandedLabel}}%
}}
\providecommand{{\review}}[2]{{#2}}
\providecommand{{\user}}[1]{{#1}}
\providecommand{{\selfadd}}[1]{{#1}}
\AtBeginDocument{{%
  \renewcommand{{\review}}[2]{{%
    \stepcounter{{reviewblock}}%
    \edef\ReviewBlockID{{\arabic{{reviewblock}}}}%
    \leavevmode
    \ReviewLineLabel{{review:\ReviewBlockID:start}}%
    #2%
    \ReviewLineLabel{{review:\ReviewBlockID:end}}%
    \immediate\write\ReviewLocationFile{{#1|\ReviewBlockID}}%
  }}%
  \renewcommand{{\user}}[1]{{#1}}%
  \renewcommand{{\selfadd}}[1]{{#1}}%
}}
"""

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


def _is_escaped(text: str, index: int) -> bool:
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def _extract_braced(text: str, start: int) -> tuple[str, int]:
    if start >= len(text) or text[start] != "{":
        raise WorkflowError("Internal diff parser expected an opening brace.")
    depth = 0
    cursor = start
    while cursor < len(text):
        char = text[cursor]
        if char == "%" and not _is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        if char == "{" and not _is_escaped(text, cursor):
            depth += 1
        elif char == "}" and not _is_escaped(text, cursor):
            depth -= 1
            if depth == 0:
                return text[start + 1 : cursor], cursor + 1
        cursor += 1
    raise WorkflowError("Unbalanced braces while processing revision diff output.")


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
        content, end = _extract_braced(text, index + len(macro))
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
        if text.startswith(delimiter, cursor) and not _is_escaped(text, cursor):
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
        if content[cursor] == "%" and not _is_escaped(content, cursor):
            newline = content.find("\n", cursor)
            cursor = len(content) if newline == -1 else newline + 1
            continue
        is_math = (
            content[cursor] == "$" and not _is_escaped(content, cursor)
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
        pieces.append(f"{math_macro}{{{content[cursor:end]}}}")
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
        content, end = _extract_braced(text, index + len(macro))
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
                _, end = _extract_braced(body, cursor)
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
        old, old_end = _extract_braced(text, start + len(deleted_macro))
        candidates = [(text.find(f"{macro}{{", old_end), macro) for macro in additions]
        candidates = [item for item in candidates if item[0] >= 0]
        if not candidates:
            output.append(text[cursor:])
            break
        add_start, add_macro = min(candidates)
        separator = text[old_end:add_start]
        if not _separator_is_diff_only(separator):
            output.append(text[cursor:old_end])
            cursor = old_end
            continue
        new, add_end = _extract_braced(text, add_start + len(add_macro))
        refined = _render_inline_math_refinement(old, new, add_macro)
        if refined is None:
            output.append(text[cursor:old_end])
            cursor = old_end
            continue
        output.extend((text[cursor:start], refined))
        cursor = add_end
    return "".join(output)


def _parse_registry(path: Path) -> list[tuple[str, int]]:
    if not path.exists():
        raise WorkflowError(f"Location build did not create a review registry: {path}")
    records: list[tuple[str, int]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or (number == 1 and line == REVIEW_REGISTRY_HEADER):
            continue
        fields = line.split("|")
        if len(fields) != 2 or not fields[1].isdigit():
            raise WorkflowError(f"Malformed review registry at line {number}: {raw}")
        records.append((fields[0], int(fields[1])))
    return records


def _parse_labels(path: Path) -> dict[tuple[int, str], int]:
    if not path.exists():
        raise WorkflowError(
            f"Location build did not create a line-number AUX file: {path}"
        )
    labels: dict[tuple[int, str], int] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for block, edge, line in LABEL_PATTERN.findall(text):
        labels[(int(block), edge)] = int(line)
    return labels


def _format_locations(ranges: list[tuple[int, int]], language: str) -> str:
    """Format line ranges as one complete Chinese or English phrase."""
    if not ranges:
        return "位置不可用" if language == "zh" else "Location unavailable"
    if language == "zh":
        parts = [
            f"第 {start if start == end else f'{start}--{end}'} 行"
            for start, end in ranges
        ]
        if len(parts) == 1:
            return parts[0]
        return (
            "和".join(parts)
            if len(parts) == 2
            else "、".join(parts[:-1]) + "和" + parts[-1]
        )
    values = [
        str(start) if start == end else f"{start}--{end}" for start, end in ranges
    ]
    if len(values) == 1:
        prefix = "Line" if ranges[0][0] == ranges[0][1] else "Lines"
        return f"{prefix} {values[0]}"
    joined = (
        f"{values[0]} and {values[1]}"
        if len(values) == 2
        else f"{', '.join(values[:-1])}, and {values[-1]}"
    )
    return f"Lines {joined}"


def _calculate_locations(
    build_dir: Path,
    stem: str = "manuscript_marked",
    language: str = "en",
) -> dict[str, str]:
    registry = _parse_registry(build_dir / f"{stem}.reviewloc")
    labels = _parse_labels(build_dir / f"{stem}.aux")
    by_comment: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    for ids, block in registry:
        start = labels.get((block, "start"))
        end = labels.get((block, "end"))
        if start is None or end is None:
            raise WorkflowError(f"Line labels are missing for reviewer block {block}.")
        location = (start, end)
        for review_id in (item.strip() for item in ids.split(",")):
            if not is_review_id(review_id):
                raise WorkflowError(
                    f"Invalid reviewer ID {review_id!r}; expected E-1 or 1-1."
                )
            if location not in by_comment[review_id]:
                by_comment[review_id].append(location)
    return {
        key: _format_locations(value, language) for key, value in by_comment.items()
    }


def _build_review_locations(
    config: ProjectConfig,
    round_number: int,
    run_dir: Path,
    engine_override: str | None,
) -> dict[str, str]:
    """Compile transparent review wrappers solely to calculate response locations."""
    source_dir = run_dir / "location_source"
    source = stage_runtime_resources(
        config,
        round_number,
        source_dir,
        include_manuscript=True,
    )
    runtime = source_dir / "revision_location_runtime.tex"
    runtime.write_text(_LOCATION_RUNTIME, encoding="utf-8")
    text = source.read_text(encoding="utf-8")
    marker = r"\begin{document}"
    if marker not in text:
        raise WorkflowError("Manuscript source does not contain \\begin{document}.")
    source.write_text(
        text.replace(marker, f"\\input{{revision_location_runtime.tex}}\n{marker}", 1),
        encoding="utf-8",
    )
    build_dir = run_dir / "location_build"
    compile_tex(
        source,
        build_dir,
        config,
        engine_override,
        keep_intermediates=True,
    )
    locations = _calculate_locations(build_dir, source.stem, config.language)

    # Preserve the historical retained-run paths for downstream diagnostics.
    marked_build = run_dir / "marked_build"
    marked_build.mkdir(exist_ok=True)
    for suffix in ("reviewloc", "aux"):
        candidate = build_dir / f"{source.stem}.{suffix}"
        if candidate.exists():
            shutil.copy2(candidate, marked_build / f"manuscript_marked.{suffix}")
    return locations


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
    roots = (previous, current, config.project)
    old_text = strip_provenance_wrappers(
        _flatten_tex(previous / "manuscript.tex", roots)
    )
    provenance = extract_provenance(_flatten_tex(current / "manuscript.tex", roots))
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

    locations = _build_review_locations(
        config,
        round_number,
        run_dir,
        engine_override,
    )
    output = current / "output" / "manuscript_marked.pdf"
    output.parent.mkdir(exist_ok=True)
    shutil.copy2(compiled.pdf, output)
    return MarkedResult(pdf=output, locations=locations)
