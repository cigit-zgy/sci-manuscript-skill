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

Reviewer comments use Markdown headings and consecutive numbered comments:

```text
# Reviewer #1

General assessment.

1. First specific comment.
```

Use `\review{1-1}{revised text}` only for reviewer-linked manuscript changes.
Write ordinary author additions directly; adjacent `latexdiff` detects them.
Legacy `\user{additional text}` remains readable but should not be added.
Replace every generated `\ResponsePending{1-1}` with the real response.

`\review` is provenance metadata only. It does not make its whole body green.
Before diffing, wrappers are removed and their current-source character ranges
are retained in a sidecar map. Actual additions are classified against that map
after structural comparison. Therefore unchanged reviewer-scoped text remains
unmarked.

```bash
sci-manuscript submission --project /absolute/path/to/project
```

This publishes:

```text
revision_NN/output/manuscript_clean.pdf
revision_NN/output/manuscript_marked.pdf
revision_NN/output/response_letter.pdf
revision_NN/submission/package/
```

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

Display mathematics is compared with `latexdiff --math-markup=WHOLE`. The
formula is treated as a structured object and diff commands are not inserted
into its internal grouping. Inline and display mathematics are excluded from
CJK/ulem text-decoration scanners.

Visible states are mutually exclusive:

- ordinary author addition: blue wave underline in text, blue in mathematics;
- reviewer/editor-linked addition: green straight underline in text, green in
  mathematics;
- deletion: red strikeout in text, red in mathematics;
- unchanged content: normal rendering.

Chinese text decoration remains continuous through CJK punctuation.

## Submission and artifact contract

`submission` builds the clean manuscript and version-local submission material;
for a revision it also builds the adjacent marked comparison and response
letter. The marked comparison is always direct-parent to current.

After clean and marked compilation, the workflow parses both compiler logs and
compares their unique overfull boxes. Any marked-specific overfull box fails the
revision build. A passing run publishes
`revision_NN/output/revision_layout_qa.txt`; shared warnings still require visual
PDF inspection and must not be hidden through global spacing, font-size,
page-geometry, or manual line-break workarounds.

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
