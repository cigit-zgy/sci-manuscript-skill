from __future__ import annotations

import re
from pathlib import Path

PATH = Path("src/sci_manuscript/diff.py")
text = PATH.read_text(encoding="utf-8")

text = text.replace(
    "import collections\nimport re\n",
    "import collections\nimport difflib\nimport re\n",
    1,
)
text = text.replace(
    "from .workspace import ProjectConfig, WorkflowError, strip_provenance_wrappers\n",
    "from .workspace import ProjectConfig, WorkflowError\n",
    1,
)

replacement = r'''def _strip_and_collect_provenance(
    text: str,
    *,
    review_depth: int = 0,
) -> tuple[str, tuple[tuple[str, int, int], ...]]:
    """Strip provenance wrappers and retain review spans in the stripped source."""
    output: list[str] = []
    scopes: list[tuple[str, int, int]] = []
    output_length = 0
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "%" and not _is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            end = len(text) if newline == -1 else newline + 1
            chunk = text[cursor:end]
            output.append(chunk)
            output_length += len(chunk)
            cursor = end
            continue
        if text[cursor] == "\\":
            parsed_review = _parse_command_arguments(text, cursor, r"\review", 2)
            if parsed_review is not None:
                if review_depth:
                    raise WorkflowError(
                        "Nested \\review blocks are ambiguous; combine reviewer IDs "
                        "in one wrapper instead."
                    )
                (raw_ids, body), end = parsed_review
                review_ids = tuple(
                    item.strip() for item in raw_ids.split(",") if item.strip()
                )
                if not review_ids or any(not is_review_id(item) for item in review_ids):
                    raise WorkflowError(
                        f"Invalid reviewer ID list {raw_ids!r}; expected IDs such as 1-1."
                    )
                stripped_body, nested = _strip_and_collect_provenance(
                    body,
                    review_depth=1,
                )
                if nested:
                    raise WorkflowError("Nested reviewer scopes are not supported.")
                start = output_length
                output.append(stripped_body)
                output_length += len(stripped_body)
                scopes.append((",".join(review_ids), start, output_length))
                cursor = end
                continue
            parsed_user = _parse_command_arguments(text, cursor, r"\user", 1)
            if parsed_user is not None:
                (body,), end = parsed_user
                stripped_body, nested = _strip_and_collect_provenance(
                    body,
                    review_depth=review_depth,
                )
                output.append(stripped_body)
                output_length += len(stripped_body)
                scopes.extend(nested)
                cursor = end
                continue
        output.append(text[cursor])
        output_length += 1
        cursor += 1
    return "".join(output), tuple(scopes)


def _map_new_boundary_to_old(
    matching_blocks: list[difflib.Match],
    position: int,
    *,
    side: str,
) -> int:
    """Project one current-source review boundary onto the direct parent."""
    previous: difflib.Match | None = None
    following: difflib.Match | None = None
    for block in matching_blocks:
        if block.b <= position <= block.b + block.size:
            return block.a + (position - block.b)
        if block.b + block.size < position:
            previous = block
            continue
        if block.b > position:
            following = block
            break
    if side == "start":
        if previous is not None:
            return previous.a + previous.size
        if following is not None:
            return following.a
    elif side == "end":
        if following is not None:
            return following.a
        if previous is not None:
            return previous.a + previous.size
    else:
        raise WorkflowError(f"Unknown review-boundary side: {side}")
    return 0


def _insert_review_boundaries(
    text: str,
    scopes: tuple[tuple[str, int, int], ...],
) -> str:
    """Insert transparent internal markers without changing source semantics."""
    result = text
    for ids, start, end in sorted(scopes, key=lambda item: (item[1], item[2]), reverse=True):
        result = (
            result[:end]
            + f"{INTERNAL_REVIEW_END}{{{ids}}}"
            + result[end:]
        )
        result = (
            result[:start]
            + f"{INTERNAL_REVIEW_START}{{{ids}}}"
            + result[start:]
        )
    return result


def _paired_review_sources(old_text: str, new_text: str) -> tuple[str, str]:
    """Project current review scopes onto both sources before latexdiff.

    The user-facing ``\\review`` command records provenance only.  The wrapper is
    removed before diffing, then its boundaries are projected onto the direct
    parent with a character-level sequence alignment.  Identical internal
    boundaries are therefore present in both latexdiff inputs, so the wrapper
    itself can never turn unchanged text into an addition.
    """
    old_stripped, _ = _strip_and_collect_provenance(old_text)
    new_stripped, new_scopes = _strip_and_collect_provenance(new_text)
    if not new_scopes:
        return old_stripped, new_stripped

    matching_blocks = difflib.SequenceMatcher(
        None,
        old_stripped,
        new_stripped,
        autojunk=False,
    ).get_matching_blocks()
    old_scopes: list[tuple[str, int, int]] = []
    previous_new_end = -1
    previous_old_end = -1
    for ids, new_start, new_end in new_scopes:
        if new_start < previous_new_end:
            raise WorkflowError("Reviewer provenance scopes must not overlap.")
        old_start = _map_new_boundary_to_old(
            matching_blocks,
            new_start,
            side="start",
        )
        old_end = _map_new_boundary_to_old(
            matching_blocks,
            new_end,
            side="end",
        )
        if old_start > old_end:
            raise WorkflowError(
                f"Could not align reviewer scope {ids} with the direct parent."
            )
        if old_start < previous_old_end:
            raise WorkflowError(
                f"Reviewer scope {ids} crosses a previous scope after alignment."
            )
        old_scopes.append((ids, old_start, old_end))
        previous_new_end = new_end
        previous_old_end = old_end

    return (
        _insert_review_boundaries(old_stripped, tuple(old_scopes)),
        _insert_review_boundaries(new_stripped, new_scopes),
    )


'''
pattern = re.compile(
    r"def _expand_provenance_wrappers\(.*?\n\ndef _parse_provenance_command",
    flags=re.DOTALL,
)
match = pattern.search(text)
if match is None:
    raise SystemExit("could not locate provenance-expansion function")
text = text[: match.start()] + replacement + "def _parse_provenance_command" + text[match.end() :]

old = '''    old_text = strip_provenance_wrappers(\n        _flatten_tex(previous / "manuscript.tex", roots)\n    )\n    new_text = _expand_provenance_wrappers(\n        _flatten_tex(current / "manuscript.tex", roots)\n    )\n'''
new = '''    old_text, new_text = _paired_review_sources(\n        _flatten_tex(previous / "manuscript.tex", roots),\n        _flatten_tex(current / "manuscript.tex", roots),\n    )\n'''
if old not in text:
    raise SystemExit("could not locate marked-source preparation block")
text = text.replace(old, new, 1)

PATH.write_text(text, encoding="utf-8")
