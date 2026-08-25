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

The project root contains the only `references/` tree: bibliography and
revision style. Built-in publisher resources come from the
installed package. No version may contain `references/`. `sci-manuscript
revision` is the only normal revision creator. It copies manuscript state from
the current highest version, removes inherited provenance wrappers from
manuscript prose, resets outputs, and creates a response workspace. It never
copies or regenerates shared references. Gaps, duplicates, `revision_0`, and
non-adjacent parents are rejected.

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
rendered to `tmp/<run>/publisher_metadata.tex`; successful runs remove tmp and
no generated metadata TeX enters `initial_submission/`.

Journal templates, publisher classes/styles, and the shared manuscript
preamble are installed package resources. A build resolves them after reading
the user project, stages them under `manuscript/tmp/<run>/`, compiles there, and
publishes final PDFs. User rounds therefore do not contain `preamble/`,
`manuscript_preamble/`, `journal_templates/`, publisher `.cls`/`.bst`,
`workflow.tex`, or `sections.yaml`. The one intentional style copy is
`references/revision_style.tex`, initialized from the packaged
`revision_style.template.tex` so users can configure revision colors and the
deletion strikeout.

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

`response/responses.tex` stores editable response prose. The Skill generates one
empty `\Response{ID}{...}` entry for each actual detailed comment, including
editor comments, and no entry for summaries. When revision creation receives a
populated `--reviews` file, generation is immediate; otherwise the first build
after comments are entered creates the file. Users fill only response bodies and
never enter line-number fields. Review completeness is derived at build time.

### Review audit

Every revision `build` and `submission` performs a three-way audit of:

```text
reviewer_comments.md <-> responses.tex <-> manuscript \review{...}
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
list reordering. These are
non-blocking review-completeness issues: clean and marked rendering continues.
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

A revision build publishes clean and marked manuscript PDFs and rebuilds the
response letter from the current syntactically valid `responses.tex`, even when
the audit is `INCOMPLETE`. Missing and empty entries remain audit issues, while
filled response bodies and automatically derived locations are never served
from an older output. Formal submission requires `COMPLETE` and stops before
assembling submission artifacts otherwise. A malformed response source produces
`RESPONSES_INVALID` with its absolute path: clean and marked manuscripts still
build, while no untrusted response or submission PDF is generated. If the
comment template is still empty, manuscript build remains available and the
audit remains `INCOMPLETE`.

Response locations are calculated in an independent transparent line-label
compilation from `\review{ID}{...}`. Duplicate, overlapping, and adjacent ranges
are normalized; multiple remaining ranges are ordered and localized. A
response-only comment has no location sentence. Registries, flattened TeX,
extracted text, and compiler files remain temporary.

Every user-visible section input participates in the same staged manuscript
comparison, including title, abstract, and keywords supplied through
`sections/00_frontmatter.tex`. Publisher-visible generated metadata, including
funding, is compared in the same flattened runtime stream. This staging does not
rewrite the user-owned composition root or any section source.

## Revision comparison contract

The direct-parent marked comparison has four stages:

1. provenance extraction from current source;
2. provenance-free structural diff;
3. conservative replacement refinement;
4. semantic rendering.

Character refinement is allowed only for TeX-structure-free prose when
`max(len(old), len(new)) <= 2000` and `SequenceMatcher(...,
autojunk=False).ratio() >= 0.70`. Dissimilar, long, or TeX-bearing replacements
stay atomic. These are release-level policy values, not per-project settings.

Display mathematics is compared with `latexdiff --math-markup=FINE`. Math-aware
diff commands mark only changed fragments. Inline and display additions use
semantic color; deletion alone uses a strike overlay. Mathematics remains
excluded from CJK/ulem text-decoration scanners.

Visible states are mutually exclusive:

- ordinary author addition: blue text in prose and mathematics;
- reviewer/editor-linked addition: red text in prose and mathematics;
- deletion: light-gray strikeout in text and mathematics;
- unchanged content: normal rendering.

Chinese deletion strikeout remains continuous through CJK punctuation.

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

After clean and marked compilation, the workflow parses both compiler logs and
compares their unique overfull boxes. Any marked-specific overfull box fails the
revision build. A passing run keeps the report only in the current `tmp/<run>/`
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

Each successful build or submission atomically updates
`state/<round>/build_manifest.yaml`. The manifest records the round and parent,
package/Python/engine/tool identities, effective author source, fonts,
publisher-resource hashes, scientific input hashes, and final output hashes.
It contains no private absolute project or temporary path, is not a scientific
source, and never enters the submission directory.

## Bibliography synchronization

Every version reads the single root `references/references.bib`. Explicit Better
BibTeX synchronization atomically replaces that shared file:

```bash
sci-manuscript sync-bib --project /absolute/path/to/project \
  --bib /absolute/path/to/export.bib
```

No Zotero process or network service is contacted. Rebuild packages after
synchronizing a changed bibliography.

## Temporary-file contract

Every command lazily uses `project/manuscript/tmp/run_<timestamp>_<pid>_<id>/`.
A successful run removes its run directory and the empty `tmp/`. A failure
retains it and reports a project-relative path. `--keep-temp` retains a
successful run only for explicit diagnostics.

## v1 workspace detection

Version 2.0 does not silently migrate ambiguous v1 state. Detection of legacy
`authors.first_author`/`corresponding_author`/`other_author`, editable
`response_letter.tex`, nested `submission/package/`, or
`revision_creation.yaml` stops with an explicit message: archive the workspace,
read this migration note and the 2.0 changelog, then deliberately convert to the
single 2.0 contract. There are no dual-schema aliases or migration-on-read
adapters.
