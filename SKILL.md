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
| Start a paper | Collect project, journal, publisher, language, article type, author roles, and optional bibliography; run `init` |
| Build | Run `build`; do not change TeX or create a revision |
| Start revision | Read the response/revision parts of [workflow.md](references/workflow.md); run `revision` only after explicit confirmation |
| Prepare submission | Confirm all user responses are complete; run `submission` |
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
- `\review{ID}{text}` and `\user{text}` are the only manual provenance wrappers.
  Deletions are detected by adjacent `latexdiff`.
- Successful operations remove lazy `tmp/`; failed runs may retain diagnostics.
- Editable responses and submission sources are created once and not replaced
  by later builds.

## Entrypoints

```bash
sci-manuscript doctor
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
Validate extractable PDF text and visually inspect marked/response pages. Never
publish compiler intermediates, flattened TeX, location registries, caches, test
PDFs, or private paths.
