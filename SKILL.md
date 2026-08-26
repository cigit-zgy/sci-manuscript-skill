---
name: sci-manuscript-skill
description: >
  Manage a LaTeX scientific manuscript workspace through initialization,
  selected-round builds, adjacent revisions, highlighted revised manuscripts,
  reviewer responses, bibliography state, rollback/reindex safety, and
  submission packaging. Never invent or rewrite scientific or response content.
---

# SCI manuscript workflow

Use the installed `sci-manuscript` CLI or public `sci_manuscript` API. Package
resources are staged under the project `tmp/`; they are not copied into rounds.

## Safety invariant

Do not modify manuscript prose, metadata, figures, formulas, citations,
bibliography, reviewer comments, or response prose unless the user explicitly
supplies or approves that exact change. Lifecycle/build authorization is not
scientific-edit authorization.

## Route the request

1. Normalize the project to `PROJECT/manuscript/` and run `status` when the
   active round is uncertain.
2. Determine whether the user means the active round or a specific existing
   `--round`.
3. Determine the minimum build target:
   - initial manuscript: `clean` (default for `initial_submission`);
   - inspect revision highlighting: `marked` (default for revisions);
   - rebuild reviewer correspondence: `response`;
   - final cross-artifact verification: `all`.
4. Run `doctor` only when tool availability is unknown or a compile is blocked.
5. Report selected round, generated artifacts, audit state, timing when
   requested, and any retained diagnostics.

Read [references/workflow.md](references/workflow.md) before creating a
revision, modifying response/reference metadata, synchronizing bibliography, or
preparing submission. Read
[references/revision_semantics.md](references/revision_semantics.md) when marked
content, provenance, topology, citations, equations, or locations are involved.
Read [references/environment.md](references/environment.md) only for environment
diagnosis. Read [references/technical_core.md](references/technical_core.md)
only for repository audits, technical maintenance, architecture optimization,
or release audits; do not load it for normal manuscript lifecycle work.

## Core commands

```bash
sci-manuscript status --project PATH
sci-manuscript build --project PATH [--round ROUND] [--target TARGET]
sci-manuscript revision --project PATH --yes
sci-manuscript submission --project PATH [--round ROUND]
sci-manuscript rollback --project PATH --yes
sci-manuscript reindex --project PATH --yes
sci-manuscript sync-bib --project PATH --bib EXPORT.bib
```

`--round` selects an existing round without changing the active round. A
revision build defaults to the marked-only fast path. Use `--target all` only
when clean, marked, response, and full identity validation are required.

## Frozen revision semantics

- Marked = current clean scientific content + revision highlighting.
- Reviewer-owned current additions/replacements are RubineRed; author-owned are
  ForestGreen; unchanged text is black.
- Citation markers and DOI/URL links use xcolor `ProcessBlue` from `dvipsnames`;
  bibliography prose remains black.
- Parent-only deleted content is absent.
- `latexdiff` detects current additions only; it is not the final renderer.
- `\review` defines provenance only; unchanged scoped text stays black.
- At 60% addition coverage, one current block may be highlighted wholly only
  with identical provenance. Structural seams never merge.
- Current source, equations, citations, bibliography, labels, counters, and
  paragraph topology are the only layout authority.
- `\ReviewReference` is causal reference provenance, not ownership inferred
  from a response mention. AUTHOR/REVIEWER conflict is an error.
- The response-letter first-page opening is a package-owned fixed template.
  `response/responses.tex` owns only `\Response{ID}{...}`, optional
  `\ReviewReference`, and comments; `\ResponseLetter` is rejected with a
  migration diagnostic. Never add, rewrite, or design opening/sign-off prose.

## Workspace and output rules

- Ancestry is `initial_submission -> revision_01 -> revision_02 -> ...`.
- `references/references.bib` is current editable bibliography state;
  `state/<round>/bibliography.bib` is immutable historical machine state.
- `state/<round>/round_state.yaml` freezes historical source, metadata,
  effective author metadata, bibliography, and parent identity.
- `output/` contains canonical user-facing PDFs only. Selective builds remove
  stale PDFs and retain manifest-verified current PDFs.
- Manifests live under `state/`; audits, timing, cache, TeX, AUX, and logs live
  under `tmp/` only.
- Historical builds must not initialize, rewrite, or activate a round.
- Rollback/reindex require explicit confirmation and preserve an archive.
- Submission requires a complete review audit and complete enabled sources.

## Handoff checks

For revision work, report the selected round and parent, target, artifact paths,
review audit, source/topology/numbering identity appropriate to that target, and
whether diagnostics were retained. Do not claim PDF or layout success without a
real compile and rendered inspection. Never hide incomplete responses or
publish compiler intermediates.
