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

Initialize a manuscript project:

```bash
sci-manuscript init \
  --project /path/to/project \
  --title "Manuscript title" \
  --journal "Target Journal" \
  --publisher elsevier \
  --language en \
  --article-type "Research Article"
```

Build:

```bash
sci-manuscript build --project /path/to/project
```

## Project structure

User-facing manuscript projects follow this structure:

```text
manuscript/
├── references/
│   ├── authors.yaml
│   ├── meta.yaml
│   ├── references.bib
│   └── revision_style.tex
├── initial_submission/
├── revision_01/
├── state/
└── tmp/
```

Users edit:

- `meta.yaml`
- `authors.yaml`
- manuscript sections
- figures and tables
- reviewer responses

The Skill manages internally:

- journal templates;
- manuscript preamble resources;
- compiler resources;
- temporary build files.

Packaged resources are resolved during compilation and do not need to be copied into user projects.

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

## Configuration

`meta.yaml` stores manuscript metadata:

- journal
- publisher
- language
- article type

`authors.yaml` stores reusable author information.

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
