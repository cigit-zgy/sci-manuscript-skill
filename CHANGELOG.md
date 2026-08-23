# Changelog

## 1.1.0

- Revision-round `build` retains both clean and direct-parent marked PDFs.
- Red strikeout remains deletion markup and blue wave underline remains ordinary author markup.
- `\review{ID}{text}` is now a provenance scope rather than a formatting wrapper: only text that actually differs from the direct parent is rendered with the green straight underline, while unchanged text inside the scope remains unmarked.
- Chinese abstract and keyword macros participate in reviewer-aware diffing, so reviewed changes in front matter use the same green semantics as body text.
- Added regression tests for reviewer-scope classification, Chinese front matter, and retained marked build output.
