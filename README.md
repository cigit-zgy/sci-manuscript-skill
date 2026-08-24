# sci-manuscript-skill

A reproducible manuscript lifecycle framework for scientific writing projects. It manages manuscript initialization, journal-aware compilation, peer-review revision, reviewer response linkage, and submission preparation while keeping scientific content under author control.

## Overview

Scientific manuscripts often accumulate fragile file structures during revision: duplicated LaTeX files, disconnected reviewer responses, unclear revision states, and mixed temporary artifacts. `sci-manuscript-skill` provides a structured workflow that separates user scientific content from manuscript infrastructure.

The framework supports:

- manuscript initialization;
- journal-aware compilation;
- revision rounds with reviewer linkage;
- clean and marked manuscript generation;
- response letter generation;
- submission artifact preparation.

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

### Reproducible compilation

- Built-in journal resources
- Isolated build environment
- PDF validation and layout checks

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
│   └── revision_style.tex
├── initial_submission/
│   └── meta.yaml
├── revision_01/
├── state/
└── tmp/
```

Users edit:

- `meta.yaml`
- optional project `references/authors.yaml` overrides
- manuscript sections
- figures and tables
- reviewer responses

The Skill manages internally:

- journal templates;
- manuscript preamble resources;
- compiler resources;
- temporary build files.

The bundled `resources/authors.yaml` is the default reusable person-level
library and is not copied by metadata-first initialization. A pre-existing
project author library is resolved first. Packaged resources are resolved
during compilation and do not need to be copied into user projects.

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

`sections/00_frontmatter.tex` stores the user-owned manuscript title;
publisher-appropriate section sources store abstract and keyword text.

The active author library stores only person-level names, email, affiliations,
and bilingual biography strings. Names, affiliations, email, and biographies
are not duplicated in `meta.yaml`.

For a Chinese publisher, the build resolves `meta.yaml` plus the active author
library into the runtime-only `tmp/<run>/publisher_metadata.tex`. It generates
Chinese and English titles and abstracts, funding, and
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

## Development

```bash
pytest
ruff format --check .
ruff check .
mypy src tests
python -m build
```

## Documentation

Detailed workflow and implementation information are maintained separately:

- `SKILL.md` — agent execution instructions
- `references/` — detailed workflows and design documentation

## License

MIT License.
