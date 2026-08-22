# Lifecycle workflow

Read this reference before creating a revision, resolving response
placeholders, synchronizing BibTeX, or preparing a submission package.

## Version model

```text
initial_submission/   r00, parent null
revision_01/          r01, parent r00
revision_02/          r02, parent r01
```

The project root contains the only `references/` tree: author library,
bibliography, and revision style. Built-in publisher resources
come from the installed package.
No version may contain `references/`. `sci-manuscript revision` is the only
normal revision creator. It copies manuscript state from the current highest
version, removes inherited provenance wrappers from manuscript prose, resets
outputs, and creates a response workspace. It never copies or regenerates
shared references. Gaps, duplicates, `revision_0`, and non-adjacent parents are
rejected.

## Initialization

Run `doctor` before initialization when the environment has not already been
verified. For Chinese targets, run `sci-manuscript doctor --language zh` so the
real CJK compile-and-glyph probe is included. Collect an existing parent project
path, title, journal, publisher, language, article type, author order, and any
existing author YAML or BibTeX file. Do not infer missing scientific or identity
data.

The author-library priority is strict: explicit `init --authors PATH`, then the
configured user library, then no usable author data. The package
`resources/authors.yaml` is schema-only example data and is never selected.
Configure a reusable library once with:

```bash
sci-manuscript authors configure /absolute/path/to/authors.yaml
sci-manuscript authors list
sci-manuscript authors show author_id
```

The configured location follows the operating-system user configuration
directory (macOS:
`~/Library/Application Support/sci-manuscript/authors.yaml`). In an interactive
terminal, `init` lists every configured ID with English and Chinese names and
asks separately for first, corresponding, and other IDs. Multiple IDs and
first/corresponding overlap are valid. These roles are written only to the
paper's `meta.yaml`; the global profile library stays role-free.

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

Omitting `--authors` uses only a configured user library; if none exists,
interactive and non-interactive initialization both fail with a configure
instruction. Omitting `--bib` uses the package bibliography placeholder and must
be reported as requiring replacement. Initialization creates and builds only
`initial_submission`; it must not create a revision or a submission package.

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

Use `\review{1-1}{revised text}` for reviewer-linked manuscript changes and
`\user{additional text}` for user-initiated additions. Replace every
generated `\ResponsePending{1-1}` with the real response.

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

Response locations are calculated from continuous line labels in the marked
PDF. Registries, flattened TeX, extracted text, and compiler files remain
temporary.

## Submission and artifact contract

`submission` builds the clean manuscript and version-local submission material;
for a revision it also builds the adjacent marked comparison and response
letter. The marked comparison is always direct-parent to current.

Marked-manuscript PDFs have continuous line numbers. Cover letters, response
letters, highlights, and graphical abstracts do not use manuscript line
numbering. Editable submission and response sources are created once and
survive later builds.

## Bibliography synchronization

Every version reads the single root `references/references.bib`. Explicit
Better BibTeX synchronization atomically replaces that shared file:

```bash
sci-manuscript sync-bib --project /absolute/path/to/project \
  --bib /absolute/path/to/export.bib
```

No Zotero process or network service is contacted. Rebuild packages after
synchronizing a changed bibliography.

## Temporary-file contract

Every command lazily uses `project/manuscript/tmp/run_<timestamp>_<pid>_<id>/`.
A successful run removes its run directory and the empty `tmp/`. A failure
retains it and reports a project-relative
path. `--keep-temp` retains a successful run only for explicit diagnostics.
