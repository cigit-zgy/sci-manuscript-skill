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

`doctor` reports missing LaTeX, `latexdiff`, PDF, and font dependencies for the
selected publisher and build target.

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

The CLI resolves a project, selects an existing round, selects the requested
artifact target, stages package resources in a temporary run directory, builds
the minimum dependency set, validates the result, and atomically publishes only
the requested current artifacts.

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

Fine addition spans are preferred. At 60% or greater visible addition coverage,
one current paragraph, heading, or caption may be highlighted as a whole only
when all additions have identical provenance. Structural seams are immutable,
so highlight spans cannot merge paragraphs or cross headings, displays, floats,
tables, or lists. Changed display equations may be highlighted atomically.

## Reference link styling

Citation identity is the BibTeX key, not its rendered number. Current citation
markers and reference-related DOI/URL links retain the manuscript's normal link
styling, which is xcolor `ProcessBlue` from `dvipsnames`. Bibliography prose
remains black. Provenance is retained for audit and reviewer-location purposes;
removed references are absent because only the current bibliography renders.

## Deleted content policy

Deleted prose, equations, headings, citations, bibliography entries, labels,
and other parent-only structures are not shown. A deletion-only reviewer reply
uses a locale-aware note stating that no corresponding highlighted text remains
instead of inventing a line number.

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

After compilation, the response build uses Poppler text extraction to verify
the localized opening and correspondence fields, ordered comment IDs, visible
response-body projections, and resolved locations against the real PDF.

Multiple corresponding authors are supported. The response letter lists them
in manuscript author order, filtering the selected author list without sorting
by name, affiliation, or metadata declaration order. Each localized block
contains the author name, correspondence address, and email. The address uses
that author's optional `correspondence_address` value when present; otherwise
it uses only the first affiliation. A corresponding author without an email or
resolvable address fails the build with an author-specific metadata error.

Block labels are `通讯地址：` and `邮箱：` in Chinese, and
`Correspondence address:` and `E-mail:` in English. Name-to-address and
address-to-email gaps are each `0.25\baselineskip`; adjacent author blocks are
separated by `0.55\baselineskip`, with no trailing block gap.

Reviewer locations come from a layout-equivalent compilation of the final
marked source. They never alter the visible marked PDF.

## Build commands

Initial submission:

```bash
sci-manuscript build --project .
```

Active revision, default marked-only fast path:

```bash
sci-manuscript build --project .
```

Historical revision:

```bash
sci-manuscript build --project . --round revision_01
```

Explicit target and full verification:

```bash
sci-manuscript build --project . --round revision_01 --target clean
sci-manuscript build --project . --round revision_01 --target all
```

Use `--timing` to print stage durations and LaTeX, bibliography, cache-hit, and
latexdiff invocation counts. Use `--keep-temp` only when diagnostics are needed.

## Round selection

`--round` selects an existing round without changing the active round. Omission
selects the active round. Missing rounds list all available rounds; an existing
but incomplete round reports why the requested target is not buildable and
lists available targets. There is no silent fallback.

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

Full revision validation requires scientific-text, numbering, paragraph, block
topology, reference provenance, location-layout, and output-purity identity.
Marked-only builds run source-level current-content and topology checks but skip
cross-PDF validation because no clean PDF is compiled.

Build manifests use content digests to identify CURRENT, STALE, and MISSING
artifacts. Artifact fingerprints include the installed production Python
implementation plus the selected engine and renderer-tool identities. When a
round becomes historical, `state/<round>/round_state.yaml` freezes its source,
metadata, effective author metadata, bibliography snapshot, and parent identity;
historical builds verify that record before compilation without rewriting it.

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
