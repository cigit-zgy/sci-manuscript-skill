# Changelog

## Unreleased

- Treat every changed formula atomically: render the complete old formula as a
  deletion and the complete current formula as an addition, with changed
  labelled displays separated to prevent revision-only horizontal overflow.

- The Chinese `kxtbcas-numeric.bst` now renders non-empty DOI fields exactly
  once and removes standard DOI resolver prefixes at rendering time without
  rewriting user BibTeX data.
- Generated bibliographies now participate in direct-parent marked comparison.
  Parent/current `.bbl` files are materialized independently and aligned by
  citation key, preserving current numbering while marking real metadata,
  addition, and deletion changes.
- Machine-owned per-round bibliography snapshots preserve visible history
  across `sync-bib`, revision creation, rollback, reindex, build, and
  submission transactions. Snapshots now retain only build-resolved citations
  and recursive BibTeX dependencies; `rebuild-bib-state` provides an explicit
  confirmed migration for existing round state, while local attachment paths
  are excluded from machine-owned snapshots.
- Marked builds encode current-source paragraph topology before `latexdiff`,
  neutralize generated serialization whitespace, and emit a zero-tolerance
  current/marked/missing/invented topology report.
- Response letters use a single title/contact page break, exact editor/reviewer
  section titles, compact location spacing, and visually distinct neutral-gray
  general comments without generated ceremonial closings.

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
- Revision provenance, fine-grained mathematical comparison, automatic response
  locations, and the red/blue/light-gray visual semantics are unchanged.
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
