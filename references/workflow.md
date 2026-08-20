# Lifecycle workflow

Read this reference before creating a revision, resolving response
placeholders, synchronizing BibTeX, or preparing a submission package.

## Version model

```text
initial_submission/   r0, parent null
revision_1/           r1, parent r0
revision_2/           r2, parent r1
```

Each version contains its own manuscript sources, author library, generated
metadata, bibliography, revision style, assets, submission workspace, and
outputs. `python run.py revision` is the only normal revision creator. It
copies the current highest version, removes inherited provenance wrappers from
manuscript prose, resets outputs, and creates a response workspace. Gaps,
duplicates, `revision_0`, and non-adjacent parents are rejected.

## Initial submission

```bash
python run.py build
python run.py submission
```

The clean PDF is `initial_submission/output/manuscript.pdf`. Submission sources
are created on demand under `initial_submission/submission/`; their package is
published under `submission/package/` without exposing compiler intermediates.

## Revision response

Reviewer comments use Markdown headings and consecutive numbered comments:

```text
# Reviewer #1

General assessment.

1. First specific comment.
```

Use `\review{1-1}{revised text}` for reviewer-linked manuscript changes and
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

## Bibliography synchronization

Every version owns a `references/references.bib` snapshot. Explicit Better
BibTeX synchronization updates all existing snapshots atomically per file:

```bash
python run.py sync-bib --bib-export /absolute/path/to/export.bib
```

No Zotero process or network service is contacted. Rebuild packages after
synchronizing a changed bibliography.

## Temporary-file contract

Every command uses `project/tmp/run_<timestamp>_<pid>_<id>/`. A successful run
removes its run directory. A failure retains it and reports a project-relative
path. `--keep-temp` retains a successful run only for explicit diagnostics.
