# Zotero Better BibTeX setup

This project uses one shared bibliography for every manuscript version:

```text
%%EXPORT_PATH%%
```

## Recommended automatic export

1. Install the Zotero Better BibTeX extension.
2. In Zotero, select the collection used by this manuscript.
3. Choose **File -> Export Library** or **Export Collection**.
4. Select **Better BibTeX** as the export format.
5. Enable **Keep updated** to create an Automatic Export.
6. Set the export path to the `references.bib` path shown above.

The resulting workflow is:

```text
Zotero
  -> Better BibTeX Automatic Export
  -> references/references.bib
  -> LaTeX compilation
  -> PDF
```

The manuscript skill does not open Zotero, change Zotero settings, access the
Zotero database, or call a Zotero API. Complete the Automatic Export setup in
Zotero itself. A normal manuscript build never updates the bibliography.

## Manual fallback

If Automatic Export is unavailable, export a Better BibTeX file explicitly and
run:

```bash
python run.py sync-bib --bib-export /absolute/path/to/export.bib
```

Use `sync-bib` only as a manual fallback. After changing the bibliography, run
`python run.py check` before rebuilding the manuscript.
