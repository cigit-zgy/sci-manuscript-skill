---
name: sci-manuscript-skill
description: >
  Automate an existing LaTeX manuscript workflow: initialize a structured
  project, inspect its build environment, compile the current manuscript, create
  adjacent revisions, prepare reviewer-response infrastructure and marked
  manuscripts, guide Zotero Better BibTeX Automatic Export, validate citation
  keys, synchronize explicit BibTeX exports as a manual fallback, and build
  version-local submission packages. Use for manuscript lifecycle engineering
  requests in English or Chinese, even when the user does not name this skill.
  Do not use for scientific writing, literature interpretation, claim
  assessment, experiment analysis, or deciding how to answer reviewers
  scientifically.
---

# SCI manuscript workflow

Operate the manuscript lifecycle through the deterministic Python entrypoint.
Keep scientific content and reviewer judgment with the user.

## Highest-priority content invariant

**Agent MUST NOT autonomously modify manuscript content.** This prohibition
overrides workflow convenience and reviewer pressure. By default, the agent may
not polish, rewrite, reorganize, change scientific content, add or remove
arguments, edit the abstract, introduction, discussion, or conclusion, or decide
from a reviewer comment what the manuscript should say. A reviewer request alone
is not authorization to draft or apply manuscript text.

Revision workflow may create the next adjacent workspace, response
infrastructure, diffs, line locations, compilations, and submission packages.
The agent may apply a manuscript patch only when the user supplies or explicitly
confirms the exact replacement text or concrete edit operation. “Start the first
revision” creates infrastructure only. “Generate the marked PDF” changes no TeX
source.

## Route the request

| Task | Required context | Action |
| --- | --- | --- |
| New manuscript | Read [environment.md](references/environment.md) when dependency state is unknown; read the initialization section of [workflow.md](references/workflow.md) | Run `doctor`, collect user data, then run `init` and verify the first PDF |
| Build current manuscript | No reference is normally needed | Run the project-root `python run.py build`; do not initialize or create a revision |
| Start or edit a revision | Read [revision_contract.yaml](references/revision_contract.yaml) and the version and response sections of [workflow.md](references/workflow.md) | Enforce the default no-content-edit boundary, determine the current highest round, and run `revision` once when a new round is required |
| Prepare submission | Read the submission and artifact sections of [workflow.md](references/workflow.md) | Run `submission` for an initial version or `all` for a completed revision |
| Configure bibliography | Read the bibliography section of [workflow.md](references/workflow.md) | Prefer Better BibTeX Automatic Export; run `setup-zotero` to prepare guidance, `check` to validate keys, and `sync-bib` only as a manual fallback |
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
  responses, or scientific claims. Workflow automation and reviewer comments do
  not authorize content changes.
- Revision mode starts with **NO CONTENT EDIT**. Apply only an exact text patch or
  concrete edit operation supplied or explicitly confirmed by the user. Never
  infer the edit from a reviewer comment. Do not independently polish, rewrite,
  restructure, alter claims or interpretation, optimize narrative, add concepts,
  or fix typos. Starting a revision, building, diffing, locating lines, and
  packaging must leave user-owned manuscript sources unchanged.
- Before installing, upgrading, activating, or otherwise changing a dependency,
  show the missing requirement and obtain approval for the exact environment.
- Treat authors, bibliography, manuscript sections, figures, tables, and reviewer
  responses as user-owned. Explicitly identify every placeholder that remains.
- Preserve editable cover-letter, response, highlights, and graphical-abstract
  sources after creation; repeated builds must not overwrite user edits.
- Keep author data, bibliography, revision style, generated metadata, and
  publisher resources only under project-root `references/`. Never create or
  copy a `references/` directory inside a version.
- Never open Zotero, modify its settings or database, or call a Zotero API.
  `setup-zotero` creates only project files and instructions. A build never
  synchronizes bibliography data implicitly.
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
python run.py check
python run.py revision --reviews /absolute/path/to/reviewer-comments.md
python run.py submission
python run.py all
python run.py setup-zotero
python run.py sync-bib --bib-export /absolute/path/to/export.bib
python run.py status
```

Compatibility aliases are `render` for `build`, `revise` for `revision`,
`package` for `submission`, and `validation` for `check`.

Select an existing version with `--round rN` where supported. `revision` creates
only the next version. `--allow-placeholders` is diagnostic and never makes a
submission ready.

## New-project inputs

For a request such as "start writing a paper", do not initialize immediately.
Use this order:

1. run `doctor` when the environment has not already been verified;
2. ask for manuscript location, title, journal, publisher, language, article
   type, ordered authors, corresponding authors, bibliography source, Zotero
   Better BibTeX preference, and any existing LaTeX files;
3. initialize only after the required identity and project information is known;
4. compile and validate the initial PDF, citation state, shared references, and
   empty `tmp/`.

Never fill missing authors, journal facts, submission declarations, citations,
or scientific prose. Ask whether the user wants Better BibTeX Automatic Export.
If yes, point them to `references/zotero_setup.md`; if no, retain the shared
`references/references.bib` for manual maintenance. Do not require repeated
manual BibTeX copying when Automatic Export is acceptable.

Initialization must leave the user with
`initial_submission/output/manuscript.pdf` and identify these editable locations:

- `initial_submission/manuscript.yaml`;
- root `references/authors.yaml`, `references/references.bib`, and
  `references/revision_style.tex`;
- root `references/zotero_setup.md` and `references/journal_templates/`;
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
