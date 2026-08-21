---
name: sci-manuscript-skill
description: >
  Automate an existing LaTeX manuscript workflow: initialize a structured
  project, inspect its build environment, compile the current manuscript, create
  adjacent revisions, prepare reviewer-response infrastructure and marked
  manuscripts, synchronize explicit BibTeX exports, and build version-local
  submission packages. Use for manuscript lifecycle engineering requests in
  English or Chinese, even when the user does not name this skill. Do not use for
  scientific writing, literature interpretation, claim assessment, experiment
  analysis, or deciding how to answer reviewers scientifically.
---

# SCI manuscript workflow

Operate the manuscript lifecycle through the deterministic Python entrypoint.
Keep scientific content and reviewer judgment with the user.

## Route the request

| Task | Required context | Action |
| --- | --- | --- |
| New manuscript | Read [environment.md](references/environment.md) when dependency state is unknown; read the initialization section of [workflow.md](references/workflow.md) | Run `doctor`, collect user data, then run `init` and verify the first PDF |
| Build current manuscript | No reference is normally needed | Run the project-root `python run.py build`; do not initialize or create a revision |
| Start a revision | Read the version and response sections of [workflow.md](references/workflow.md) | Determine the current highest round and run `revision` once |
| Prepare submission | Read the submission and artifact sections of [workflow.md](references/workflow.md) | Run `submission` for an initial version or `all` for a completed revision |
| Synchronize bibliography | Read the bibliography section of [workflow.md](references/workflow.md) | Run `sync-bib` only with an explicit export path or configured local export |
| Diagnose environment | Read [environment.md](references/environment.md) | Run `doctor`; report blockers without changing the environment |

Do not read `.cls`, `.bst`, `.dtx`, or other bundled assets as routine reasoning
context. The runtime copies and compiles files under `assets/` directly. Inspect a
publisher asset only when adapting or diagnosing that exact template.

## Preserve these invariants

- The lifecycle is adjacent and gap-free:
  `initial_submission (r0) -> revision_1 (r1) -> revision_2 (r2) -> ...`.
  Never create `r0 -> r2` or compare non-adjacent versions.
- Use `scripts/run.py` only for source-repository commands. After initialization,
  use the copied project-root `run.py`; do not expose internal module entrypoints.
- Do not invent manuscript prose, results, citations, author identities, reviewer
  responses, or scientific claims. Workflow automation does not authorize content
  changes.
- Before installing, upgrading, activating, or otherwise changing a dependency,
  show the missing requirement and obtain approval for the exact environment.
- Treat authors, bibliography, manuscript sections, figures, tables, and reviewer
  responses as user-owned. Explicitly identify every placeholder that remains.
- Preserve editable cover-letter, response, highlights, and graphical-abstract
  sources after creation; repeated builds must not overwrite user edits.
- Keep author data, bibliography, revision style, generated metadata, and
  publisher resources only under project-root `references/`. Never create or
  copy a `references/` directory inside a version.
- Successful commands remove their `tmp/run_*` directory. Failed commands may
  retain a project-relative diagnostic directory and must report it.

## Entrypoints

From the skill repository:

```bash
python scripts/run.py doctor
python scripts/run.py init --help
```

From an initialized project:

```bash
python run.py doctor
python run.py build
python run.py revision --reviews /absolute/path/to/reviewer-comments.md
python run.py submission
python run.py all
python run.py sync-bib --bib-export /absolute/path/to/export.bib
python run.py status
```

Select an existing version with `--round rN` where supported. `revision` creates
only the next version. `--allow-placeholders` is diagnostic and never makes a
submission ready.

## New-project inputs

Before `init`, obtain a new or empty project path, user-supplied title and journal,
publisher key (`elsevier`, `nature`, `acs`, or `chinese`), language (`en` or `zh`),
article type, author order, and optional existing author YAML and BibTeX paths.
Copy bundled examples only after the user accepts that they are placeholders.

Initialization must leave the user with
`initial_submission/output/manuscript.pdf` and identify these editable locations:

- `initial_submission/manuscript.yaml`;
- root `references/authors.yaml`, `references/references.bib`, and
  `references/revision_style.tex`;
- `initial_submission/sections/`, `figures/`, and `tables/`.

Each version YAML groups selected names under `authors.first_authors`,
`authors.corresponding_authors`, and `authors.authors`; multiple names are
allowed in every group. Do not edit generated root
`references/author_metadata.tex` or `references/publisher_metadata.tex`
directly.

## Validate before handoff

Confirm the selected version, direct parent, expected final PDFs, extractable PDF
text, manuscript line numbers, correspondence without manuscript line numbering,
and an empty `tmp/` after success. Report only final project-relative artifacts;
do not publish compiler intermediates, flattened diff sources, extracted location
registries, caches, or test fixtures.
