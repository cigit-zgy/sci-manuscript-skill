# Lifecycle workflow

Read this reference before creating a revision, resolving response
placeholders, synchronizing BibTeX, or preparing a submission package. The
marked-manuscript algorithm is defined normatively in
[revision_semantics.md](revision_semantics.md); consuming manuscript projects
must not add local diff semantics.

## Version model

```text
initial_submission/   r00, parent null
revision_01/          r01, parent r00
revision_02/          r02, parent r01
```

The project root contains the only `references/` tree: author library,
bibliography, and revision style. Built-in publisher resources come from the
installed package. No version may contain `references/`. `sci-manuscript
revision` is the only normal revision creator. It copies manuscript state from
the current highest version, removes inherited provenance wrappers from
manuscript prose, resets outputs, and creates a response workspace. It never
copies or regenerates shared references. Gaps, duplicates, `revision_0`, and
non-adjacent parents are rejected.

## Initialization

Run `doctor` before initialization when the environment has not already been
verified. For Chinese targets, run `sci-manuscript doctor --language zh` so the
real CJK compile-and-glyph probe is included. Collect an existing parent project
path, title, journal, publisher, language, article type, author order, and any
existing author YAML or BibTeX file. Do not infer missing scientific or identity
data.

The author-library priority is strict: explicit `init --authors PATH`, then the
configured user library, then the bundled role-free public team library in
`resources/authors.yaml`. Configure a reusable library once with:

```bash
sci-manuscript authors configure /absolute/path/to/authors.yaml
sci-manuscript authors list
sci-manuscript authors show author_id
```

The configured location follows the operating-system user configuration
directory (macOS: `~/Library/Application Support/sci-manuscript/authors.yaml`).
In an interactive terminal, `init` lists every configured ID with English and
Chinese names and asks separately for first, corresponding, and other IDs.
Multiple IDs and first/corresponding overlap are valid. These roles are written
only to the paper's `meta.yaml`; the global profile library stays role-free.

```bash
sci-manuscript init \
  --project /absolute/path/to/project \
  --title "User-supplied title" \
  --journal "Target Journal" \
  --publisher elsevier \
  --language en \
  --article-type "Research Article" \
  --authors /absolute/path/to/authors.yaml \
  --first-author first_author \
  --corresponding-author corresponding_author \
  --bib /absolute/path/to/references.bib
```

Omitting `--authors` uses a configured user library or the bundled fallback.
Neither source assigns manuscript roles: interactive initialization asks for
them, and non-interactive initialization still requires explicit
`--first-author` and `--corresponding-author`. Omitting `--bib` uses the package
bibliography placeholder and must be reported as requiring replacement.
Initialization creates and builds only `initial_submission`; it must not create
a revision or a submission package.

## Initial submission

```bash
sci-manuscript build --project /absolute/path/to/project
sci-manuscript submission --project /absolute/path/to/project
```

The clean PDF is `initial_submission/output/manuscript.pdf`. Submission sources
are created on demand under `initial_submission/submission/`; their package is
published under `submission/package/` without exposing compiler intermediates.

`build` recompiles only the selected clean manuscript. It must not create the
next revision, submission sources, or scientific content.

## Revision response

Running

```bash
sci-manuscript revision --project /absolute/path/to/project --yes
```

automatically creates `revision_NN/response/reviewer_comments.md` from the
project language. The Chinese template contains `编辑`, `审稿人 #1`, and
`审稿人 #2`; the English template contains the corresponding `Editor` and
`Reviewer` headings. Each specific comment is entered as one numbered list
item. Empty template items are ignored and users may add or remove list items or
reviewer sections.

Example:

```text
# Editor

1. Please clarify the scope.

# Reviewer #1

General assessment from Reviewer 1.

1. First specific comment.
2. Second specific comment.
```

The parser derives `E-1`, `1-1`, `1-2`, and subsequent IDs from section identity
and non-empty list order. A paragraph placed between a reviewer heading and the
first numbered item is treated as that reviewer's general assessment. Legacy
files using explicit `## 1-1 | ...` headings remain readable for migration, but
new revision templates use only the numbered-list form.

Use `\review{1-1}{revised text}` only for reviewer-linked manuscript changes.
Write ordinary author additions directly; adjacent `latexdiff` detects them.
Legacy `\user{additional text}` remains readable but should not be added.

`\review` is provenance metadata only. It does not make its whole body red.
Before diffing, wrappers are removed and their current-source character ranges
are retained in a sidecar map. Actual additions are classified against that map
after structural comparison. Therefore unchanged reviewer-scoped text remains
unmarked.

`response/responses.tex` stores editable response prose. When a revision is
created from an already populated review file, one pending response entry is
created for each parsed comment. When the generated review template is still
empty, the response source is initially empty. Review completeness is therefore
derived at build time rather than encoded in `reviewer_comments.md`.

### Review audit

Every revision `build` and `submission` performs a three-way audit of:

```text
reviewer_comments.md <-> responses.tex <-> manuscript \review{...}
```

The audit computes these states:

- `manuscript_revised`: completed response plus matching manuscript provenance;
- `response_only`: completed response without manuscript provenance;
- `manuscript_changed_but_unanswered`: manuscript provenance exists but the
  response is missing or pending;
- `unanswered`: the comment has neither a completed response nor manuscript
  provenance.

It also reports empty or invalid comment files, orphan response IDs, orphan
`\review` IDs, and review-ID drift after list reordering. These are
non-blocking review-completeness warnings: clean and marked rendering continues.
Each warning prints the concrete path or paths that require attention.

The first audit of populated comments records comment fingerprints in
`state/revision_NN/review_index.yaml`. Later reordering that would remap the
same comment text to a different ID is reported as `REVIEW_ID_DRIFT` instead of
silently changing the established association.

```bash
sci-manuscript build --project /absolute/path/to/project --round r01
sci-manuscript submission --project /absolute/path/to/project --round r01
```

A revision build publishes clean and marked manuscript PDFs. Submission also
publishes the available correspondence and package artifacts. If comments are
present while some responses remain unfinished, the response PDF may contain
visible pending placeholders and the audit remains `INCOMPLETE`. If the comment
template is still empty, the manuscript PDFs can still be built and the audit
points directly to `reviewer_comments.md`.

Response locations are calculated in an independent transparent line-label
compilation. Registries, flattened TeX, extracted text, and compiler files
remain temporary.

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

`submission` builds the clean manuscript and version-local submission material;
for a revision it also builds the adjacent marked comparison. A response letter
is assembled when parsed review comments are available. Review-completeness
warnings do not suppress manuscript rendering or the rest of the package.

The copied `submission/package/checklist.md` receives one generated line:

```text
Review completeness: COMPLETE
```

or

```text
Review completeness: INCOMPLETE
```

The terminal audit remains the detailed source of unresolved IDs and concrete
paths.

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
