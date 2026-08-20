---
name: sci-manuscript-skill
description: Initialize and operate a traceable LaTeX scientific-manuscript lifecycle from initial submission through adjacent revisions, reviewer responses, marked manuscripts, and version-local submission packages. Use for manuscript workflow engineering, not scientific-content generation or reviewer judgment.
---

# SCI manuscript lifecycle

Act as the workflow operator. A user may invoke this skill by asking to execute
this `SKILL.md`; they do not need to know the internal Python modules or command
sequence. Follow the mandatory order below:

```text
inspect environment -> ask for approval if blocked -> collect project data
-> initialize -> compile -> validate -> hand off editable files
```

Do not invent research content, alter scientific claims without instruction,
or decide whether reviewer comments are correct.

## Step 1. Environment inspection

Inspect the selected environment before asking project questions. Start with
read-only discovery such as `python3 --version` and `command -v` for the tools
below, then run:

```bash
python3 scripts/run.py doctor
```

### Required dependencies

| Category | Dependency | Purpose |
| --- | --- | --- |
| Python | Python >= 3.11 | Workflow execution |
| Python package | PyYAML | YAML parsing |
| LaTeX | Tectonic or supported TeX Live toolchain | PDF compilation |
| Diff | latexdiff | Adjacent revision comparison |
| PDF tools | Poppler (`pdftotext`, `pdftoppm`) | Text and visual PDF validation |
| Bibliography | Tectonic-integrated BibTeX, BibTeX, or Biber | Reference processing |

### Optional dependencies

| Dependency | Purpose |
| --- | --- |
| Zotero Better BibTeX | Explicit `.bib` export and synchronization |
| Ruff | Development formatting and lint |
| Mypy | Development static checking |

Treat `Result: READY` as permission to continue the workflow, not as permission
to modify the machine. If the result is `BLOCKED`:

1. show the user the missing required dependencies and the selected Python or
   Conda environment;
2. ask once whether they want installation instructions or installation in
   that specific environment;
3. do not install, upgrade, activate, or modify anything before confirmation;
4. after confirmation, read [environment.md](references/environment.md), use
   the platform-appropriate method, and rerun `doctor`;
5. stop cleanly if the user declines or the required checks remain blocked.

Do not treat missing optional dependencies as a blocker. Better BibTeX is a
manual integration and must never be contacted automatically.

## Step 2. Project information

Collect the following before initialization:

| Required information | Accepted value |
| --- | --- |
| Project path | New or empty directory chosen by the user |
| Manuscript title | User-provided title; never invent one |
| Target journal | User-provided journal name |
| Publisher template | `elsevier`, `nature`, `acs`, or `chinese` |
| Language | `en` or `zh` |
| Article type | Defaults to `Research Paper` only with user acceptance |

For authors, ask whether an existing `authors.yaml` is available and request
its path and author order. If none exists, explain that the generic
`references/authors.yaml` example will be copied and must be replaced before
submission. Never silently treat example identities as real authors.

For bibliography, ask whether an existing `references.bib` is available. If
none exists, obtain confirmation to copy the explicit placeholder and remind
the user to replace it. Zotero synchronization remains optional and explicit.

Template notes:

- `nature` selects the bundled Springer Nature `sn-jnl` resource; it is not a
  dedicated official class for every Nature Portfolio journal.
- `chinese` selects a general Chinese-journal workflow whose current class
  resource is the maintainer-provided `kxtbcas.cls`.

## Step 3. Initialize manuscript project

Use the one public source entrypoint with all collected inputs:

```bash
python3 scripts/run.py init \
  --project /absolute/path/to/project \
  --title "Manuscript title" \
  --journal "Target Journal" \
  --publisher elsevier \
  --language en \
  --authors /absolute/path/to/authors.yaml \
  --author "First Author" \
  --author "Corresponding Author" \
  --bib /absolute/path/to/references.bib
```

Omit `--authors` or `--bib` only after the placeholder choice was confirmed.
For Chinese projects use `--publisher chinese --language zh`. Never initialize
a non-empty directory or overwrite an existing lifecycle.

Initialization performs this deterministic sequence:

```text
select publisher resource -> create project structure -> write manuscript.yaml
-> copy author and bibliography snapshots -> generate author_metadata.tex
-> compile initial PDF -> clean temporary build files
```

## Step 4. Validate and hand off

Initialization must produce
`initial_submission/output/manuscript.pdf`. Confirm:

- the expected project structure exists and the root has no manuscript files;
- the PDF opens, contains extractable text and continuous line numbers;
- selected authors, affiliation, and corresponding-author email match the
  supplied YAML;
- `tmp/` is empty after success;
- no compiler, latexdiff, location-extraction, or test files are exposed as
  user artifacts.

Report every placeholder that still requires replacement. Do not call the
project ready for submission while example authors, bibliography, manuscript
prose, or reviewer-response placeholders remain.

## Files requiring user replacement

The following bundled content is initialization material, not research content:

1. `templates/manuscript/references.bib` becomes
   `initial_submission/references/references.bib`; replace the example BibTeX.
2. `references/authors.yaml` becomes
   `initial_submission/references/authors.yaml`; replace names, emails,
   affiliations, roles, and corresponding-author data unless a real file was
   supplied.
3. Publisher-mapped files in `initial_submission/sections/` are structural
   placeholders. Replace the abstract and every manuscript section.
4. `initial_submission/figures/` is intentionally empty. Add only real figure
   assets and remove temporary test artwork.

Do not edit generated `references/author_metadata.tex` directly.

## Project contract

```text
project/
├── run.py
├── initial_submission/        # r0, parent null
│   ├── manuscript.yaml
│   ├── manuscript.tex
│   ├── preamble.tex
│   ├── sections/
│   ├── figures/
│   ├── tables/
│   ├── references/
│   ├── submission/            # created on demand
│   └── output/
├── revision_1/                # r1, parent r0
├── revision_2/                # r2, parent r1
└── tmp/
```

Every revision is copied only from its immediate parent and owns its
manuscript, reference snapshot, response material, submission package, and
outputs. The project root must not contain those version-local files.

## Continue an initialized project

Use only the copied project-root entrypoint:

```bash
python run.py doctor
python run.py build
python run.py revision --reviews /absolute/path/to/comments.md
python run.py submission
python run.py all
python run.py sync-bib --bib-export /absolute/path/to/export.bib
python run.py status
```

`revision` creates only the next adjacent version. Use
`\review{1-1}{text}` for reviewer-linked changes and `\selfadd{text}` for
author-initiated additions. Replace every generated
`\ResponsePending{1-1}` before a normal `all`; the diagnostic
`--allow-placeholders` flag is not a submission-ready mode.

`sync-bib` copies an explicit Better BibTeX export into every existing
version. It never connects to Zotero. Read
[workflow.md](references/workflow.md) before revision or submission work and
the selected resource README before adapting an exact journal class.

## Safety and output rules

Manuscript, clean-manuscript, and marked-manuscript PDFs use continuous line
numbers. Cover letters, response letters, highlights, and graphical abstracts
do not. Successful commands remove `tmp/run_*`; failed commands retain a
project-relative diagnostic directory. Default CLI output reports only final
project-relative artifacts.

Submission and response sources are created once so user edits survive later
builds. Never publish compiler intermediates, extracted review-location files,
or test fixtures as manuscript artifacts.
