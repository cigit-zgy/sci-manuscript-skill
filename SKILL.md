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
| Start a paper | Collect project, journal, publisher, language, article type, author roles, and optional bibliography; if no author library is configured, route to `sci-manuscript authors configure PATH`, then run `init` |
| Build | Run `build`; r00 retains clean output, while revision rounds retain both clean and adjacent marked PDFs; revision rounds also print the review audit without blocking rendering |
| Start revision | Read the response/revision parts of [workflow.md](references/workflow.md) and the normative [revision semantics](references/revision_semantics.md); run `revision` only after explicit confirmation |
| Prepare submission | Run `submission`; it builds available artifacts, records review completeness in the checklist, and prints unresolved review items with file paths |
| Roll back or reindex | Explain the archive/digest transaction, obtain confirmation, then run the exact command |
| Synchronize bibliography | Use only a user-specified BibTeX export with `sync-bib` |

Do not inspect `.cls`, `.bst`, or `.dtx` during routine reasoning. Inspect a
publisher resource only to diagnose that exact publisher build.

## Invariants

- Workspace root is `PROJECT/manuscript/`; unrelated parent-project files are
  preserved and an existing `manuscript/` is never overwritten.
- Revision ancestry is adjacent and fixed-width:
  `initial_submission (r00) -> revision_01 (r01) -> revision_02 (r02)`.
- Only `manuscript/references/` contains `authors.yaml`, `references.bib`, and
  `revision_style.tex`; revision directories never contain `references/`.
- Built-in publisher resources are package data, not copied user files. Only a
  custom publisher creates `references/journal_template/`.
- `manuscript.tex` is a user-owned composition root. Builds read it but never
  overwrite it.
- `revision` creates `response/reviewer_comments.md` automatically from the
  project language. The editable template contains Editor and Reviewer sections
  with numbered list items. Comment IDs are derived from section identity and
  non-empty list order; review states are computed from comments, responses,
  and manuscript provenance.
- `\review{ID}{text}` is the only manual reviewer-provenance scope for new
  work. It is metadata, not visual markup. The wrapper is removed before
  structural comparison and stored as a sidecar character interval map. Only
  actual additions that fall inside those intervals become reviewer-red;
  unchanged text remains ordinary manuscript text. Deletions remain light gray;
  additions outside reviewer intervals remain author-blue. Legacy `\user{text}`
  remains readable but should not be added.
- Revision comparison follows the four-layer contract in
  `references/revision_semantics.md`: provenance extraction, provenance-free
  structural diff, conservative refinement, then semantic rendering.
- Character refinement is permitted only for TeX-structure-free prose with
  `SequenceMatcher` similarity at least `0.70` and a maximum replacement size
  of `2000` characters. Otherwise the replacement remains atomic.
- Display and inline mathematics use fine-grained structural comparison with
  `latexdiff --math-markup=FINE`. Text decorators never scan mathematical
  content; math changes use the same semantic colors as prose.
- Every revision `build` and `submission` audits
  `reviewer_comments.md <-> responses.tex <-> \review{...}`. Missing responses,
  orphan responses, orphan provenance references, empty comments, invalid input,
  and review-ID drift are warnings. Rendering continues. Every warning reports
  concrete source paths; `submission/package/checklist.md` records review
  completeness as `COMPLETE` or `INCOMPLETE`.
- `output/` contains final user PDFs, `state/` contains persistent machine state,
  and lazy `tmp/` contains reproducible run diagnostics. Successful operations
  remove `tmp/` unless diagnostics are explicitly retained.
- Editable `response/responses.tex` and `submission/cover_letter_body.tex`
  sources are created once and not replaced by later builds. Complete
  correspondence documents are assembled from installed templates only in
  `tmp/`.
- Author-library priority is explicit `--authors`, configured user library,
  then the bundled role-free public library. Initialization always requires
  explicit manuscript roles and never auto-selects bundled authors.
- Correspondence uses the selected corresponding authors. A sole corresponding
  author signs automatically; multiple corresponding authors require an
  explicit `correspondence.signing_author` before submission.
- Cover-letter `\guidance{...}` blocks and unresolved template tokens still
  block submission because they are unresolved submission content rather than
  review-completeness warnings.

## Entrypoints

```bash
sci-manuscript doctor
sci-manuscript authors configure /path/to/authors.yaml
sci-manuscript authors list
sci-manuscript init --help
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
When the audit is incomplete, report each unresolved ID and the exact paths
printed by the CLI. Do not hide those warnings simply because PDFs compiled.

For every revision, `submission` builds clean and direct-parent marked PDFs from
the same source and shared bibliography. A response PDF is assembled when
review comments are available; incomplete responses remain visible placeholders
and the audit stays `INCOMPLETE`. The workflow parses clean and marked compiler
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
same semantic colors; display equations use fine-grained math comparison.
Reviewer line locations are generated in a separate transparent compilation
and cannot change marked rendering.
