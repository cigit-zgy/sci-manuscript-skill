"""Formal policy for adjacent manuscript revision comparison.

The policy separates scientific provenance from diff mechanics. It defines when
prose may be refined below block level and how mathematics is handed to
``latexdiff``. Rendering colors and line styles remain presentation concerns in
``diff.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class RevisionDiffPolicy:
    """Deterministic rules for structural diff refinement.

    Character-level refinement is intentionally conservative. A replacement is
    refined only when both sides are TeX-structure-free prose, the larger side
    is bounded by ``max_character_refinement_chars``, and SequenceMatcher
    similarity reaches ``min_character_similarity``. Otherwise the replacement
    remains atomic.

    Display mathematics is compared as a whole equation. This prevents diff
    commands from being inserted into the internal TeX structure of equations,
    where they can change grouping or layout.
    """

    min_character_similarity: float = 0.70
    max_character_refinement_chars: int = 2000
    math_markup: str = "WHOLE"
    unsafe_character_refinement_tokens: str = r"\{}$%&#_^~"

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_character_similarity <= 1.0:
            raise ValueError("min_character_similarity must be within [0, 1].")
        if self.max_character_refinement_chars <= 0:
            raise ValueError("max_character_refinement_chars must be positive.")
        if self.math_markup not in {"OFF", "WHOLE", "COARSE", "FINE"}:
            raise ValueError("math_markup must be OFF, WHOLE, COARSE, or FINE.")

    def character_matcher(self, old: str, new: str) -> SequenceMatcher[str] | None:
        """Return a matcher only when a prose replacement is eligible to refine."""
        if any(
            char in self.unsafe_character_refinement_tokens for char in old + new
        ):
            return None
        if max(len(old), len(new)) > self.max_character_refinement_chars:
            return None
        matcher = SequenceMatcher(a=old, b=new, autojunk=False)
        if matcher.ratio() < self.min_character_similarity:
            return None
        return matcher


DEFAULT_REVISION_DIFF_POLICY = RevisionDiffPolicy()
