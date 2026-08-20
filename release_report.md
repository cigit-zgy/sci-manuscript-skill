# Release Report

## Version

3.0.0

Release type: initial public release.

## Checks

- `pytest -q`: 22 tests passed.
- `ruff format --check .`: passed; 20 files already formatted.
- `ruff check .`: passed with no lint errors.
- `mypy scripts tests`: passed with no issues in 8 source files.
- `python scripts/run.py doctor`: `Result: READY` with Python 3.14.6,
  PyYAML 6.0.3, Tectonic 0.17.0, latexdiff 1.4.0, Poppler 26.08.0,
  and Tectonic-integrated BibTeX processing.
- Skill validator: passed.
- Publisher compilation: Elsevier, Springer Nature, ACS, and the Chinese
  journal resource passed actual Tectonic compilation tests.
- Release hygiene: no Finder metadata, Python/test/Ruff/Mypy caches, PDFs,
  LaTeX intermediates, private absolute paths, or secret-like credentials are
  included.
- External lifecycle fixture: the separate `skill-test` workspace was verified
  as outside the repository and is not part of the release.

The Python structure audit reported review signals for established long
workflow functions and modules. Manual review found no syntax failure,
speculative abstraction, unsafe import-time registration, or new release
regression. Architecture remains frozen for v3.0.0.

## Published files

- `README.md`: public installation and usage documentation.
- `SKILL.md`: executable agent workflow entrypoint.
- `LICENSE`: MIT license for original project material.
- `THIRD_PARTY_NOTICES.md`: Elsevier, Springer Nature, ACS, and Chinese
  journal resource notices.
- `pyproject.toml`: version 3.0.0, runtime dependency, Ruff, and Mypy settings.
- `.gitignore` and `.pre-commit-config.yaml`: repository hygiene and Ruff
  pre-commit gates.
- `scripts/`: deterministic lifecycle implementation.
- `references/`: environment guidance, author example, revision style,
  workflow reference, and publisher resources.
- `templates/`: manuscript, response, cover letter, highlights, graphical
  abstract, and checklist templates.
- `tests/`: lifecycle and real publisher-compilation tests.
- `migration_report.md`: v3.0 architecture and validation record.
- `release_report.md`: this release record.

Generated PDFs, compiler intermediates, caches, and the external `skill-test`
workspace are not published.

## Git commit

Release commit message: `Initial release v3.0.0`.

The immutable commit identifier is recorded by the annotated `v3.0.0` tag and
in the final release output because a commit cannot embed its own hash.

## Tag

Annotated tag: `v3.0.0`

Tag message: `Initial release v3.0.0`

## Known limitations

- A generated project's copied `run.py` delegates to the installed skill path.
  If the skill checkout moves, set `SCI_MANUSCRIPT_SKILL_ROOT` to its new path.
- Publisher requirements can change after release; users must check the target
  journal's current author instructions.
- The maintainer-provided `kxtbcas.cls` has no public upstream URL or embedded
  license notice. The repository maintainer explicitly confirmed that it may be
  distributed publicly with this v3.0.0 project.
- Tectonic is the fully validated compiler path for this release. The supported
  TeX Live alternative was not available in the release environment.
- Ruff, Mypy, and pytest were executed in isolated development environments;
  they remain optional for manuscript users.
