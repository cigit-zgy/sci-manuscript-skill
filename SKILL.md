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
| Build | Run `build`; do not change TeX or create a revision |
| Start revision | Read the response/revision parts of [workflow.md](references/workflow.md); run `revision` only after explicit confirmation |
| Prepare submission | Confirm all user responses are complete; run `submission`, which must pass clean/marked layout QA |
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
- `\review{ID}{text}` is the only manual provenance wrapper for new work.
  Ordinary additions and deletions are detected by adjacent `latexdiff`;
  legacy `\user{text}` remains readable but should not be added.
- Successful operations remove lazy `tmp/`; failed runs may retain diagnostics.
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
- Cover-letter `\guidance{...}` blocks and unresolved template tokens block
  submission. `response_only` comments omit locations; `manuscript_revised`
  comments use marked-manuscript locations.

## Entrypoints

```bash
sci-manuscript doctor
sci-manuscript authors configure /path/to/authors.yaml
sci-manuscript authors list
sci-manuscript init --help
sci-manuscript status --project /path/to/project
sci-manuscript build --project /path/to/project
sci-manuscript revision --project /path/to/project --reviews reviews.md --yes
sci-manuscript rollback --project /path/to/project --yes
sci-manuscript reindex --project /path/to/project --yes
sci-manuscript submission --project /path/to/project
sci-manuscript sync-bib --project /path/to/project --bib export.bib
```

## Handoff checks

Report the exact current round and parent, final project-relative artifacts,
pending responses, source-integrity result, and whether `tmp/` was removed.
For every revision, `submission` builds clean, direct-parent marked, and
response PDFs from the same source and shared bibliography. It parses both
compiler logs, compares overfull boxes, and fails if marked introduces an
overflow absent from clean; the durable result is
`revision_NN/output/revision_layout_qa.txt`. Do not suppress failures with
global `\sloppy`, unconditional `\emergencystretch`, smaller body type, altered
geometry, or hand-inserted line breaks. The automated comparison cannot decide
whether small shared overfull boxes are visually harmless, so validate
extractable PDF text and visually inspect marked/response pages. Never
publish compiler intermediates, flattened TeX, location registries, caches, test
PDFs, or private paths.

Automatic revision provenance uses three non-overlapping conventions: ordinary
author additions detected by latexdiff are blue with a wave underline,
deletions are red with strikeout, and reviewer-linked `\review{}` additions are
green with a straight underline. `\user{}` is backward-compatible only and has
the same ordinary-addition semantics. Structural wrappers stay transparent,
while mathematics is rendered
through a dedicated zero-width overlay path and separated from line-decoration
scanners. Do not wrap arbitrary latexdiff or reviewer blocks as one `ulem`,
`soul`, or `xeCJKfntef` argument; that can turn mixed CJK/math content into
unbreakable boxes and alter the clean manuscript's geometry.
