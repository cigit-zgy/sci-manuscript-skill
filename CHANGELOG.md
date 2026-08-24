# Changelog

## 1.1.0

- Revision-round `build` retains both clean and direct-parent marked PDFs.
- Reviewer provenance is separated from structural comparison: `\review{ID}{text}` records reviewer scope, while only actual additions inside that scope render as red text without an underline; unchanged scoped text remains unmarked.
- Deletions render as light-gray strikeout and ordinary author additions render as blue text without an underline or wave.
- Pure-prose replacements are refined at character level only when `SequenceMatcher(..., autojunk=False).ratio() >= 0.70` and the replacement is at most 2000 characters; dissimilar, long, or TeX-bearing replacements remain atomic.
- Display and inline mathematics use fine-grained comparison (`latexdiff --math-markup=FINE`) with the same semantic colors as prose; mathematics is excluded from CJK/ulem text-decoration scanners except for the dedicated deletion strikeout.
- Persistent revision creation and review-index records live under `state/revision_NN/`; `output/` contains final user PDFs only and reproducible diagnostics remain under the current `tmp/<run>/`.
- Malformed response sources produce a non-blocking `RESPONSES_INVALID` audit issue with the absolute source path. Clean and marked manuscripts still build, the checklist remains `INCOMPLETE`, and no untrusted response PDF is generated.
- Chinese abstract and keyword macros participate in the same provenance classification as body text.
- Reviewer line locations are compiled independently from marked-manuscript color rendering.
- Added regression coverage for provenance extraction, refinement policy, Chinese front matter, mathematical markup, three-color rendering, and clean-versus-marked layout QA.
