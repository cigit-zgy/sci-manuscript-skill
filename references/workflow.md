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
generated metadata, bibliography, revision style, and all publisher resources.
No version may contain `references/`. The public `revision` command is the only
normal revision creator. It copies manuscript state from the current highest
version, removes inherited provenance wrappers from manuscript prose, resets
outputs, inherits editable submission sources and non-round-specific response
attachments, and creates a fresh response letter for the new reviewer round.
It never copies a prior response letter, a generated submission package, or
shared references. Gaps, duplicates, `revision_0`, and non-adjacent parents are
rejected.

## Initialization

Run `doctor` before initialization when the environment has not already been
verified. Collect a new or empty project path, title, journal, publisher,
language, article type, author order, and any existing author YAML or BibTeX
file. Do not infer missing scientific or identity data.

```bash
sci-manuscript init \
  --project /absolute/path/to/project \
  --title "User-supplied title" \
  --journal "Target Journal" \
  --publisher elsevier \
  --language en \
  --authors /absolute/path/to/authors.yaml \
  --author "First Author" \
  --author "Corresponding Author" \
  --bib /absolute/path/to/references.bib
```

Ask whether the user wants Zotero Better BibTeX Automatic Export. Initialization
always creates the non-invasive `references/zotero_setup.md` guide and the
single shared `references/references.bib` export target. If the user declines
Zotero integration, the bibliography remains available for manual maintenance.
When the user accepts bundled placeholders, omit `--authors` or `--bib` and
identify the copied files that must be replaced. Initialization creates and
builds only `initial_submission`; it must not create a revision or a submission
package.

## Initial submission

```bash
python run.py build
python run.py submission
```

The clean PDF is `initial_submission/output/manuscript.pdf`. Submission sources
are created on demand under `initial_submission/submission/`; their package is
published under `submission/package/` without exposing compiler intermediates.

`build` recompiles only the selected clean manuscript. It must not create the
next revision, submission sources, or scientific content.

## Revision response

Starting a revision creates infrastructure only. It must not change the parent
or current manuscript content. Reviewer comments do not authorize the agent to
draft, infer, or apply manuscript wording. Use the markup commands below only
for an exact patch or concrete edit operation supplied or explicitly confirmed
by the user.

External comments use Markdown headings and consecutive numbered comments:

```text
# Editor

1. Editor comment.

# Associate Editor

1. Associate-editor comment.

# Reviewer #1

General assessment.

1. First paragraph.
   Second paragraph.
```

Stable IDs are `E-N`, `AE-N`, and the backward-compatible reviewer form `N-N`.
Indented or blank-line-separated paragraphs remain distinct, and external
comment text is escaped for LaTeX. User-authored response LaTeX is not escaped
again. Use `\review{1-1}{revised text}` for reviewer-linked manuscript changes and
`\selfadd{additional text}` for author-initiated additions. Replace every
generated `\ResponsePending{1-1}` with the real response.

```bash
python run.py all
```

This publishes:

```text
revision_N/output/manuscript_clean.pdf
revision_N/output/manuscript_marked.pdf
revision_N/output/response_letter.pdf
revision_N/submission/package/
```

Response locations are calculated from continuous line labels in the marked
PDF. Registries, flattened TeX, extracted text, and compiler files remain
temporary.

## Submission and artifact contract

Use `submission` for an initial submission or when only version-local submission
materials are needed. Use `all` for a completed revision because it builds the
clean manuscript, adjacent marked comparison, response letter, and submission
package together. The marked comparison is always direct-parent to current.

Manuscript, clean-manuscript, and marked-manuscript PDFs have continuous line
numbers. Cover letters, response letters, highlights, and graphical abstracts
do not use manuscript line numbering. Editable submission and response sources
are created once and survive later builds.

## Bibliography workflow

Every version reads the single root `references/references.bib`. The recommended
workflow is Zotero Better BibTeX Automatic Export with format `Better BibTeX`,
the export path shown in `references/zotero_setup.md`, and `Keep updated`
enabled. The skill creates only the guide and export target; it does not access
Zotero, modify Zotero settings, or connect to a Zotero API.

Validate the selected manuscript version without changing files:

```bash
python run.py check
```

The command reports citation keys that do not exist in the shared BibTeX file.
It never exports, repairs, or inserts citations. A normal build does not run a
Zotero export or `sync-bib`.

Explicit synchronization remains an atomic manual fallback:

```bash
python run.py sync-bib --bib-export /absolute/path/to/export.bib
```

No Zotero process or network service is contacted. Rebuild packages after
synchronizing a changed bibliography.

## Temporary-file contract

Every command uses `project/tmp/run_<timestamp>_<pid>_<id>/`. A successful run
removes its run directory. A failure retains it and reports a project-relative
path. `--keep-temp` retains a successful run only for explicit diagnostics.
