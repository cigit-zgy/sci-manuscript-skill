# Changelog

## 2.0.0

- Removed the superseded project author-library override, custom publisher
  template, traditional-LaTeX engine, implicit bibliography discovery, and
  manuscript frontmatter fields from the public contract.
- Defined the supported publisher/language matrix as Chinese/`zh`,
  Elsevier/`en`, Nature/`en`, and ACS/`en`.
- Formal revision submission now requires a complete review audit; ordinary
  manuscript builds remain available while responses are incomplete.
- Reindexing clears only generated submission artifacts and preserves editable
  cover-letter, highlights, and graphical-abstract sources.
- TeX command scanners ignore commented provenance, and ambiguous duplicate
  review-comment fingerprints no longer produce false drift reports.
- Failed revision creation removes partial round, state, response, and temporary
  transaction data.
- Bibliography synchronization now requires an explicit user-supplied BibTeX
  path.

- Revision-round `build` retains both clean and direct-parent marked PDFs.
- Reviewer provenance is separated from structural comparison: `\review{ID}{text}` records reviewer scope, while only actual additions inside that scope render as red text without an underline; unchanged scoped text remains unmarked.
- Deletions render as light-gray strikeout and ordinary author additions render as blue text without an underline or wave.
- Pure-prose replacements are refined at character level only when `SequenceMatcher(..., autojunk=False).ratio() >= 0.70` and the replacement is at most 2000 characters; dissimilar, long, or TeX-bearing replacements remain atomic.
- Display and inline mathematics use fine-grained comparison (`latexdiff --math-markup=FINE`) with the same semantic colors as prose; mathematics is excluded from CJK/ulem text-decoration scanners except for the dedicated deletion strikeout.
- Persistent revision creation and review-index records live under `state/revision_NN/`; `output/` contains final user PDFs only and reproducible diagnostics remain under the current `tmp/<run>/`.
- Malformed response sources produce `RESPONSES_INVALID` with the absolute
  source path. Clean and marked manuscript builds remain available, while formal
  submission and untrusted response output are blocked.
- Reviewer-comment input uses one Editor/Reviewer structure with an optional summary and numbered detailed comments. IDs are assigned internally only to non-empty detailed comments.
- Editable response entries are generated from the actual detailed comments. Users write only each `\Response{ID}{body}` body; missing, empty, and orphan entries remain non-blocking completeness issues.
- Response-letter locations are derived automatically from `\review{ID}{...}`, with localized and normalized multiple ranges; response-only comments omit the location sentence.
- Publisher-independent title ownership lives in user-editable `sections/00_frontmatter.tex`; runtime manuscript and correspondence metadata resolve that source without duplicating title text in `meta.yaml`.
- Chinese abstract and keyword macros participate in the same provenance classification as body text.
- Reviewer line locations are compiled independently from marked-manuscript color rendering.
- Added regression coverage for provenance extraction, refinement policy, Chinese front matter, mathematical markup, three-color rendering, and clean-versus-marked layout QA.
