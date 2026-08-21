# sci-manuscript-skill

## 1. Purpose

`sci-manuscript-skill` is an agent-operated workflow for managing the complete
LaTeX manuscript lifecycle: initial drafting, first submission, adjacent
revisions, reviewer responses, marked manuscripts, and version-specific
submission packages. It gives every paper a predictable structure and one
project command-line entrypoint while keeping author metadata, bibliography,
response material, and final PDFs synchronized.

The project is designed to solve engineering problems around manuscript work:
unstructured LaTeX folders, ambiguous revision ancestry, duplicated author
information, fragile `latexdiff` commands, scattered response letters, and
time-consuming submission packaging. It does **not** generate scientific
content, invent results, rewrite claims without instruction, judge reviewer
comments, or replace the current instructions of a target journal. Authors
remain responsible for the research, text, data, figures, citations, ethics,
and submission decisions.

## 2. Features

| Feature | Description |
| --- | --- |
| Agent workflow | `SKILL.md` defines environment inspection, information collection, initialization, validation, and handoff |
| Manuscript lifecycle | Maintains initial submission and any number of adjacent revisions |
| Publisher resources | Bundles Elsevier, Springer Nature, ACS, and a general Chinese-journal category |
| Dynamic metadata | Generates publisher-specific LaTeX author commands from one manuscript-level YAML author library |
| Revision comparison | Produces clean and marked manuscripts from adjacent versions with `latexdiff` |
| Response letter | Creates structured reviewer-response sources and validates unfinished placeholders |
| Submission packaging | Builds cover letter, highlights, graphical abstract, manuscript, response, and checklist artifacts on demand |
| Zotero workflow | Recommends Better BibTeX Automatic Export to the one shared bibliography without controlling Zotero |
| Citation validation | Reports manuscript citation keys missing from the shared BibTeX database without modifying sources |
| Isolated builds | Routes compiler intermediates through `tmp/` and removes successful temporary runs |
| PDF verification | Uses Poppler text extraction and rendering tools for output QA |

## 3. Actual output

The images below come from an anonymous test fixture compiled by the public API.
They contain no unpublished research content or local filesystem paths.

| Marked manuscript | Response letter |
| --- | --- |
| ![Anonymous marked manuscript example](docs/images/marked_manuscript.png) | ![Anonymous response letter example](docs/images/response_letter.png) |

![Anonymous submission package structure](docs/images/submission_package.png)

## 4. Installation

### Runtime requirements

- Python 3.11 or newer;
- PyYAML 6.x;
- Tectonic, or a supported TeX Live toolchain with `latexmk` and pdfLaTeX or
  XeLaTeX;
- `latexdiff`;
- Poppler tools `pdftotext` and `pdftoppm`;
- a bibliography backend: Tectonic's integrated BibTeX processing, BibTeX, or
  Biber.

Ruff and Mypy are development-only tools. Zotero Better BibTeX is an optional
desktop integration. The recommended workflow uses its Automatic Export, but
the skill never opens Zotero, changes its settings, or accesses its database.

Clone the repository, create or activate a Python environment, and install the
single Python runtime dependency:

```bash
git clone https://github.com/cigit-zgy/sci-manuscript-skill.git
cd sci-manuscript-skill

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On macOS with Homebrew, the supported compact toolchain is:

```bash
brew install tectonic latexdiff poppler
```

TeX Live may be used instead when `latexmk` and a compatible LaTeX engine are
available. Chinese projects require XeLaTeX-compatible compilation and usable
Chinese fonts. Always inspect the selected environment after installation:

```bash
python scripts/run.py doctor
```

`doctor` is read-only. A `READY` result means all required workflow categories
were found. A `BLOCKED` result lists missing requirements and exits with status
2; it never installs or upgrades anything.

## 5. Quick Start

The preferred interface is to ask an agent to execute the skill entrypoint:

```text
Execute /absolute/path/to/sci-manuscript-skill/SKILL.md.
```

The agent follows this sequence:

```mermaid
flowchart TD
    A[Execute SKILL.md] --> B[Check environment]
    B --> C[Collect project, journal, author, and bibliography information]
    C --> D[Select publisher resource]
    D --> E[Initialize initial_submission]
    E --> F[Compile and validate the first PDF]
    F --> G[Write manuscript]
    G --> H{Next action}
    H -->|Build| I[Clean manuscript]
    H -->|Revise| J[Adjacent revision]
    H -->|Submit| K[Version-local package]
```

If a required dependency is missing, the agent reports it and asks before any
environment change. Once the environment is ready, provide a new project path,
manuscript title, target journal, publisher category, language, author YAML,
author order, and optional BibTeX file. If no author or bibliography file is
available, the agent can copy explicit examples only after confirming that
they must be replaced.

The equivalent direct initialization command is:

```bash
python scripts/run.py init \
  --project /absolute/path/to/my-paper \
  --title "Manuscript title" \
  --journal "Target Journal" \
  --publisher elsevier \
  --language en \
  --authors /absolute/path/to/authors.yaml \
  --author "First Author" \
  --author "Corresponding Author" \
  --bib /absolute/path/to/references.bib
```

Initialization creates and compiles `initial_submission` (internal round r0).
Continue from the generated project root:

```bash
cd /absolute/path/to/my-paper
python run.py build
python run.py check
python run.py submission
python run.py status
```

The copied project `run.py` delegates to the installed skill implementation
recorded during initialization. Keep that installation available. If the skill
repository is moved, set `SCI_MANUSCRIPT_SKILL_ROOT` to its new absolute path
before running project commands.

## 6. Command line

Every generated project contains one copied `run.py`. Use that entrypoint for
all later operations.

| Command | Purpose |
| --- | --- |
| `doctor` | Inspect required and optional environment dependencies without installing anything |
| `init` | Create `initial_submission` (r0), generate metadata, and compile the first manuscript PDF |
| `build` | Compile the selected version's clean manuscript |
| `revision` | Create the next adjacent revision and initialize its response source |
| `submission` | Build version-local submission materials and package |
| `all` | Build clean, marked, response, and submission outputs for the selected version |
| `setup-zotero` | Prepare the Better BibTeX Automatic Export guide and shared export target |
| `check` | Report citation keys absent from the shared BibTeX database |
| `sync-bib` | Atomically replace the shared BibTeX database from an explicit export as a manual fallback |
| `status` | Report lifecycle ancestry and generated artifacts |

Run `python run.py <command> --help` for command-specific options. `build`,
`submission`, and `all` accept `--round rN` for an existing version.
`revision` accepts reviewer comments as Markdown through `--reviews`. The
`--allow-placeholders` option is diagnostic only; a package containing pending
responses is not submission-ready.

Compatibility aliases are `render` for `build`, `revise` for `revision`,
`package` for `submission`, and `validation` for `check`. They are visible in
`python run.py --help` and preserve the canonical command behavior.

`submission` and `all` print every final artifact actually produced, including
clean, marked, response, cover-letter, highlights, graphical-abstract, checklist,
and package paths when enabled. Paths are project-relative; compiler staging and
temporary files are never presented as deliverables.

## 7. Python API

The installable `sci_manuscript` package is the stable programmatic interface.
CLI commands and Python calls use the same lifecycle implementation; modules in
`scripts/` remain internal runtime details.

```python
from sci_manuscript import ManuscriptProject, initialize_manuscript

initialized = initialize_manuscript(
    path="/absolute/path/to/my-paper",
    title="Anonymous manuscript title",
    journal="Target Journal",
    publisher="elsevier",
    language="en",
    authors="/absolute/path/to/authors.yaml",
    selected_authors=("First Author", "Corresponding Author"),
    bib="/absolute/path/to/references.bib",
)

project = ManuscriptProject(initialized.project)
status = project.status()
build = project.build()
revision = project.start_revision(reviews="/absolute/path/to/reviews.md")
submission = project.build_all()
```

All operations return frozen dataclass results containing `Path` objects for
final artifacts. They do not expose `argparse.Namespace` or compiler, diff,
metadata-rendering, and temporary-file internals.

| CLI | Python API |
| --- | --- |
| `run.py doctor` | `project.doctor()` |
| `run.py init ...` | `initialize_manuscript(...)` |
| `run.py status` | `project.status()` |
| `run.py build` | `project.build()` |
| `run.py revision` | `project.start_revision(reviews=...)` |
| `run.py submission` | `project.prepare_submission()` |
| `run.py all` | `project.build_all()` |
| `run.py check` | `project.check()` |
| `run.py setup-zotero` | `project.setup_zotero()` |
| `run.py sync-bib` | `project.sync_bib(...)` |

## 8. User configuration

### `manuscript.yaml`

Each version owns one `manuscript.yaml` containing title, article type,
language, journal, selected publisher template, semantic revision identity,
immediate parent, submission switches, and author role groups. It does not
duplicate emails or affiliations. Revision creation copies this YAML from the
direct parent and changes only `revision.name`, `revision.parent`, and
`revision.round`.

```yaml
manuscript:
  title: Manuscript title
  article_type: Research Paper
  language: en

journal:
  name: Target Journal
  publisher: elsevier
  template: elsarticle

revision:
  name: initial_submission
  parent: null
  round: r0

submission:
  cover_letter: true
  highlights: true
  graphical_abstract: true

authors:
  first_authors:
    - First Author
    - Co-first Author
  corresponding_authors:
    - Corresponding Author
    - Co-corresponding Author
  authors:
    - Other Author
```

### `references/authors.yaml`

This manuscript-level author library stores complete English and Chinese
names, default roles, affiliation references, affiliation addresses, and known
email addresses. Email is optional for ordinary authors but required for every
author selected as corresponding. The names selected in each version's
`manuscript.yaml` must exactly match keys in this file. Multiple first and
corresponding authors are supported. Python expands the selected version and shared library into
`references/author_metadata.tex` and `references/publisher_metadata.tex`.
Manuscript and correspondence templates use these generated shared sources;
do not edit them directly.

### `references/references.bib`

This is the only bibliography used by every version. Prefer Zotero Better
BibTeX Automatic Export as described below. When Automatic Export is
unavailable, atomically replace it from an explicit export using the manual
fallback:

```bash
python run.py sync-bib --bib-export /absolute/path/to/export.bib
```

### `sections/`, `figures/`, and `tables/`

Publisher-specific section files are structural placeholders. Replace all
placeholder prose with author-written content. The figures and tables
directories start empty; add only manuscript assets. The workflow does not
create scientific figures or infer missing content.

## 9. Project structure

```text
manuscript/
├── run.py
├── references/                   # manuscript-level shared resources
│   ├── authors.yaml
│   ├── author_metadata.tex       # generated
│   ├── publisher_metadata.tex    # generated
│   ├── references.bib
│   ├── revision_style.tex
│   ├── zotero_setup.md
│   └── journal_templates/
│       ├── elsevier/
│       ├── nature/
│       ├── acs/
│       └── chinese/
├── initial_submission/          # r0, parent null
│   ├── manuscript.yaml
│   ├── manuscript.tex
│   ├── preamble.tex
│   ├── sections/
│   ├── figures/
│   ├── tables/
│   ├── submission/              # editable sources populated on demand
│   └── output/
├── revision_1/                  # r1, parent r0
├── revision_2/                  # r2, parent r1
└── tmp/
```

`initial_submission` is the complete first-submission state. Each
`revision_N` is copied only from `revision_(N-1)` (or from
`initial_submission` for revision 1) and adds its own response source,
submission material, and outputs. Editable submission sources and response
attachments are inherited, while the previous round's response letter and
generated package are excluded. Revision directories never contain a
`references/` directory. `tmp/` contains isolated
compiler and diff work and is empty after successful commands. Manuscript
sources, outputs, and submission files never live directly at the project
root. Shared author data, bibliography, revision style, and all publisher
classes exist exactly once under root `references/`. Workflow execution still
uses the installed skill code.

## 10. Zotero and bibliography workflow

The recommended bibliography workflow is Zotero Better BibTeX Automatic
Export. It keeps the BibTeX database current while leaving LaTeX with one
explicit, reproducible input:

```mermaid
flowchart LR
    A[Zotero collection] --> B[Better BibTeX Automatic Export]
    B --> C[references/references.bib]
    C --> D[LaTeX compilation]
    D --> E[PDF]
```

1. Install the Zotero Better BibTeX extension.
2. Export the manuscript collection using format **Better BibTeX**.
3. Choose the exact export path shown in `references/zotero_setup.md`.
4. Enable **Keep updated**.
5. Run `python run.py check`, then build normally.

`python run.py setup-zotero` recreates a missing bibliography target and setup
guide. It does **not** open Zotero, change Zotero settings, access the Zotero
database, or call a Zotero API. Builds never synchronize the bibliography
implicitly. `sync-bib` remains an explicit manual fallback.

## 11. Publisher templates

| Publisher key | Bundled resource | Intended use |
| --- | --- | --- |
| `elsevier` | `elsarticle` | Elsevier article workflow |
| `nature` | Springer Nature `sn-jnl` | Generic Springer Nature authoring resource |
| `acs` | `achemso` | ACS article workflow |
| `chinese` | `kxtbcas` | General Chinese-journal starting point |

The `nature` key does not claim a dedicated official class for every Nature
Portfolio journal. The `chinese` category is not a universal official Chinese
journal template. Publisher resources and default section mappings live in
`assets/journal_templates/<publisher>/`; each resource README records its
source, version, date, license, and any local compatibility adaptation.

Bundled resources are tested with author, figure, citation, and bibliography
content, but journals update instructions independently. Check the current
Guide for Authors and update the selected resource when necessary. Upstream
templates retain their own licenses; see `THIRD_PARTY_NOTICES.md`.

## 12. Revision workflow

The ancestry is explicit and gap-free:

```mermaid
flowchart LR
    R0[initial_submission r0] --> R1[revision_1 r1]
    R1 --> R2[revision_2 r2]
```

Create the next version with:

```bash
python run.py revision --reviews /absolute/path/to/reviewer-comments.md
```

The command rejects r0-to-r2 jumps and copies manuscript state only from the
immediate parent; it never copies or regenerates the shared references tree.
Starting a revision does not authorize or perform a manuscript edit, and the
parent source hash remains unchanged. Reviewer comments alone never authorize
the agent to decide or draft replacement text; an exact patch or concrete edit
operation must be supplied or explicitly confirmed by the user.
Reviewer-linked additions use `\review{1-1}{Revised text.}`; author-initiated
additions use `\selfadd{Additional text.}`. The marked manuscript compares the
current version against its direct parent, so added and deleted text remain
traceable. User-adjustable colors and markup appearance are isolated in
`references/revision_style.tex`.

```mermaid
flowchart LR
    A[Parent clean manuscript] --> B[latexdiff]
    C[Current clean manuscript] --> B
    B --> D[Marked manuscript]
    D --> E[Computed line locations]
    E --> F[Response letter]
```

Complete each `\ResponsePending{review-id}` in the version-local response
letter, then run `python run.py all`. A revision package contains the clean
manuscript, marked manuscript, response letter, cover letter, highlights,
graphical abstract, and checklist according to the YAML submission switches.
Manuscript PDFs have continuous line numbers; correspondence and supplementary
submission files do not.

```mermaid
flowchart TD
    A[Version-local submission source] --> B[Submission package]
    C[Manuscript PDF] --> B
    D[Cover letter] --> B
    E[Highlights] --> B
    F[Graphical abstract] --> B
    G[Marked manuscript and response] --> B
```

## 13. Validation and development

The repository separates agent routing, deterministic execution, on-demand
guidance, static output resources, and the two validation layers:

| Directory | Purpose |
| --- | --- |
| `SKILL.md` | Agent routing, authorization boundaries, and workflow invariants |
| `src/sci_manuscript/` | Stable Python API, structured results, shared lifecycle orchestration, and thin CLI adapter |
| `scripts/` | Internal deterministic workspace, metadata, compiler, diff, and response runtime plus the project bootstrap |
| `references/` | Agent-readable environment and lifecycle guidance loaded only when needed |
| `assets/` | Author examples, revision style, manuscript sources, correspondence templates, and publisher resources copied or compiled by the runtime |
| `evals/` | Agent triggering, routing, authorization, and scope-boundary evaluations |
| `tests/` | Software correctness, lifecycle invariants, and actual publisher compilation |

`SKILL.md` is intentionally a compact router. A normal `build` does not require
the environment reference, and publisher `.cls`, `.bst`, and `.dtx` files are
assets rather than routine agent context. `evals/` defines behavioral tasks;
`tests/` remains the executable software verification suite.

Run the release checks from the repository root:

```bash
pytest
ruff format --check .
ruff check .
mypy src scripts tests
```

Release validation additionally exercises a fresh r0 -> r1 -> r2 lifecycle,
submission packages, PDF text extraction, rendered pages, temporary-file
cleanup, and the skill frontmatter validator. Development tools are optional
for manuscript users but required before publishing changes.

`.github/workflows/test.yml` runs Pytest, Ruff format/check, and Mypy on pushes
and pull requests. Publisher class compilation remains part of the local
release gate when Tectonic is available.

## 14. License

Original workflow code, documentation, tests, and original templates are
released under the MIT License in `LICENSE`. Bundled publisher class and
bibliography resources are third-party works and retain their upstream terms.
The maintainer-provided Chinese class is documented separately because its
source did not include an embedded license notice; the maintainer has confirmed
that it may be distributed publicly with the project. Review
`THIRD_PARTY_NOTICES.md` and each publisher-resource README before
redistribution.
