# sci-manuscript-skill

Current stable contract: **2.0.0**.

An isolated manuscript lifecycle framework for scientific writing projects. It manages manuscript initialization, journal-aware compilation, peer-review revision, reviewer response linkage, and submission preparation while keeping scientific content under author control.

## Overview

Scientific manuscripts often accumulate fragile file structures during revision: duplicated LaTeX files, disconnected reviewer responses, unclear revision states, and mixed temporary artifacts. `sci-manuscript-skill` provides a structured workflow that separates user scientific content from manuscript infrastructure.

The framework supports:

- manuscript initialization;
- journal-aware compilation;
- revision rounds with reviewer linkage;
- clean and marked manuscript generation;
- response letter generation;
- submission artifact preparation.

The package owns LaTeX infrastructure. Authors own manuscript prose, metadata,
figures, tables, review comments, response bodies, and enabled submission
sources. The workflow never invents or rewrites scientific content.

## Features

### Manuscript lifecycle

- Initial submission (`initial_submission`)
- Sequential revision rounds (`revision_01`, `revision_02`, ...)
- Submission preparation

### Revision management

- Reviewer comment registry
- Response linkage audit
- Reviewer-linked additions
- Clean manuscript generation
- Marked manuscript generation

### Isolated compilation

- Built-in journal resources
- Isolated build environment
- PDF validation and layout checks

The build is deterministic with respect to the selected source, installed Skill
resources, author library, bibliography, toolchain, and fonts. It does not
promise byte-identical PDFs across different toolchain or font installations.

## Quick start

```bash
git clone https://github.com/cigit-zgy/sci-manuscript-skill.git
cd sci-manuscript-skill
python -m pip install .
sci-manuscript doctor
```

Initialize a metadata-first manuscript project:

```bash
sci-manuscript init --project /path/to/project
```

The command creates a fully commented `initial_submission/meta.yaml` and prints
`Please edit meta.yaml before build.` It does not compile, select authors, or
invent manuscript metadata. Explicit command-line fields remain available for
automated initialization.

Build:

```bash
sci-manuscript build --project /path/to/project
```

## Project structure

User-facing manuscript projects follow this structure:

```text
manuscript/
├── references/
│   ├── references.bib
│   ├── revision_style.tex
│   └── journal_template/       # custom publisher only
├── initial_submission/
│   └── meta.yaml
├── revision_01/
├── state/                      # machine-owned persistent state and manifests
└── tmp/
```

Users edit:

- `meta.yaml`
- `sections/00_frontmatter.tex` for title, abstract, and keywords
- manuscript sections
- figures and tables
- reviewer comments and responses
- `submission/cover_letter_body.tex`, highlights, checklist, and graphical
  abstract source when those deliverables are enabled

The Skill manages internally:

- journal templates;
- manuscript preamble resources;
- compiler resources;
- temporary build files.

The active author library is the configured user library, falling back to the
bundled `resources/authors.yaml`. It is never copied into a project. Packaged
resources are resolved during compilation and do not need to be copied into
user projects.

Built-in publisher/language pairs are Chinese/`zh`, Elsevier/`en`, Nature/`en`,
and ACS/`en`. A custom template supplied at initialization declares its own
supported languages and is copied once to `references/journal_template/`.

## Workflow

```text
Draft
  ↓
Initial submission
  ↓
Peer review
  ↓
Revision
  ↓
Response preparation
  ↓
Resubmission
```

## Revision visualization

The marked manuscript uses three visual meanings:

| Type | Appearance |
| --- | --- |
| Author additions | Blue text |
| Reviewer-linked additions | Red text |
| Deleted content | Light-gray strikeout |

Reviewer-linked additions are created through explicit `\\review{}` markers so that reviewer comments, responses, and manuscript changes remain traceable.
Ordinary additions are rendered as blue text without underline; this wording
describes the existing revision contract and is unchanged by metadata work.
Reviewer-linked additions use red text without underline, while deletions retain
the light-gray strikeout.

## Configuration

`meta.yaml` stores workflow metadata:

- funding, language, and article type;
- journal and publisher;
- publication-order author IDs and corresponding-author IDs.

`sections/00_frontmatter.tex` stores the user-owned manuscript title, abstract,
and keywords. These visible fields participate in the same direct-parent
revision comparison as body sections; generated visible funding metadata is
included in that comparison as well. Historical bibliography state is frozen
under `state/<round>/` for key-based machine comparison, while marked output
always renders the current bibliography only. `\ReviewReference{ID}{key[,keys...]}`
adds eligible current-entry lines to the same response-location set as
manuscript `\review` additions.

The active author library stores only person-level names, email, affiliations,
and bilingual biography strings. Names, affiliations, email, and biographies
are not duplicated in `meta.yaml`.

For a Chinese publisher, the build resolves the user frontmatter, `meta.yaml`,
and the active author library into the runtime-only
`tmp/<run>/publisher_metadata.tex`. It generates Chinese and English titles and
abstracts, funding, and
`firstauthorcn`/`firstauthoren`/`corrauthorcn`/`corrauthoren`; it is never written
into `initial_submission/`.

`revision_style.tex` stores user-editable revision visualization settings.

## Architecture

```text
User manuscript project
          |
          v
sci-manuscript-skill
          |
 ┌────────┼────────┐
Templates Compiler Revision engine
          |
          v
      PDF outputs
```

The project directory contains scientific content. The Skill package contains reusable infrastructure.

For revision rounds, `build` deterministically refreshes clean, marked, and
response PDFs. The response PDF reads the user-owned `\ResponseLetter{...}` and
`\Response{ID}{...}` bodies only from current `response/responses.tex`, then
inserts the unified final-marked locations derived from `\review` and
`\ReviewReference`; malformed response syntax suppresses only untrusted
response output.

Associate Editor (`AE-N`), Editor (`E-N`), and Reviewer (`N-N`) detailed
comments use the same response and provenance workflow. `build` remains
available while the audit is incomplete so authors can inspect the current
clean/marked PDFs and a parseable response preview. `submission` requires a
complete audit and complete enabled submission sources.

Submission correspondence is split between package-owned document templates
and user-owned bodies. Users edit `submission/cover_letter_body.tex`; they do
not maintain a complete cover-letter document. Unresolved `\guidance{...}`
blocks, template tokens, and pending highlights/graphical-abstract markers block
formal submission.

Final user PDFs live in `output/`; persistent audit and reproducibility data,
including `state/<round>/build_manifest.yaml`, live in `state/`; reproducible
compiler and diagnostic files live only in `tmp/`. Successful operations remove
their temporary run directory. The manifest records hashes and effective
resource/toolchain identities without recording private absolute project paths.

## Development

```bash
pytest
ruff format --check .
ruff check .
mypy src tests
python -m build
```

The supported built-in matrix is Chinese/`zh`, Elsevier/`en`, Nature/`en`, and
ACS/`en`. Python 3.11 or newer is required. Tectonic is the primary,
release-gated engine; the traditional `latexmk` driver is supported with an
appropriate XeLaTeX/pdfLaTeX and BibTeX/Biber toolchain but does not have equal
release evidence. macOS ARM and Linux x86_64 are covered by CI, with real CJK
integration on macOS.

## From 1.0 to 2.0

Version 2.0 is intentionally strict. Author roles are list-valued
`authors.first`, `authors.corresponding`, and `authors.other`; visible title,
abstract, and keywords live in `sections/00_frontmatter.tex`; editable replies
use generated `\Response{ID}{body}` entries; cover prose lives in
`cover_letter_body.tex`; revision build and submission have different
completeness policies; creation, review-index, generated-artifact, and build
manifest records live under `state/`. A v1 workspace is detected and rejected
with an archive-first migration message rather than silently rewritten. See
[the workflow migration note](references/workflow.md#v1-workspace-detection).

## Rendered examples

![Marked manuscript showing semantic revision colors](docs/images/marked_manuscript.png)

![Response letter with automatically derived locations](docs/images/response_letter.png)

## Documentation

Detailed workflow and implementation information are maintained separately:

- `SKILL.md` — agent execution instructions
- `references/` — detailed workflows and design documentation

## License

The Python package and the project-maintained Chinese `kxtbcas.cls` resource are
MIT licensed. The bundled `kxtbcas-numeric.bst` is a derived third-party
bibliography style; its provenance and license are recorded in
`THIRD_PARTY_NOTICES.md`.
