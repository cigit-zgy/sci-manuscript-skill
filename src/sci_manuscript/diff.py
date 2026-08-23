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
DIF_CONTROL_PATTERN = re.compile(
    r"\\DIF(?:add|del|mod)(?:begin|end)(?:FL)?\s*"
)
REVIEW_REGISTRY_HEADER = "sci-manuscript-reviewloc-v2"
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

\providecommand{\DIFaddMath}[1]{%
  {\RevisionAddedFont\color{RevisionAddedColor}#1}%
}
\providecommand{\DIFaddReviewMath}[1]{%
  {\RevisionReviewFont\color{RevisionReviewColor}#1}%
}
\newbox\DIFdelDisplayMathBox
\providecommand{\DIFdelMath}[1]{%
  \ifmmode
    \begingroup
      \setbox\DIFdelDisplayMathBox=\hbox{$\displaystyle\RevisionDeletedFont
        \color{RevisionDeletedColor}#1$}%
      \dimen0=.5\ht\DIFdelDisplayMathBox
      \advance\dimen0 by -.5\dp\DIFdelDisplayMathBox
      \rlap{\raise\dimen0\hbox{\color{RevisionDeletedColor}%
        \rule{\wd\DIFdelDisplayMathBox}{0.6pt}}}%
      \box\DIFdelDisplayMathBox
    \endgroup
  \else
    \begingroup
      \setbox\DIFdelDisplayMathBox=\hbox{{\RevisionDeletedFont
        \color{RevisionDeletedColor}#1}}%
      \dimen0=.5\ht\DIFdelDisplayMathBox
      \advance\dimen0 by -.5\dp\DIFdelDisplayMathBox
      \rlap{\raise\dimen0\hbox{\color{RevisionDeletedColor}%
        \rule{\wd\DIFdelDisplayMathBox}{0.6pt}}}%
      \box\DIFdelDisplayMathBox
    \endgroup
  \fi}
\providecommand{\DIFadd}[1]{%
  \ifmmode
    \DIFaddMath{#1}%
  \else
    \RevisionAddedBackground{{\RevisionAddedFont\color{RevisionAddedColor}%
      \RevisionAddedUnderline{#1}}}%
  \fi}
\providecommand{\DIFaddReview}[1]{%
  \ifmmode
    \DIFaddReviewMath{#1}%
  \else
    \RevisionReviewBackground{{\RevisionReviewFont\color{RevisionReviewColor}%
      \RevisionReviewUnderline{#1}}}%
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


def _copy_resources(config: ProjectConfig, round_dir: Path, target: Path) -> None:
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


def _safe_character_refinement(old: str, new: str) -> bool:
    """Restrict character-level refinement to prose, never TeX structure."""
    unsafe = set(r"\{}$%&#_^~")
    return not any(char in unsafe for char in old + new)


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
    *,
    full_document: bool,
) -> str:
    matcher = SequenceMatcher(a=old, b=new, autojunk=False)
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


def _classify_body_additions(body: str, provenance: ProvenanceSource) -> str:
    """Classify actual additions using a sidecar provenance map.

    Reviewer wrappers never enter latexdiff. Pure-prose replacement blocks are
    refined at Unicode-character granularity so unchanged Chinese text remains
    unmarked even when latexdiff reports a coarse replacement.
    """
    segments = _split_diff_segments(body)
    locator = _AdditionLocator(provenance)
    output: list[str] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        if (
            segment.kind == "del"
            and index + 2 < len(segments)
            and segments[index + 1].kind == "plain"
            and segments[index + 2].kind == "add"
            and _separator_is_diff_only(segments[index + 1].content)
        ):
            addition = segments[index + 2]
            start, end = locator.locate(addition.content)
            full_document = addition.macro.endswith("FL")
            if _safe_character_refinement(segment.content, addition.content):
                output.append(
                    _refine_replacement(
                        segment.content,
                        addition.content,
                        provenance,
                        start,
                        full_document=full_document,
                    )
                )
            else:
                output.append(f"{segment.macro}{{{segment.content}}}")
                output.append(segments[index + 1].content)
                output.append(
                    _render_addition(
                        provenance,
                        start,
                        end,
                        full_document=full_document,
                    )
                )
            index += 3
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
    marker = r"\begin{document}"
    index = latexdiff_output.find(marker)
    if index < 0:
        raise WorkflowError("latexdiff output does not contain \\begin{document}.")
    body_start = index + len(marker)
    return (
        latexdiff_output[:body_start]
        + _classify_body_additions(latexdiff_output[body_start:], provenance)
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
    marker = r"\begin{document}"
    marker_index = text.find(marker)
    if marker_index < 0:
        return text
    body_start = marker_index + len(marker)
    prefix = text[:body_start]
    body = text[body_start:]
    output: list[str] = []
    cursor = 0
    while cursor < len(body):
        candidates = [(body.find(f"{macro}{{", cursor), macro) for macro in macros]
        matches = [item for item in candidates if item[0] >= 0]
        if not matches:
            output.append(body[cursor:])
            break
        index, macro = min(matches, key=lambda item: item[0])
        output.append(body[cursor:index])
        content, end = _extract_braced(body, index + len(macro))
        output.append(_split_inline_math(content, macro))
        cursor = end
    return prefix + "".join(output)


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
        raise WorkflowError(f"Location build did not create a line-number AUX file: {path}")
    labels: dict[tuple[int, str], int] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for block, edge, line in LABEL_PATTERN.findall(text):
        labels[(int(block), edge)] = int(line)
    return labels


def _format_location(start: int, end: int) -> str:
    return f"Line {start}" if start == end else f"Lines {start}--{end}"


def _join_locations(locations: list[str]) -> str:
    if not locations:
        return "Location unavailable"
    if len(locations) == 1:
        return locations[0]
    if len(locations) == 2:
        return f"{locations[0]} and {locations[1]}"
    return f"{', '.join(locations[:-1])}, and {locations[-1]}"


def _calculate_locations(build_dir: Path, stem: str) -> dict[str, str]:
    registry = _parse_registry(build_dir / f"{stem}.reviewloc")
    labels = _parse_labels(build_dir / f"{stem}.aux")
    by_comment: dict[str, list[str]] = collections.defaultdict(list)
    for ids, block in registry:
        start = labels.get((block, "start"))
        end = labels.get((block, "end"))
        if start is None or end is None:
            raise WorkflowError(f"Line labels are missing for reviewer block {block}.")
        location = _format_location(start, end)
        for review_id in (item.strip() for item in ids.split(",")):
            if not is_review_id(review_id):
                raise WorkflowError(
                    f"Invalid reviewer ID {review_id!r}; expected E-1 or 1-1."
                )
            if location not in by_comment[review_id]:
                by_comment[review_id].append(location)
    return {key: _join_locations(value) for key, value in by_comment.items()}


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
    return _calculate_locations(build_dir, source.stem)


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
        f"{user_style}\n{_revision_runtime(config.language)}", encoding="utf-8"
    )
    _copy_resources(config, current, source_dir)

    command = [
        shutil.which("latexdiff") or "latexdiff",
        "--encoding=utf8",
        "--packages=none",
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
