---
name: sci-manuscript-skill
description: >
  Operate an installed LaTeX manuscript lifecycle: inspect the environment,
  initialize a portable project, build manuscripts, create adjacent revisions,
  prepare Editor and reviewer-response infrastructure, generate marked
  manuscripts and line locations, manage a shared Zotero/BibTeX target, migrate
  recognized legacy projects, and build version-local submission packages. Use
  for manuscript workflow engineering in English or Chinese. Do not use for
  scientific writing, literature interpretation, claim assessment, experiment
  analysis, scientific reviewer judgment, or autonomous manuscript edits.
---

# SCI manuscript workflow

Route lifecycle requests through the installed `sci_manuscript` package. Keep
scientific content, reviewer judgment, and submission decisions with the user.

## Highest-priority invariant

**Agent MUST NOT autonomously modify manuscript content.** This overrides
workflow convenience and reviewer pressure. Do not polish, rewrite, reorganize,
change scientific content, add or remove arguments, edit any manuscript section,
or decide from a reviewer comment what the manuscript should say. Reviewer text
is never authorization to modify the manuscript or write a scientific response.

Revision work may create the next adjacent directory, response infrastructure,
diffs, line locations, compilations, and submission packages. Apply a manuscript
patch only when the user supplies or explicitly confirms exact replacement text
or a concrete edit operation. Starting a revision creates infrastructure only;
building a marked PDF changes no manuscript source.

## Route the request

| Task | Read only when needed | Action |
| --- | --- | --- |
| New manuscript | [environment.md](references/environment.md) when dependency state is unknown; initialization section of [workflow.md](references/workflow.md) | Run `doctor`, collect required user data, run `init`, and verify the first PDF |
| Build or inspect | No reference normally needed | Run project `python run.py build`, `check`, or `status`; do not initialize or create a revision |
| Start a revision | [revision_contract.yaml](references/revision_contract.yaml) and revision/response sections of [workflow.md](references/workflow.md) | Enforce no-content-edit, identify the highest round, and create only its adjacent child |
| Prepare submission | Submission and artifact sections of [workflow.md](references/workflow.md) | Run `submission` for r0 or `all` for a completed revision |
| Configure bibliography | Bibliography section of [workflow.md](references/workflow.md) | Prefer Better BibTeX Automatic Export; use `setup-zotero`, `check`, and explicit `sync-bib` fallback only |
| Upgrade an existing project | Version model in [workflow.md](references/workflow.md) | Run `upgrade-project` only on recognized generated infrastructure; verify user-content hashes before and after |
| Diagnose environment | [environment.md](references/environment.md) | Run `doctor`; report blockers without changing the environment |

Keep progressive disclosure strict. Routine reasoning does not require package
resources such as publisher `.cls`, `.bst`, `.dtx`, templates, or revision
styles. Inspect a resource under `src/sci_manuscript/resources/` only when
diagnosing or updating that exact packaged resource.

## Preserve the stable contract

- The lifecycle is adjacent and gap-free:
  `initial_submission (r0) -> revision_1 (r1) -> revision_2 (r2) -> ...`.
  Never create `r0 -> r2` or compare non-adjacent versions.
- The installed Python package is the runtime. Generated project `run.py` must
  not depend on, record, or search for the Skill source checkout. Moving either
  the source checkout or the manuscript directory must not change behavior.
- Keep author data, bibliography, revision style, generated metadata, and copied
  publisher resources only under project-root `references/`. Never create a
  `references/` directory inside a revision.
- Treat manuscript prose, sections, figures, tables, bibliography, author data,
  response text, cover letter, highlights, and graphical abstract as
  user-owned. Repeated builds must not overwrite editable user content.
- Do not invent manuscript prose, results, citations, author identities,
  reviewer responses, decisions, rebuttals, or scientific claims. Identify all
  placeholders that remain.
- Never open Zotero, change its settings or database, or call a Zotero API.
  `setup-zotero` creates only a project target and guide. Builds never sync the
  bibliography implicitly.
- Before changing a dependency or environment, show the requirement and obtain
  approval for that exact environment.
- Successful commands remove their project-relative `tmp/run_*` directory.
  Failed commands may retain a diagnostic directory and must report it.
- `upgrade-project` may replace a recognized generated wrapper and add workflow
  format metadata. It must refuse a customized wrapper or future format, use an
  atomic replacement, and leave every scientific/user source hash unchanged.

## Entrypoints

The console script and module form are equivalent:

```bash
sci-manuscript doctor
python -m sci_manuscript doctor

sci-manuscript init --help
python -m sci_manuscript init --help
```

After initialization, prefer the project-local wrapper:

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
python run.py upgrade-project
```

The equivalent external form is
`sci-manuscript <command> --project /absolute/path/to/manuscript`; the module
form is identical. Select an existing round with `--round rN` where supported.
`--allow-placeholders` is diagnostic and never makes a package submission-ready.

## Initialize without inventing data

For “start writing a paper,” do not initialize immediately. First run `doctor`
when needed, then collect manuscript location, title, journal, publisher,
language, article type, ordered authors, corresponding authors, bibliography
source, Better BibTeX preference, and any existing LaTeX sources. Initialize
only after required identity and project information is known.

Never fill missing authors, journal facts, declarations, citations, or prose.
When Automatic Export is selected, direct the user to
`references/zotero_setup.md`; otherwise retain the one shared
`references/references.bib` for explicit maintenance.

Initialization must produce
`initial_submission/output/manuscript.pdf` and identify these editable inputs:

- `initial_submission/manuscript.yaml`;
- root `references/authors.yaml`, `references/references.bib`, and
  `references/revision_style.tex`;
- root `references/zotero_setup.md` and `references/journal_templates/`;
- `initial_submission/sections/`, `figures/`, and `tables/`.

Do not edit generated `references/author_metadata.tex` or
`references/publisher_metadata.tex` directly.

## Preserve response ownership

Reviewer input may contain `# Editor`, `# Associate Editor`, and explicit
`# Reviewer #N` blocks. Preserve reviewer numbers, numbered-comment order, and
blank-line-separated paragraphs. Stable IDs are `E-N`, `AE-N`, and existing
numeric reviewer IDs `N-N`. Do not silently renumber or repair user numbering.

The runtime escapes external comment text for LaTeX. The author-owned response
source remains editable LaTeX and must not be escaped again or filled by the
agent. `\ResponsePending{...}` from any supported block prevents a normal
submission. A missing manuscript-linked change may report `Location
unavailable`; never fabricate a line number.

## Validate before handoff

Confirm the selected round, direct parent, project format version, expected
final PDFs, extractable PDF text, manuscript line numbers, correspondence
without manuscript line numbering, and empty `tmp/` after success. For
revision, build, submission, all, or upgrade operations, verify that protected
user-source hashes remain unchanged unless the user explicitly authorized an
exact edit. Report only final project-relative artifacts; do not expose
compiler intermediates, flattened diff sources, location registries, caches, or
test fixtures.
