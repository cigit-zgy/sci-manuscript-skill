---
name: sci-manuscript-skill
description: >
  Manage an existing or new LaTeX manuscript workspace through initialization,
  compilation, adjacent revisions, marked manuscripts, reviewer responses,
  bibliography synchronization, rollback/reindex safety, and submission
  packaging. Use for scientific manuscript lifecycle engineering in English or
  Chinese. Do not use to invent, rewrite, or scientifically assess manuscript or
  reviewer-response content.
---

# SCI manuscript workflow

Use the installed `sci-manuscript` CLI or public `sci_manuscript` API. Runtime
code and publisher resources come from the installed package; a generated
project never depends on a source checkout and never receives a copied `run.py`.

## Highest-priority invariant

**AGENT MUST NOT AUTONOMOUSLY MODIFY MANUSCRIPT CONTENT.** Starting a revision,
building, diffing, locating lines, rolling back, reindexing, synchronizing a
bibliography, or preparing submission files is not authorization to polish,
rewrite, reorganize, add, delete, or scientifically interpret manuscript text.
Reviewer comments are not edit authorization. Apply manuscript changes only
when the user supplies or explicitly confirms the exact text or operation. Do
not write reviewer-response prose on the user's behalf.

## Route requests

| Request | Action |
| --- | --- |
| Check environment | Run `sci-manuscript doctor`; read [environment.md](references/environment.md) only for a blocker |
| Start a paper | Run `init --project PATH` to create commented metadata without inventing values; the user edits `meta.yaml` before the first build. The parameter-rich form remains supported for automation. |
| Build | Run `build`; r00 retains clean output, while revision rounds retain clean, adjacent marked, and current response PDFs when response sources are syntactically valid; revision rounds also print the review audit without blocking rendering |
| Start revision | Read the response/revision parts of [workflow.md](references/workflow.md) and the normative [revision semantics](references/revision_semantics.md); run `revision` only after explicit confirmation |
| Prepare submission | Run `submission`; a revision must have a complete review audit before formal submission artifacts are assembled |
| Roll back or reindex | Explain the archive/digest transaction, obtain confirmation, then run the exact command |
| Synchronize bibliography | Use only a user-specified BibTeX export with `sync-bib` |

Do not inspect `.cls`, `.bst`, or `.dtx` during routine reasoning. Inspect a
publisher resource only to diagnose that exact publisher build.

## Invariants

- Workspace root is `PROJECT/manuscript/`; unrelated parent-project files are
  preserved and an existing `manuscript/` is never overwritten.
- Revision ancestry is adjacent and fixed-width:
  `initial_submission (r00) -> revision_01 (r01) -> revision_02 (r02)`.
- `manuscript/references/` contains `references.bib` and `revision_style.tex`.
  The BibTeX file is the editable latest state; immutable historical copies live
  only in machine-owned `state/<round>/bibliography.bib` and are never edited by
  `sync-bib`.
  Builds resolve the configured user author library, then the bundled
  Skill-level library. Projects and revision directories never contain an
  author library or version-local `references/`.
- Built-in publisher/language pairs are Chinese/`zh`, Elsevier/`en`, Nature/`en`,
  and ACS/`en`. A custom template supplied at initialization declares its own
  supported languages and is copied once to `references/journal_template/`;
  built-in resources remain package data and are never copied into projects.
- `sections/00_frontmatter.tex` owns manuscript title, abstract, and keyword
  text. `meta.yaml` owns funding,
  language, article type,
  journal, publisher, author order, and corresponding roles. The author library
  owns names, email, affiliations, and bilingual biography strings. Runtime
  metadata combines these sources under `tmp/<run>/` and is never published
  into a manuscript round.
- `manuscript.tex` is a user-owned composition root. Builds read it but never
  overwrite it.
- `revision` creates `response/reviewer_comments.md` automatically from the
  project language. The editable template contains Associate Editor, Editor,
  and Reviewer sections
  with numbered list items. Comment IDs are derived from section identity and
  non-empty list order; review states are computed from comments, responses,
  and manuscript provenance.
- `\review{ID}{text}` is the only manual reviewer-provenance scope for new
  work. It is metadata, not visual markup. The wrapper is removed before
  structural comparison and stored as a sidecar character interval map. Only
  actual additions that fall inside those intervals become reviewer-red;
  unchanged text remains ordinary manuscript text. Deletions remain light gray;
  additions outside reviewer intervals remain author-blue.
- Revision comparison follows the four-layer contract in
  `references/revision_semantics.md`: provenance extraction, provenance-free
  structural diff, conservative refinement, then semantic rendering.
- Visible manuscript state includes user scientific TeX, user frontmatter,
  generated visible metadata, and the publisher-rendered bibliography. Parent
  and current bibliographies are materialized independently from their own
  citation sets and BibTeX state. Generated `\bibitem` entries are aligned by
  citation key, while the marked PDF retains current ordering and numbering.
- Bibliography metadata changes are ordinary author revisions: additions are
  blue and deletions are light-gray strikeout, never reviewer-red. Citation
  keys remain machine identity and must not appear in the PDF.
- Character refinement is permitted only for TeX-structure-free prose with
  `SequenceMatcher` similarity at least `0.70` and a maximum replacement size
  of `2000` characters. Otherwise the replacement remains atomic.
- Display and inline mathematics use fine-grained structural comparison with
  `latexdiff --math-markup=WHOLE`. Any formula change replaces the complete
  formula as one revision unit. Text decorators never scan mathematical
  content; math changes use the same semantic colors as prose.
- Every revision `build` and `submission` audits
  `reviewer_comments.md <-> responses.tex <-> \review{...}`. Missing responses,
  orphan responses, orphan provenance references, empty comments, invalid input,
  and review-ID drift are completeness issues. A normal `build` continues so
  authors can inspect manuscript PDFs; formal `submission` stops before
  creating artifacts unless the audit is complete.
  Ordinary missing/empty/orphan entries are listed by ID without internal paths;
  malformed source reports its absolute path.
- `output/` contains final user PDFs, `state/` contains persistent machine state,
  and lazy `tmp/` contains reproducible run diagnostics. Successful operations
  remove `tmp/` unless diagnostics are explicitly retained.
- Editable `response/responses.tex` is generated from the actual detailed
  comments, and `submission/cover_letter_body.tex` is created once. Complete
  correspondence documents are assembled from installed templates only in
  `tmp/`.
- Author-library priority is configured user library, then the bundled
  role-free public library. Initialization always requires
  explicit manuscript roles and never auto-selects bundled authors.
- Correspondence uses the selected corresponding authors. A sole corresponding
  author signs automatically; multiple corresponding authors require an
  explicit `correspondence.signing_author` before submission.
- Cover-letter `\guidance{...}` blocks, unresolved template tokens, and pending
  highlights/graphical-abstract markers block submission because they are
  unresolved submission content rather than review-completeness warnings.
- Built-in journal templates and manuscript preambles remain package resources.
  They are staged only under `tmp/<run>/`; user rounds never contain
  `preamble/`, `manuscript_preamble/`, `journal_templates/`, publisher
  `.cls`/`.bst`, `workflow.tex`, or `sections.yaml`.
- Submission artifacts, editable sources, and their final PDFs share the flat
  user-facing `submission/` directory.
- Every successful build/submission atomically updates
  `state/<round>/build_manifest.yaml` with input/output/resource hashes and the
  effective engine/toolchain without private absolute project paths. Failed
  operations leave the previous successful manifest unchanged.
- Tectonic is the primary release-gated engine. `--engine latex` uses the
  traditional `latexmk` driver with XeLaTeX for Chinese, pdfLaTeX for English
  unless the source requires XeLaTeX, and BibTeX/Biber as appropriate.

## Entrypoints

```bash
sci-manuscript doctor
sci-manuscript authors configure /path/to/authors.yaml
sci-manuscript authors list
sci-manuscript init --help
sci-manuscript init --project /path/to/project
sci-manuscript status --project /path/to/project
sci-manuscript build --project /path/to/project
sci-manuscript revision --project /path/to/project --yes
sci-manuscript rollback --project /path/to/project --yes
sci-manuscript reindex --project /path/to/project --yes
sci-manuscript submission --project /path/to/project
sci-manuscript sync-bib --project /path/to/project --bib export.bib
```

A pre-existing reviewer-comment file may still be supplied with
`revision --reviews /path/to/reviews.md`; the generated template is used when
that option is omitted.

## Handoff checks

Report the exact current round and parent, final project-relative artifacts,
review-audit result, source-integrity result, and whether `tmp/` was removed.
When the audit is incomplete, report each unresolved ID. Include an absolute
path only when the CLI identifies malformed source. Do not hide incomplete
responses simply because PDFs compiled.

For every revision, `build` produces clean and direct-parent marked PDFs from
isolated parent/current visible state, derives review locations, and rebuilds
the response PDF from the current user-owned `responses.tex` when that source is
syntactically valid. Incomplete entries remain visible in the audit but do not
make a valid response source stale. `submission` requires a complete audit
before assembling formal submission artifacts. The workflow parses clean and marked compiler
logs, compares overfull boxes, and fails if marked introduces an overflow absent
from clean; the per-run result remains in
`tmp/<run>/revision_layout_qa.txt` only when diagnostics are retained or the run
fails.
Do not suppress failures with global `\sloppy`, unconditional
`\emergencystretch`, smaller body type, altered geometry, or hand-inserted line
breaks. The automated comparison cannot decide whether small shared overfull
boxes are visually harmless, so validate extractable PDF text and visually
inspect marked/response pages. Never publish compiler intermediates, flattened
TeX, location registries, caches, test PDFs, or private paths.

Automatic revision provenance has three mutually exclusive visible states:
ordinary author additions are blue text, deletions are light gray with
strikeout, and reviewer/editor-linked additions are red text. Unchanged text is
never colored because of `\review{}` alone. In Chinese marked manuscripts,
deletion strikeout continues through CJK punctuation. Mathematics follows the
same semantic colors; every changed formula is replaced as one atomic unit.
Reviewer line locations are generated in a separate transparent compilation
and cannot change marked rendering.

For the built-in Chinese publisher, `kxtbcas-numeric.bst` renders each non-empty
DOI exactly once at the end of its entry as `DOI: 10...`. Standard
`https://doi.org/`, `http://doi.org/`, and `http(s)://dx.doi.org/` prefixes are
removed only while rendering; the user-owned BibTeX source is never rewritten.
Entries without a DOI receive no DOI label or placeholder.
