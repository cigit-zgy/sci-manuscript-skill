"""Reviewer comment parsing."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
from ..exceptions import WorkflowError

HEADING = re.compile(r"^#\s+(Editor|Associate Editor|Reviewer\s+#([1-9]\d*))\s*$", re.I)
COMMENT = re.compile(r"^([1-9]\d*)\.\s+(.*)$")

@dataclass(frozen=True)
class ReviewComment:
    owner: str
    number: int
    text: str


def parse_reviews(path: Path) -> tuple[ReviewComment, ...]:
    if not path.is_file():
        raise WorkflowError(f"Reviewer-comments file is missing: {path}")
    owner: str | None = None
    expected = 1
    comments: list[ReviewComment] = []
    current_number: int | None = None
    current: list[str] = []

    def flush() -> None:
        nonlocal current_number, current, expected
        if current_number is None:
            return
        text = "\n".join(current).strip()
        if not text:
            raise WorkflowError("Reviewer comment cannot be empty.")
        if current_number != expected:
            raise WorkflowError(f"Reviewer comments must be consecutive from 1; expected {expected}, got {current_number}.")
        assert owner is not None
        comments.append(ReviewComment(owner, current_number, text))
        expected += 1
        current_number = None
        current = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        heading = HEADING.fullmatch(raw)
        if heading:
            flush()
            label = heading.group(1).lower()
            if label == "editor":
                owner = "E"
            elif label == "associate editor":
                owner = "AE"
            else:
                owner = heading.group(2)
            expected = 1
            continue
        match = COMMENT.fullmatch(raw)
        if match:
            if owner is None:
                raise WorkflowError("Numbered comment appears before a reviewer heading.")
            flush()
            current_number = int(match.group(1))
            current = [match.group(2)]
        elif current_number is not None:
            current.append(raw)
        elif raw.strip() and owner is None:
            raise WorkflowError("Text appears before the first reviewer heading.")
    flush()
    if not comments:
        raise WorkflowError("No numbered reviewer comments were found.")
    return tuple(comments)


def has_pending_response(text: str) -> bool:
    return any("\\ResponsePending" in line and "\\newcommand" not in line for line in text.splitlines())
