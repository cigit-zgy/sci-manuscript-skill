---
name: sci-manuscript-skill
description: Operate a deterministic LaTeX manuscript lifecycle: initialize, inspect, build, create adjacent revisions, rollback accidental unchanged revisions, reindex broken revision sequences, manage reviewer-response infrastructure, prepare submission packages, and manage an explicit shared bibliography. Do not autonomously edit scientific manuscript content.
---

# SCI manuscript workflow

Use the installed `sci_manuscript` runtime. Scientific prose and scientific decisions remain user-owned.

## Highest-priority invariant

**Never autonomously modify manuscript scientific content.** A reviewer comment does not authorize a content change. Apply manuscript edits only when the user supplies or explicitly approves exact text or a concrete edit operation.

## Routing

| Task | Runtime command |
| --- | --- |
| Initialize | `sci-manuscript init ...` |
| Inspect | `python run.py status` |
| Build | `python run.py build` |
| Start adjacent revision | `python run.py revision` |
| Undo accidental unchanged revision | `python run.py rollback` |
| Repair broken numbering | `python run.py reindex` |
| Prepare submission | `python run.py submission` |
| Prepare Zotero target | `python run.py setup-zotero` |
| Explicit BibTeX sync | `python run.py sync-bib --bib-export ...` |
| Upgrade recognized project state | `python run.py upgrade-project` |

## Revision identity

Canonical identity is two-digit and gap-free:
`initial_submission (r00) -> revision_01 (r01) -> revision_02 (r02) -> ...`.
Legacy one-digit names may be read and repaired by reindexing. New revisions are always adjacent.

`revision`, `rollback`, and `reindex` are confirmation-gated in the CLI. Use `--yes` only when the user has already explicitly authorized that exact mutation.

## Rollback

Rollback is restricted to the latest revision. It compares protected user-owned sources against the revision creation manifest and refuses deletion after user edits or completed response text.

## Reindex

Reindex first produces a plan, then applies renames transactionally. It may change revision directory names and revision identity metadata and may invalidate generated PDFs/packages. It must preserve all protected scientific/user source hashes.

## Progressive disclosure

Read `references/workflow.md` only for lifecycle details and `references/environment.md` only for dependency diagnosis. Do not inspect publisher resources unless diagnosing that exact resource.
