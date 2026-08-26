# Lifecycle workflow

Read this reference before creating a revision, resolving responses,
synchronizing BibTeX, or preparing a submission package. The
marked-manuscript algorithm is defined normatively in
[revision_semantics.md](revision_semantics.md); consuming manuscript projects
must not add local diff semantics.

## Version model

```text
initial_submission/   r00, parent null
revision_01/          r01, parent r00
revision_02/          r02, parent r01
```

The project root contains the only user-editable `references/` tree:
bibliography and revision style. Built-in publisher resources come from the
installed package. No version may contain `references/`. Historical
bibliography state is machine-owned under `state/<round>/bibliography.bib` and
is not a second editable bibliography system. `sci-manuscript
revision` is the only normal revision creator. It copies manuscript state from
the current highest version, removes inherited provenance wrappers from
manuscript prose, freezes the parent bibliography, resets outputs, and creates a
response workspace. It never copies references into a manuscript round. Gaps,
duplicates, `revision_0`, and non-adjacent parents are rejected.

## Initialization

Run `doctor` before the first build when the environment has not already been
verified. Metadata-first initialization requires only the parent project path:

```bash
sci-manuscript init --project /absolute/path/to/project
```

It creates a commented `initial_submission/meta.yaml`, prints `Please edit
meta.yaml before build.`, and does not compile or infer scientific/identity
data. After the user supplies journal, publisher, language, article type,
funding, author order, and corresponding roles, the first build materializes
publisher-appropriate manuscript sources. The user then maintains title,
abstract, and keyword text in `sections/00_frontmatter.tex`.
Explicit command-line fields remain available for automated initialization.

The author-library priority is the configured user library, then the bundled
role-free Skill library in `resources/authors.yaml`. No author library is
copied into the project. Configure a reusable user library once with:

```bash
sci-manuscript authors configure /absolute/path/to/authors.yaml
sci-manuscript authors list
sci-manuscript authors show author_id
```

The configured location follows the operating-system user configuration
directory (macOS: `~/Library/Application Support/sci-manuscript/authors.yaml`).
The parameter-rich interactive init lists every configured ID with English and
Chinese names and asks separately for first, corresponding, and other IDs.
Multiple IDs and first/corresponding overlap are valid. The new metadata schema
stores the list-valued `authors.first`, `authors.corresponding`, and
`authors.other` roles; it never duplicates names, email, affiliations, or
bilingual biographies. Every author library stays role-free.

Response correspondence is list-based. The renderer traverses the manuscript
author list and retains records whose IDs appear in `authors.corresponding`, so
the response order is manuscript order rather than correspondence-list, name,
or affiliation order. Each author-library record may provide the optional
scalar `correspondence_address`. If it is absent, the response uses only that
author's first affiliation, localized for the response language; it never
concatenates multiple affiliations or infers an address from an affiliation ID.
Every corresponding author must have a non-empty email and a resolvable
address. Missing values fail with the author name, source, and missing field
where applicable.

```bash
sci-manuscript init \
  --project /absolute/path/to/project \
  --title "User-supplied title" \
  --journal "Target Journal" \
  --publisher elsevier \
  --language en \
  --article-type "Research Article" \
  --first-author author_one \
  --corresponding-author author_two \
  --bib /absolute/path/to/references.bib
```

The configured user library or bundled default never assigns manuscript roles:
interactive initialization asks for
them, and non-interactive initialization still requires explicit
`--first-author` and `--corresponding-author`. Omitting `--bib` uses the package
bibliography placeholder and must be reported as requiring replacement.
Metadata-first initialization creates only editable configuration and workspace
directories. It must not compile, create a revision, or create submission files.
During build, bilingual manuscript fields and author-library biographies are
rendered to `tmp/<run>/publisher_metadata.tex`; successful runs remove that run
directory, and no generated metadata TeX enters `initial_submission/`.
Deterministic bibliography cache entries may remain under `tmp/cache/`.

Journal templates, publisher classes/styles, and the shared manuscript
preamble are installed package resources. A build resolves them after reading
the user project, stages them under `manuscript/tmp/<run>/`, compiles there, and
publishes final PDFs. User rounds therefore do not contain `preamble/`,
`manuscript_preamble/`, `journal_templates/`, publisher `.cls`/`.bst`,
`workflow.tex`, or `sections.yaml`. The one intentional style copy is
`references/revision_style.tex`, initialized from the packaged
`revision_style.template.tex` for optional font/background hooks. Semantic
colors are package-owned and frozen: reviewer RubineRed, author ForestGreen,
and citation/DOI/URL pure RGB blue (`#0000FF`).

For a custom publisher, initialize with `publisher: custom` and
`--custom-template /absolute/path/to/template`. Its `sections.yaml` declares
supported languages. The resource is validated for path traversal and copied
once to `references/journal_template/`; runtime staging resolves nested assets
from that sole project-owned copy.

## Initial submission

```bash
sci-manuscript build --project /absolute/path/to/project
sci-manuscript submission --project /absolute/path/to/project
```

The clean PDF is `initial_submission/output/manuscript.pdf`. Submission sources
are created on demand under `initial_submission/submission/`; final submission
files are published directly in that flat directory without exposing compiler
intermediates. `cover_letter_body.tex`, `highlights.tex`,
the graphical-abstract directory, and `checklist.md` are user-editable;
generated PDFs share the same submission directory.

`build` recompiles only the selected clean manuscript. It must not create the
next revision, submission sources, or scientific content.

## Revision response

Running

```bash
sci-manuscript revision --project /absolute/path/to/project --yes
```

automatically creates `revision_NN/response/reviewer_comments.md` from the
project language. The Chinese template contains `副编辑`, `编辑`, `审稿人 #1`,
and `审稿人 #2`; the English template contains the corresponding `Associate
Editor`, `Editor`, and `Reviewer` headings. Each specific comment is entered as one numbered list
item under `Specific comments` or `具体意见`; the unnumbered `Main comment` or
`主意见` records the overall assessment. Empty template items and empty main
comments are ignored, and users may add or remove list items or reviewer sections.

Example:

```text
# Editor

## Main comment

## Specific comments

1. Please clarify the scope.

# Reviewer #1

## Main comment

General assessment from Reviewer 1.

## Specific comments

1. First specific comment.
2. Second specific comment.
```

The parser derives `AE-1`, `E-1`, `1-1`, `1-2`, and subsequent IDs from section identity
and non-empty list order. Summary text must appear under `Main comment` or
`主意见`; numbered details must appear under `Specific comments` or `具体意见`.
The summary receives no response ID and is excluded from per-comment audit.

Use `\review{1-1}{revised text}` only for reviewer-linked manuscript changes.
Write ordinary author additions directly; adjacent `latexdiff` detects them.

`\review` is provenance metadata only. It does not make its whole body red.
Before diffing, wrappers are removed and their current-source character ranges
are retained in a sidecar map. Actual additions are classified against that map
after structural comparison. Therefore unchanged reviewer-scoped text remains
unmarked.

`response/responses.tex` stores one `\Response{ID}{...}` for each actual detailed
comment and optional `\ReviewReference{ID}{key[,keys...]}` declarations. It does
not own first-page prose. The localized response opening, ordered corresponding-
author blocks, localized labels, and single page break are generated only by the
package-owned fixed template and Python metadata fragment. Historical
`\ResponseLetter{...}` input is rejected with a migration diagnostic rather than
silently rendered or ignored.
Comment-only reading aids are derived from authoritative `reviewer_comments.md`;
summaries receive no response ID. Build, submission, and reindex never overwrite
response or reference bodies. Users never enter line-number fields.

The response traverses manuscript authors in order and renders every selected
corresponding author. Each block uses the author's explicit
`correspondence_address` or that author's first localized affiliation as the
fallback; multiple affiliations are never concatenated. Editor and reviewer
section titles are rendered verbatim (no generated `Response to` prefix and no
forced break between sections). General comments use a neutral light-gray panel
distinct from specific-comment panels. Component-local spacing is fixed by the
response template; global paragraph spacing must not stack with it.
All response-letter Latin-script text uses the exact system-installed Times New
Roman family through `fontspec`; Chinese text continues to use the existing CJK
font contract. The package does not bundle or substitute fonts. If fontconfig
cannot resolve the exact family, response compilation stops with
`RESPONSE_FONT_UNAVAILABLE_TIMES_NEW_ROMAN`.

### Review audit

Every revision `build` and `submission` performs a three-way audit of:

```text
reviewer_comments.md <-> responses.tex <-> manuscript/reference provenance
```

The audit computes these states:

- `manuscript_revised`: completed response plus matching manuscript provenance;
- `response_only`: completed response without manuscript provenance;
- `manuscript_changed_but_unanswered`: manuscript provenance exists but the
  response is missing or empty;
- `unanswered`: the comment has neither a completed response nor manuscript
  provenance.

It separately reports missing, empty, and orphan response entries, as well as
empty or invalid comment files, orphan `\review` IDs, and review-ID drift after
list reordering. These are non-blocking review-completeness issues for
manuscript targets.
Missing, empty, and orphan responses are printed concisely by ID. Only malformed
comment or response source prints its absolute path.

The first audit of populated comments records comment fingerprints in
`state/revision_NN/review_index.yaml`. Later reordering that would remap the
same comment text to a different ID is reported as `REVIEW_ID_DRIFT` instead of
silently changing the established association.

```bash
sci-manuscript build --project /absolute/path/to/project --round r01
sci-manuscript submission --project /absolute/path/to/project --round r01
```

A revision build defaults to the marked-only target. Use `--target clean` for
the clean PDF, `--target response` for marked-layout locations and the response
letter, or `--target all` for all three PDFs and full cross-artifact validation.
`response` reuses a manifest-verified current marked PDF; otherwise it rebuilds
that dependency. Missing and empty response entries remain audit issues. Formal
submission requires `COMPLETE` and stops before assembling submission artifacts
otherwise. A malformed response source makes `response` and `all` explicitly
not buildable, while `clean` and `marked` remain available.

Response locations are resolved from package-generated, TeX-native `lineno`
start/end labels in the final marked source. Python reads only the package-owned
`sci:loc:` AUX namespace; it never infers line numbers from PDF glyphs or
geometry. Actual reviewer-red current additions and eligible reviewer-owned
blue citation/reference-link spans feed one normalized range set.
`\ReviewReference{ID}{key[,keys...]}` supplies reference provenance and
location ownership only. Duplicate, overlapping, and adjacent ranges are
merged; a response-only or deletion-only comment receives the locale-aware
no-current-highlight note and never an invented nearby line.

Every user-visible section input participates in the same staged manuscript
comparison, including title, abstract, and keywords supplied through
`sections/00_frontmatter.tex`. Publisher-visible generated metadata, including
funding, is compared in the same flattened runtime stream. This staging does not
rewrite the user-owned composition root or any section source.

Parent and current bibliography sources are staged separately and materialized
by the real publisher style into `.bbl` for key-based machine comparison.
Bibliography changes are rendered using the current revision only: the marked
PDF contains exactly the current entries, order, numbering, and DOI output.
Bibliography prose remains black; citation markers and DOI/URL links retain the
same pure-blue style as clean. New and corrected current entry prose remains black.
Reviewer attribution may be declared with `\ReviewReference` and is reflected
through provenance validation and response locations, never entry color.
For a newly added key, current citation provenance is primary. A matching
`\ReviewReference` may confirm or union reviewer IDs; AUTHOR citation ownership
and REVIEWER reference ownership is a blocking `REFERENCE_PROVENANCE_CONFLICT`.
Declare `\ReviewReference` only when that reviewer comment actually caused the
reference addition or metadata correction. Merely mentioning a reference in a
response never changes its ownership.

## Revision comparison contract

The direct-parent marked comparison has five stages:

1. remove current `\review` wrappers while retaining ownership intervals;
2. use `latexdiff` only to detect current additions;
3. split spans at immutable current block seams, discard whitespace-only spans,
   and apply the fixed 60% same-provenance rule within one block only;
4. intersect additions with reviewer provenance;
5. render from the current manuscript layout.

Raw `latexdiff` output is never compiled as the final marked document. Parent
content and structural commands never enter marked source or PDF. Pure moves may be suppressed
only by exact normalized block identity; fuzzy paragraph, sentence, token, and
grapheme alignment are outside the contract.

Mathematics is treated as a scientific block without a Math AST. A substantively
changed display may be highlighted as one current block. The current formula is
the only active numbered display; parent labels, tags, and cross-reference
commands never enter marked output.

Visible states are mutually exclusive:

- ordinary author addition: ForestGreen text in prose and mathematics;
- reviewer/editor-linked addition: RubineRed text in prose and mathematics;
- unchanged content: normal rendering;
- every citation marker and DOI/URL link: pure RGB blue (`#0000FF`), independent of ownership;
- bibliography prose: black.

Parent-only deletions are absent. Stripping color/provenance markup from marked
must reproduce the exact current source projection; PDF text and AUX numbering
must also match clean. Paragraph and block-topology fingerprints must match as
independent hard invariants.

## Submission and artifact contract

`submission` first verifies review completeness. For a revision, any incomplete
or malformed audit blocks formal artifact assembly; authors use `build` to
continue inspecting clean and adjacent marked manuscript PDFs. A complete audit
allows the response letter and version-local submission material to be built.

For a revision that passes the audit, the staged `submission/checklist.md`
receives the generated line:

```text
Review completeness: COMPLETE
```

Incomplete revisions do not reach formal submission staging. The terminal audit
is the source of unresolved IDs and concrete malformed-source paths.

During `--target all`, the workflow parses clean and marked compiler logs and
compares their unique overfull boxes. Any marked-specific overfull box fails the
full build. A passing run keeps the report only in the current `tmp/<run>/`
when diagnostics are explicitly retained. A failure preserves that run and
reports its absolute path. Shared warnings still require visual PDF inspection
and must not be hidden through global spacing, font-size, page-geometry, or
manual line-break workarounds.

Marked-manuscript PDFs have continuous line numbers. Cover letters, response
letters, highlights, and graphical abstracts do not use manuscript line
numbering. Editable submission and response sources are created once and survive
later builds.

The package-owned cover-letter document consumes the user-owned
`submission/cover_letter_body.tex`. Cover `\guidance{...}` blocks, unresolved
template tokens, and pending markers in enabled highlights or graphical
abstract sources must be resolved before formal submission. A user-supplied
final graphical-abstract PDF is a source artifact; generated-artifact ownership
is hash-verified so overwriting the same path transfers ownership back to the
user.

Reindex and rollback protect all user-owned submission source. They remove only
known generated PDFs and hash-matching paths recorded in
`state/<round>/generated_artifacts.yaml`; cover body, highlights source,
checklist source, graphical source/assets, and user-supplied PDFs are preserved.
Publication is staged and installed atomically, so a failed operation restores
the previous complete set rather than leaving mixed old/new final artifacts.
Reindex moves each machine-owned bibliography snapshot with its corresponding
round. Rollback archives the removed round together with its current
bibliography and atomically restores the previous round's frozen bibliography
as the editable shared latest state.

Each successful latest-round build or submission with a compiled manuscript
freezes the AUX-resolved
cited entries, recursive `crossref`/`xdata` dependencies, and required BibTeX
declarations in `state/<round>/bibliography.bib`. Uncited export entries are not
copied into round state. Each successful build or
submission atomically updates
`state/<round>/build_manifest.yaml`. The manifest records the round and parent,
package/Python/engine/tool identities, effective author source, fonts,
publisher-resource hashes, scientific input hashes, and final output hashes.
It contains no private absolute project or temporary path, is not a scientific
source, and never enters the submission directory.

## Bibliography synchronization

The latest version reads the single editable root
`references/references.bib`. When a new revision is created, the parent value is
atomically frozen under `state/<parent>/bibliography.bib`; historical builds
read that snapshot and fail explicitly if it is missing rather than silently
substituting the latest export. Explicit Better BibTeX synchronization
atomically replaces only the shared latest file:

```bash
sci-manuscript sync-bib --project /absolute/path/to/project \
  --bib /absolute/path/to/export.bib
```

No Zotero process or network service is contacted, and no historical snapshot
is changed. An intentional migration of an existing snapshot requires the
confirmed command `sci-manuscript rebuild-bib-state --project PROJECT --round
ROUND --yes`; it rebuilds from that round's own frozen data and citations rather
than substituting the latest export. Rebuild after synchronizing a changed bibliography. The visible
reference list is compared from parent/current generated `.bbl` output rather
than raw BibTeX fields.

Zotero + Better BibTeX users may optionally add `abstract` to **Fields to omit
from export** to reduce unrelated fields and `.bib` size. This is only an
export recommendation: retained `abstract` fields are accepted, never cause a
build failure, and are not removed from or written back to the user's `.bib`.

## Temporary-file contract

Every command lazily uses `project/manuscript/tmp/run_<timestamp>_<pid>_<id>/`.
A successful run removes its run directory unless `--keep-temp` was requested;
a failure retains it and reports a project-relative path. Deterministic
bibliography cache entries may remain under `tmp/cache/bibliography/`; their
content key includes the flattened source, relevant TeX/BibTeX resources,
engine, and executable identity. No cache or run artifact enters `output/`.

## v1 workspace detection

Version 2.0 does not silently migrate ambiguous v1 state. Detection of legacy
`authors.first_author`/`corresponding_author`/`other_author`, editable
`response_letter.tex`, nested `submission/package/`, or
`revision_creation.yaml` stops with an explicit message: archive the workspace,
read this migration note and the 2.0 changelog, then deliberately convert to the
single 2.0 contract. There are no dual-schema aliases or migration-on-read
adapters.
