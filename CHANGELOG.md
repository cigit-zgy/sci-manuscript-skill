# Changelog

## Unreleased

- Highlighted manuscripts now render only current scientific content: reviewer
  additions are RubineRed, author additions are ForestGreen, citation markers
  and DOI/URL links are pure RGB blue (`#0000FF`), ordinary text is black, and parent-only
  deletions are absent.
- `latexdiff` is limited to current-addition evidence. Highlight markup is
  inserted into the exact current source with hard source, paragraph, block
  topology, numbering, and output-purity validation.
- Adaptive 60% whole-block highlighting, exact-move suppression, atomic current
  display equations, tiny unchanged-island coalescing, and causal reference
  provenance are covered by regression tests.
- Revision builds support target-aware marked-only, response, clean, and full
  paths with deterministic bibliography caching and per-stage timing.
- Response letters use package-owned Chinese and English openings, ordered
  one-to-many correspondence metadata, one opening-page break, automatic
  TeX-native current locations, frozen component-local spacing, and exact
  system Times New Roman for Latin-script text.
- Reviewer locations now come from package-owned `lineno`/`\linelabel` AUX
  records; unsupported complex AMS environments fail closed instead of falling
  back to PDF geometry.
- Publisher-generated bibliography control keys are excluded from persistent
  citation snapshots even when a later AUX pass omits their database name.
- Unused demonstration documents were removed from publisher package data;
  required classes, styles, source/license material, and provenance remain.

## 2.0.0

Version 2.0.0 establishes one strict workspace and submission contract. It does
not silently migrate v1 workspaces; archive the project before deliberately
converting it with the migration note in `references/workflow.md`.

Breaking changes:

- Author roles use only list-valued `authors.first`, `authors.corresponding`, and
  `authors.other`; the v1 role keys are rejected.
- Visible title, abstract, and keywords are user-owned in
  `sections/00_frontmatter.tex`; `meta.yaml` owns workflow metadata rather than
  rendered frontmatter prose.
- Reviewer responses use generated `\Response{ID}{body}` entries. Associate
  Editor IDs (`AE-N`) join Editor (`E-N`) and Reviewer (`N-N`) IDs, while line
  locations remain automatic and never appear as user-editable fields.
- User cover prose is `submission/cover_letter_body.tex`; complete cover and
  response documents are assembled from package-owned templates at runtime.
- Revision `build` refreshes clean, direct-parent marked, and parseable current
  response PDFs while reporting incomplete review items. Formal `submission`
  requires a complete review audit and complete enabled submission sources.
- Creation records, review indexes, generated-artifact ownership, and the
  successful build manifest live under `state/<round>/`. Final user PDFs live in
  `output/`; reproducible diagnostics live in `tmp/`.
- Submission artifacts and sources share one flat `submission/` directory;
  nested `submission/package/` is rejected. Reindex/rollback preserve user
  submission sources and hash-verify ownership of generated paths.
- Built-in templates support Chinese/`zh`, Elsevier/`en`, Nature/`en`, and
  ACS/`en`. Custom templates are explicitly supplied at initialization, declare
  their languages, and live only in `references/journal_template/`.
- Bibliography synchronization requires an explicit BibTeX path. Tectonic is
  the primary release-gated engine; the traditional `latexmk` driver is an
  explicit supported engine with engine-aware diagnostics.
- Publisher infrastructure remains package-owned. The Chinese default body is
  semantic-free, and user composition roots remain editable.

Reliability and audit changes:

- TeX input and provenance scanning is comment-aware, nested-brace aware, and
  rejects path traversal or malformed active commands with concrete source
  paths.
- Review audit detects changed/removed comments, drift, orphan provenance,
  duplicate IDs, malformed response source, and incomplete responses without
  blocking ordinary manuscript rendering.
- Revision provenance, automatic response locations, and output publication
  remain deterministic and atomic.
- Output and submission publication is staged and atomic. A failed operation
  preserves the previous complete final artifacts and successful manifest.
- Each successful build/submission writes a private-path-free manifest of
  source, resource, toolchain, font, and output hashes.
- The project-maintained Chinese class is MIT licensed; the derived
  `kxtbcas-numeric.bst` provenance and third-party license are documented.

## 1.0.0

- First public release of the manuscript initialization, build, revision,
  response, submission, rollback, reindex, and bibliography workflow.
- Established package-owned journal resources and user-owned scientific source.
