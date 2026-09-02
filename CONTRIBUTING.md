# Contributing

Thank you for improving `sci-manuscript`. Keep changes focused on one
observable manuscript-workflow behavior and preserve user-owned scientific
content.

## Development setup

```bash
python -m pip install ".[dev]"
```

Reinstall after changing package code. The regular install materializes the
explicit `src/` to `sci_manuscript` package mapping for Python and mypy without
`PYTHONPATH`, runtime path mutation, or an import-loader shim.

The real integration suite also requires the LaTeX, `latexdiff`, CJK-probe,
optional PDF-presentation, and font dependencies reported by
`sci-manuscript doctor`.

## Quality gate

Before proposing a change, run the smallest relevant tests while developing.
Run the complete gate once the change is stable:

```bash
python -m compileall -q src tests
pytest -q
ruff format --check .
ruff check .
mypy src tests
python -m build
git diff --check
```

Changes to revision semantics, project layout, publisher resources, or response
templates must include behavior-oriented regression tests and corresponding
public documentation. Do not commit PDFs, compiler intermediates, local
manuscript projects, credentials, or absolute private paths.

## Pull requests

Explain the user-visible problem, the evidence for the fix, and the validation
performed. Keep scientific content and reviewer ownership decisions out of
infrastructure changes unless the repository owner explicitly supplied them.
