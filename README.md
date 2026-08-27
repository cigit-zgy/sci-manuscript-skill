# sci-manuscript-skill

`sci-manuscript-skill` manages an isolated LaTeX manuscript lifecycle: project
initialization, journal-aware compilation, adjacent revision rounds,
highlighted revised manuscripts, reviewer responses, and submission artifacts.
Authors retain authority over all scientific content.

## Why

LaTeX revision rounds combine scientific sources, publisher resources,
bibliography state, reviewer provenance, response locations, and several final
PDFs. Manual copies make ancestry and submission state difficult to verify.
This package keeps those responsibilities separate and makes every published
artifact traceable to one explicit manuscript round.

## What it provides

The package separates editable manuscript sources from installed publisher
resources, temporary compiler files, persistent state, and final PDFs. It does
not invent manuscript prose, responses, metadata, references, or author roles.

Built-in publisher/language pairs are Chinese/`zh`, Elsevier/`en`, Nature/`en`,
and ACS/`en`. Custom templates can be supplied during initialization.

## Installation

Python 3.11 or newer is required.

```bash
git clone https://github.com/cigit-zgy/sci-manuscript-skill.git
cd sci-manuscript-skill
python -m pip install .
sci-manuscript doctor
```

`doctor` reports missing LaTeX, `latexdiff`, and PDF-tool dependencies for the
configured environment. Response builds separately fail closed unless Times New
Roman is available through fontconfig.

## Quick start

```bash
sci-manuscript init --project /path/to/paper
# Edit manuscript/initial_submission/meta.yaml and manuscript sources.
sci-manuscript build --project /path/to/paper
sci-manuscript revision --project /path/to/paper --yes
# Edit revision_01 sources and responses; add \review only for reviewer ownership.
sci-manuscript build --project /path/to/paper --target marked
sci-manuscript build --project /path/to/paper --target all
```

## Core workflow

```text
initialize -> build initial submission -> create revision
           -> mark current additions -> build responses -> prepare submission
```

The CLI builds the minimum dependency set for the selected round and target,
validates the result, and atomically publishes only current artifacts.

## Project lifecycle

```text
manuscript/
├── references/                 # current editable BibTeX and revision style
├── initial_submission/         # r00
├── revision_01/                # r01, parent r00
├── revision_02/                # r02, parent r01
├── state/                      # manifests and immutable historical state
└── tmp/                        # run workspaces and deterministic caches
```

Revision ancestry is adjacent. `revision` is the normal creator and copies the
current manuscript state into the next fixed-width round without carrying
revision provenance wrappers into the new parent baseline.

## Initial submission

```bash
sci-manuscript init --project /path/to/project
sci-manuscript build --project /path/to/project
```

Metadata-first initialization creates a commented `meta.yaml` and does not
compile or infer author/scientific data. For `initial_submission`, the default
build target is the clean manuscript, published as `output/manuscript.pdf`.

## Revision rounds

```bash
sci-manuscript revision --project /path/to/project --yes
sci-manuscript build --project /path/to/project
```

The second command selects the active round and defaults to `marked` for a
revision. It does not compile clean or response PDFs unless their targets are
requested.

## `\review` provenance

Use `\review{1-1}{current revised text}` only for a change caused by that
reviewer comment. Nested wrappers inherit and union reviewer IDs. The wrapper
defines provenance, not change extent: unchanged current text inside it remains
black.

`\ReviewReference{ID}{key}` is optional reference provenance metadata. It is
valid only when the reviewer caused a reference addition or metadata change;
mentioning an existing reference in a response does not transfer ownership.
AUTHOR versus REVIEWER ownership conflicts fail explicitly.

## Highlighted manuscript semantics

The marked manuscript is the current clean manuscript plus revision
highlighting. The current source is the only layout and structure authority.
`latexdiff` detects current additions; its union output is never compiled as the
marked manuscript. Parent-only deletions never appear.

| Current content | Appearance |
| --- | --- |
| reviewer-driven addition/replacement | RubineRed |
| author-driven addition/replacement | ForestGreen |
| unchanged text | black |
| citation markers and DOI/URL links | xcolor `ProcessBlue` (`dvipsnames`) |

Fine addition spans are preferred. Unchanged display equations stay black, and
highlight spans cannot merge structural blocks. The complete identity,
whole-block, move, equation, and citation rules are maintained in
[revision semantics](references/revision_semantics.md).

Citation identity is the BibTeX key, not its rendered number. Citation markers
and DOI/URL links use xcolor `ProcessBlue`; bibliography prose remains black.
Parent-only content is absent from the marked manuscript. A deletion-only reply
uses a locale-aware note rather than inventing a line number.

## Response workflow

Each revision owns `response/reviewer_comments.md` and
`response/responses.tex`. Authors fill one `\Response{ID}{...}` per detailed
comment and may add causal `\ReviewReference` declarations. The first-page
opening and signing block come only from the package-owned localized template;
`\ResponseLetter{...}` is no longer accepted. Build, submission, and reindex
never rewrite response bodies. The package audits comments, responses, and
manuscript/reference provenance. Formal submission requires a complete audit;
ordinary marked builds do not.

Response letters use Times New Roman for Latin-script text while retaining the
existing CJK font contract. The font is resolved from the host system and is
never bundled. If the exact font is unavailable through fontconfig, the build
fails with `RESPONSE_FONT_UNAVAILABLE_TIMES_NEW_ROMAN` instead of silently
substituting a Times-like family.

Multiple corresponding authors are supported. The response letter lists them
in manuscript author order, filtering the selected author list without sorting
by name, affiliation, or metadata declaration order. Each localized block
contains the author name, correspondence address, and email. The address uses
that author's optional `correspondence_address` value when present; otherwise
it uses only the first affiliation. A corresponding author without an email or
resolvable address fails the build with an author-specific metadata error.

Block labels are `通讯地址：` and `邮箱：` in Chinese, and
`Correspondence address:` and `E-mail:` in English.

Reviewer locations come from a layout-equivalent compilation of the final
marked source and never alter the visible marked PDF. Response builds verify
the opening, correspondence data, responses, locations, and exact Latin font
against the compiled PDF.

## Build commands

```bash
sci-manuscript build --project .
sci-manuscript build --project . --round revision_01
sci-manuscript build --project . --round revision_01 --target clean
sci-manuscript build --project . --round revision_01 --target all
```

The default target is `clean` for the initial submission and `marked` for a
revision. Use `--round` to select an existing historical round without changing
the active round. Missing rounds list available rounds, incomplete rounds list
available targets, and there is no silent fallback.

Use `--timing` to print stage durations and LaTeX, bibliography, cache-hit, and
latexdiff invocation counts. Use `--keep-temp` only when diagnostics are needed.

## Build targets

| Target | Work performed |
| --- | --- |
| `clean` | current source and bibliography -> clean PDF |
| `marked` | parent/current comparison -> marked PDF; no clean compile or locations |
| `response` | reuse a current marked PDF when valid, otherwise rebuild it; derive locations and response |
| `all` | clean + marked + response + complete cross-artifact validation |

`marked` and `response` are unavailable for `initial_submission`; `all` there
is equivalent to its complete clean build.

## Output artifacts

Initial output contains only `manuscript.pdf`. A fully built revision output
contains only:

```text
manuscript_clean.pdf
manuscript_marked.pdf
response_letter.pdf
```

Selective builds may contain a valid subset. Stale PDFs are removed after input
changes, while still-current manifest-verified PDFs are retained. Audits,
manifests, TeX, AUX, logs, timing JSON, caches, and diagnostic PDFs never enter
`output/`. Persistent manifests live under `state/`; run diagnostics and the
bibliography cache live under `tmp/`.

## Validation

Validation covers scientific text, numbering, paragraph/block topology,
reference provenance, response locations, and output purity. Build manifests
classify artifacts as CURRENT, STALE, or MISSING. Historical rounds verify their
frozen source, bibliography, author metadata, and ancestor state before build.
Implementation details and maintenance evidence live in
[workflow](references/workflow.md) and
[technical core](references/technical_core.md).

## Zotero / Better BibTeX

For leaner BibTeX exports, Zotero + Better BibTeX users may add `abstract` to
**Fields to omit from export**. This is optional: the skill accepts `.bib`
files that retain `abstract` and never removes fields from or writes changes
back to the source `.bib`.

## Requirements and dependencies

- Python 3.11+
- PyYAML and ruamel.yaml
- Tectonic (primary tested engine) or the supported `latexmk` toolchain
- latexdiff for revisions
- Poppler tools for PDF text, geometry, and layout checks

Run `sci-manuscript doctor` to inspect the local toolchain.

## Limitations

Highlight extent is best-effort: heavily rewritten single blocks may be colored
as a whole. Move suppression is exact normalized block identity only. There is
no fuzzy move detection, semantic parser, generic LaTeX AST, sentence aligner,
or mathematical AST. Tectonic has the strongest integration evidence; the
traditional LaTeX driver depends on a correctly installed local toolchain.

## Development and testing

```bash
python -m pip install -e ".[dev]"
PYTHONPATH=src pytest
ruff format --check .
ruff check .
mypy src tests
python -m build
```

Package behavior is documented in [SKILL.md](SKILL.md),
[references/workflow.md](references/workflow.md), and
[references/revision_semantics.md](references/revision_semantics.md).
Maintainers performing architecture or release audits should also read
[references/technical_core.md](references/technical_core.md); normal manuscript
work does not require it.

## Rendered examples

![Highlighted revised manuscript](docs/images/marked_manuscript.png)

![Reviewer response letter](docs/images/response_letter.png)

## License

The Python package and project-maintained Chinese class are MIT licensed.
Third-party bibliography-style provenance is recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
