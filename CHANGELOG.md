# Changelog

## 1.1.0

- Revision-round `build` retains both clean and direct-parent marked PDFs.
- Reviewer provenance is separated from structural comparison: `\review{ID}{text}` records reviewer scope, while only actual additions inside that scope render with the green straight underline; unchanged scoped text remains unmarked.
- Deletions remain red strikeout and ordinary author additions remain blue wave underline.
- Pure-prose replacements are refined at character level only when `SequenceMatcher(..., autojunk=False).ratio() >= 0.70` and the replacement is at most 2000 characters; dissimilar, long, or TeX-bearing replacements remain atomic.
- Display mathematics uses whole-equation comparison (`latexdiff --math-markup=WHOLE`) and mathematics is excluded from CJK/ulem text-decoration scanners.
- Chinese abstract and keyword macros participate in the same provenance classification as body text.
- Reviewer line locations are compiled independently from marked-manuscript color rendering.
- Added regression coverage for provenance extraction, refinement policy, Chinese front matter, mathematical markup, three-color rendering, and clean-versus-marked layout QA.
