# Test Summary

Date: 2026-08-21

The v3.0 directory contract and publisher system were preserved. This update
changed only the agent workflow entry, environment diagnostics, public
documentation, release hygiene, and type-quality defects found while running
the required gates.

## Environment

- Hardware: Apple Silicon macOS workstation.
- Selected runtime: Homebrew Python 3.14.6 through an isolated `uv` execution.
- Python dependency: PyYAML 6.0.3.
- LaTeX: Tectonic 0.17.0.
- Revision comparison: latexdiff 1.4.0.
- PDF QA: Poppler 26.08.0 (`pdftotext` and `pdftoppm`).
- Bibliography: Tectonic-integrated BibTeX processing.
- Development gates: Ruff 0.16.3 and Mypy 2.3.1.
- Alternative TeX Live path: not exercised because `latexmk`, pdfLaTeX, and
  XeLaTeX were not installed. Tectonic satisfied the supported alternative.

No dependency was installed or upgraded by the workflow. A bare Homebrew
Python 3.14 environment without PyYAML produced a structured `BLOCKED` report
and exit status 2. The isolated environment with PyYAML produced `READY` and
exit status 0.

## Workflow Result

### Initial manuscript

A completely empty external `skill-test` workspace was initialized through the
public `init` command. It created `run.py`, `initial_submission/`, and `tmp/`,
generated author metadata from generic example data, and compiled
`initial_submission/output/manuscript.pdf`.

### First submission

The `submission` command created only
`initial_submission/submission/`. Its package contains `manuscript.pdf`,
`cover_letter.pdf`, `highlights.pdf`, `graphical_abstract.pdf`, and
`checklist.md`.

### R1 revision

The first `revision` command created `revision_1` from
`initial_submission` only. A minimal reviewer-linked replacement and completed
response were added. The `all` command generated:

- `revision_1/output/manuscript_clean.pdf`;
- `revision_1/output/manuscript_marked.pdf`;
- `revision_1/output/response_letter.pdf`;
- the complete version-local submission package.

Rendered-page inspection confirmed red struck-through deletion, blue
underlined addition, and continuous manuscript line numbers. The response
letter resolved the change to Lines 6--7.

### Second revision

The second `revision` command reported `revision_1 (r1)` as its parent and
created `revision_2`; no r0-to-r2 jump occurred. Inherited provenance wrappers
were removed before the new reviewer-linked edit was applied.

### R2 revision

The second `all` command generated:

- `revision_2/output/manuscript_clean.pdf`;
- `revision_2/output/manuscript_marked.pdf`;
- `revision_2/output/response_letter.pdf`;
- the complete version-local submission package.

All seven primary lifecycle PDFs opened, contained extractable text, and had
non-zero page counts. `tmp/` was empty after every successful command, and no
LaTeX compiler, latexdiff, or location-extraction intermediates were visible in
the project.

## Workflow and Documentation Changes

### SKILL workflow

`SKILL.md` now defines a mandatory agent sequence: inspect the environment,
request approval when blocked, collect project and author data, initialize,
compile, validate, and hand off editable files. It lists required and optional
dependencies, prohibits automatic installation, defines the approval boundary,
and names every example file the user must replace.

### Environment check

`doctor` now uses only the Python standard library before workflow imports. It
therefore reports missing PyYAML instead of crashing on import. Required checks
cover Python, PyYAML, the supported LaTeX alternatives, latexdiff, both Poppler
QA tools, and a bibliography backend. Ruff, Mypy, and manual Better BibTeX
integration are reported as optional.

### README

`README.md` was rewritten as a 1,600+ word GitHub-facing guide with purpose,
feature table, installation, quick start, command table, user configuration,
project structure, publisher resources, revision workflow, development gates,
and licensing. All examples use generic paths and identities and match the
actual v3.0 CLI.

### Public-release hygiene

Personal example author names, institutional email addresses, and affiliations
were replaced by `example.org` data. `.DS_Store`, Python caches, test caches,
compiler outputs, and generated PDFs were removed from the skill source.
`THIRD_PARTY_NOTICES.md` now separates the repository MIT license from bundled
publisher-resource terms.

## Chinese Journal Resource

The general `chinese` publisher category includes
`references/journal_templates/chinese/kxtbcas.cls`, copied at the maintainer's
direction from `manuscripts/kxtbcas.cls` in a maintainer-provided Chinese
manuscript workspace. The original source was not modified. The bundled copy
changes only its two private default font roots to portable local roots and
retains the existing system-font fallback behavior.

The resource README describes it as a reusable Chinese-journal starting point,
not a universal official template. Its actual author/figure/citation/bibliography
compile test passed. The supplied class has no embedded license notice or public
source URL. For v3.0.0, the repository maintainer explicitly confirmed that the
maintainer-provided template may be distributed publicly with this project.
This release-specific permission is recorded in both the resource README and
`THIRD_PARTY_NOTICES.md`.

## Passed

- `doctor` missing-PyYAML boundary: passed, exit 2 without traceback.
- `doctor` complete environment: passed, `Result: READY`.
- Unit and integration suite: 22 tests passed.
- Real Elsevier `elsarticle` compilation: passed.
- Real Springer Nature `sn-jnl` compilation: passed.
- Real ACS `achemso` compilation: passed.
- Real Chinese `kxtbcas` compilation: passed.
- Ruff formatting check: passed.
- Ruff lint: passed.
- Mypy over `scripts` and `tests`: passed with no issues.
- Skill frontmatter and scaffold validator: passed.
- Strict public-language scan with a Chinese-workflow allowlist: passed.
- Fresh r0 -> r1 -> r2 lifecycle: passed.
- PDF text extraction and rendered-page QA: passed.
- Temporary-file cleanup and public-tree hygiene: passed.

## Problems Found

### Problem 1

Location: `scripts/run.py` environment bootstrap.

Observed: Before this update, importing the CLI required PyYAML before
`doctor` could run, so the diagnostic could not report that PyYAML was missing.

Expected: Environment inspection must remain usable when a required dependency
is absent.

Severity: High.

Suggestion: Implemented. The dependency-light diagnostic runs before internal
workflow imports and returns a structured blocking result.

### Problem 2

Location: `references/authors.yaml` and related tests.

Observed: Default example data contained personal names, institutional email
addresses, and affiliations unsuitable for an immediately public repository.

Expected: Public examples must be obviously synthetic and non-sensitive.

Severity: High for public release.

Suggestion: Implemented. Examples now use generic identities and
`example.org` addresses.

### Problem 3

Location: `scripts/workspace.py` revision staging and publisher tests.

Observed: Mypy found a loop-variable type collision in revision creation and
untyped test class attributes.

Expected: Modified paths and tests should pass the configured static checker.

Severity: Medium.

Suggestion: Implemented with explicit variable names and class annotations;
runtime behavior was unchanged.

### Problem 4

Location: generated project `run.py`.

Observed: Manuscript data and revision history are project-local, but the
copied entrypoint delegates execution to the skill installation path recorded
at initialization.

Expected: A fully portable standalone project would carry or install a stable
runtime independent of the original checkout location.

Severity: Medium; this is a documented v3.0 architectural limitation, not a
new regression.

Suggestion: Keep the skill installed or set `SCI_MANUSCRIPT_SKILL_ROOT` after
moving it. Consider a packaged CLI or versioned private runtime only in a future
major architecture change.

### Problem 5

Location: `references/journal_templates/chinese/kxtbcas.cls`.

Observed: The supplied class contains no embedded license or public provenance
URL.

Expected: The release record should state the basis for public distribution.

Severity: Resolved for v3.0.0 by explicit maintainer confirmation; no runtime
impact.

Suggestion: Implemented. The public-distribution confirmation is recorded in
the resource README and `THIRD_PARTY_NOTICES.md`. A future upstream URL or
embedded license would still improve provenance.

## Architecture Review

The current architecture functions as a scientific-paper LaTeX lifecycle tool:
one agent entry, one project CLI, semantic version directories, adjacent-only
revision ancestry, version-local submission material, generated metadata,
isolated build state, and executable publisher-resource tests. The separation
between deterministic Python workflow logic, editable LaTeX templates,
conditional references, and test code is appropriate.

### Retain

- `SKILL.md` as the agent decision and approval boundary.
- One copied project `run.py` as the user-facing command surface.
- `initial_submission`, `revision_N`, and version-local `submission/`.
- Separate author library plus `manuscript.yaml` author selection.
- `revision_style.tex` as the only user-editable markup-style file.
- Publisher resources with provenance README files and actual compile tests.
- `tmp/run_*` isolation with cleanup after success.

### Potential simplification

1. **Priority 2:** Add an upstream URL or embedded license for `kxtbcas.cls` if
   one becomes available. Public distribution for v3.0.0 is already confirmed
   by the repository maintainer.
2. **Priority 2:** In a future major version, replace the absolute installed
   skill pointer in copied `run.py` with a packaged, versioned runtime. Do not
   add another ad hoc script copy to v3.0.
3. **Priority 3:** `scripts/run.py` is above the Python-style 500-line review
   signal. If environment diagnostics grow further, move that stable concern to
   a clearly named module; current behavior does not justify a speculative split.
4. **Priority 3:** Publisher demo `.tex` and distribution source files increase
   repository size but preserve provenance, licensing context, and update
   auditability. Keep them unless a checksum-verified release-asset downloader
   is deliberately introduced.
5. **Priority 4:** `SKILL.md` and `README.md` overlap on commands and structure,
   but serve different consumers (agent execution versus GitHub onboarding).
   Reduce duplication only if drift appears in practice.

No additional unused source file or directory was identified. Only caches and
Finder metadata were deleted.

The Python structure audit emitted review signals for long workflow functions,
the two established workflow modules above 500 lines, three intentionally small
path-boundary functions, and the test import-path setup. Manual review found no
speculative protocol, ABC, factory, registry, duplicate data model, or unsafe
import-time registration. The long `run.py` signal is retained above as a
future simplification candidate rather than mechanically splitting stable code.

## Final Skill Structure and File Responsibilities

```text
sci-manuscript-skill/
├── .gitignore
├── .pre-commit-config.yaml
├── LICENSE
├── README.md
├── SKILL.md
├── THIRD_PARTY_NOTICES.md
├── migration_report.md
├── pyproject.toml
├── references/
│   ├── authors.yaml
│   ├── environment.md
│   ├── revision_style.tex
│   ├── workflow.md
│   └── journal_templates/
│       ├── elsevier/
│       │   ├── README.md
│       │   ├── elsarticle.cls
│       │   ├── elsarticle-num.bst
│       │   ├── sections.yaml
│       │   └── template.tex
│       ├── nature/
│       │   ├── README.md
│       │   ├── sn-jnl.cls
│       │   ├── sn-nature.bst
│       │   ├── sections.yaml
│       │   └── template.tex
│       ├── acs/
│       │   ├── LICENSE.md
│       │   ├── README.md
│       │   ├── achemso.cls
│       │   ├── achemso.dtx
│       │   ├── sections.yaml
│       │   └── template.tex
│       └── chinese/
│           ├── README.md
│           ├── kxtbcas.cls
│           ├── sections.yaml
│           └── template.tex
├── scripts/
│   ├── compile.py
│   ├── diff.py
│   ├── metadata.py
│   ├── response.py
│   ├── run.py
│   └── workspace.py
├── templates/
│   ├── manuscript/
│   │   ├── main.tex
│   │   ├── preamble.tex
│   │   ├── references.bib
│   │   └── sections/default/*.tex
│   ├── response/
│   │   ├── response_en.tex
│   │   └── response_zh.tex
│   └── submission/
│       ├── checklist.md
│       ├── cover_letter_en.tex
│       ├── cover_letter_zh.tex
│       ├── highlights.tex
│       └── graphical_abstract/graphical_abstract.tex
└── tests/
    ├── test_core.py
    └── test_publishers.py
```

### Root files

- `.gitignore`: excludes Python, test, editor, and LaTeX build products.
- `.pre-commit-config.yaml`: pins Ruff lint and formatting hooks.
- `LICENSE`: MIT terms for original repository material.
- `README.md`: public installation, usage, architecture, and contributor guide.
- `SKILL.md`: executable agent workflow and authorization boundaries.
- `THIRD_PARTY_NOTICES.md`: upstream resource licensing and provenance scope.
- `migration_report.md`: this implementation, validation, and architecture
  record.
- `pyproject.toml`: Python version, PyYAML dependency, package metadata, Ruff,
  and Mypy configuration.

### References

- `authors.yaml`: generic author/affiliation example copied into new r0 projects.
- `environment.md`: conditional diagnostic and approved-installation guidance.
- `revision_style.tex`: user-adjustable colors and added/deleted text styling.
- `workflow.md`: conditional revision, response, submission, temporary-build,
  and package behavior.
- Publisher `README.md`: source, version, license, and adaptation provenance.
- Publisher class/BST/DTX files: actual LaTeX implementation and distributable
  upstream source material.
- Publisher `sections.yaml`: default ordered section names and filenames.
- Publisher `template.tex`: upstream or adapted demonstration source retained
  for audit and manual comparison.

### Python scripts

- `compile.py`: compiler selection and isolated clean-PDF production.
- `diff.py`: latexdiff generation, provenance denesting, marked PDF, and line
  location extraction.
- `metadata.py`: YAML validation, round metadata, author resolution, and
  `author_metadata.tex` generation.
- `response.py`: reviewer-comment parsing, response initialization, placeholder
  validation, and response PDF production.
- `run.py`: sole public subcommand parser and lifecycle orchestration entry.
- `workspace.py`: project layout, publisher adaptation, revision ancestry,
  bibliography synchronization, submission source initialization, and
  temporary-run lifecycle.

### LaTeX templates

- `manuscript/main.tex`: generic manuscript document using generated metadata
  and publisher-mapped section inputs.
- `manuscript/preamble.tex`: scientific packages, line numbering, engine, CJK,
  and publisher compatibility.
- `manuscript/references.bib`: explicit example bibliography.
- `manuscript/sections/default/*.tex`: minimal structural section placeholders.
- `response/response_en.tex` and `response_zh.tex`: language-specific response
  letter sources.
- `submission/checklist.md`: package completion checklist.
- `submission/cover_letter_*.tex`: independent English and Chinese cover letters.
- `submission/highlights.tex`: independent highlights source.
- `submission/graphical_abstract/graphical_abstract.tex`: standalone graphical
  abstract placeholder source.

### Tests

- `test_core.py`: metadata, initialization, revision chain, submission,
  bibliography, response, CLI, environment failure, diff provenance, and
  temporary-file invariants.
- `test_publishers.py`: actual Tectonic compilation of all four bundled
  publisher categories with author, figure, citation, and bibliography content.

## Release Status

The repository is technically clean and test-ready for a Git host. At the time
of this migration review it was not yet a Git working tree. The maintainer has
now explicitly confirmed public distribution of the maintainer-provided
`kxtbcas.cls`; all identified technical release gates pass.
