# V1 Architecture Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the v1 candidate into flat, explicit domain modules without changing manuscript, revision, PDF, audit, or submission behavior.

**Architecture:** `ProjectConfig` owns every canonical workspace path. Low-level `errors`, `tex`, and `review_ids` modules feed focused domain modules; `api` remains the public facade and `cli` only adapts arguments/output. Existing algorithms move intact before any cleanup, with regression tests at every boundary.

**Tech Stack:** Python 3.11+, pathlib, dataclasses, PyYAML, pytest, Ruff, Mypy, Tectonic, latexdiff, Poppler.

---

## Design audit

`TASK_MODE=implementation`

**Goal and completion conditions:** preserve all 87 baseline behaviors, close the malformed-pending audit hole, remove the no-op public option, make state/output/tmp/archive ownership explicit, pass all release gates and the real `07_perspective` E2E, and prove scientific hashes unchanged.

**Behavior that cannot change:** adjacent/direct-parent diffing; FINE math markup; reviewer-red, author-blue, light-gray strikeout, unchanged-black rendering; provenance intervals; CJK punctuation continuity; review locations; clean/marked/response PDFs; submission checklist/package; rollback/reindex digests; bibliography and scientific source bytes.

**Modules and data flow:** `errors/tex/review_ids -> authors/metadata/workspace -> templates/compile/provenance/review -> bibliography/locations/diff/response -> submission -> api -> cli`.

**Confirmed problems and evidence:** `pending_response_ids()` raises outside the audit parser guard; `allow_placeholders` is deleted immediately; `workspace.py`, `metadata.py`, `response.py`, `diff.py`, and `api.py` mix multiple stable domains; canonical state paths are duplicated; revision creation state lives in a round root; runtime TeX is embedded in Python; current docs contradict FINE math and current colors; tracked `.DS_Store` and a bibliography diagnostic pollute the paper snapshot.

**Simpler/more complex alternatives rejected:** keeping large files does not meet the requested ownership boundaries; service/controller packages, protocols, registries, managers, plugin frameworks, and a parser class hierarchy add no current value. Use flat modules, functions, and existing dataclasses only.

**Verification commands:** targeted pytest after every slice, then compileall, non-integration pytest, Ruff format/check, Mypy, build, integration pytest, wheel smoke, real doctor/status/build/submission, PDF text/vector/raster/layout checks, hash comparison, and Git/remote SHA verification.

### Task 1: Freeze regressions and release blockers

**Files:**
- Modify: `tests/test_review_audit.py`
- Modify: `tests/test_architecture.py`
- Modify: `tests/test_core.py`

- [ ] **Step 1: Add malformed pending audit tests**

```python
@pytest.mark.parametrize("marker", ("2-1", "invalid"))
def test_malformed_pending_marker_is_nonblocking(marker: str, tmp_path: Path) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    version = config.project / "revision_01"
    (version / "response" / "reviewer_comments.md").write_text(
        "# Reviewer #1\n\n1. Comment.\n", encoding="utf-8"
    )
    response = version / "response" / "responses.tex"
    response.write_text(
        f"\\Response{{1-1}}{{\\ResponsePending{{{marker}}}}}\n", encoding="utf-8"
    )
    audit = audit_reviews(load_project(config.project, 1), 1)
    issue = next(item for item in audit.issues if item.code == "RESPONSES_INVALID")
    assert response.resolve() in issue.paths
```

- [ ] **Step 2: Run the two cases and verify RED**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_review_audit.py -k malformed_pending`

Expected: both cases fail because `audit_reviews()` raises `WorkflowError`.

- [ ] **Step 3: Add public architecture invariants**

Test observable contracts: no `allow-placeholders` parser action or API parameter; all output children are PDFs; canonical state paths; packaged revision resources; no embedded runtime constants; no tracked `.DS_Store`; docs contain no obsolete visual or WHOLE contract.

- [ ] **Step 4: Run new architecture tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_architecture.py tests/test_review_audit.py -k 'architecture or malformed or placeholders'`

Expected: fail only on invariants not yet implemented.

### Task 2: Make malformed response audit non-blocking and preserve published API

**Files:**
- Modify: `src/sci_manuscript/review.py` after Task 6 extraction, initially `src/sci_manuscript/response.py`
- Modify: `src/sci_manuscript/api.py`
- Modify: `src/sci_manuscript/cli.py`
- Modify: `tests/test_review_audit.py`
- Modify: `tests/test_core.py`

- [ ] **Step 1: Catch pending-marker validation at the same response boundary**

```python
try:
    responses = parse_response_entries(response_path)
    pending = set(pending_response_ids(responses))
except WorkflowError as exc:
    responses = {}
    pending = set()
    issues.append(
        ReviewAuditIssue("RESPONSES_INVALID", None, str(exc), (response_path,))
    )
```

- [ ] **Step 2: Verify GREEN and build non-blocking behavior**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_review_audit.py -k 'malformed_pending or warning'`

Expected: pass; absolute response path present.

- [ ] **Step 3: Apply the user's published-compatibility exception**

Remote tag `v1.0.0` contains the argparse option and both public API keywords. Do not remove this published interface. Preserve its current compatibility behavior and report the evidence; keep response rendering policy internal so malformed response input yields no response PDF, clean/marked remain available, and the checklist records `INCOMPLETE`.

- [ ] **Step 4: Add and run submission regression**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_review_audit.py tests/test_core.py -k 'malformed or submission or placeholder'`

Expected: pass with no response PDF for malformed input.

### Task 3: Establish low-level ownership

**Files:**
- Modify: `src/sci_manuscript/errors.py`
- Create: `src/sci_manuscript/tex.py`
- Create: `src/sci_manuscript/review_ids.py`
- Modify: `src/sci_manuscript/workspace.py`
- Modify: `src/sci_manuscript/provenance.py`
- Modify: `src/sci_manuscript/diff.py`
- Modify: `src/sci_manuscript/response.py`
- Create: `tests/test_tex.py`
- Create: `tests/test_review.py`

- [ ] **Step 1: Write RED tests for TeX helpers**

```python
def test_extract_braced_handles_nested_escaped_and_comments() -> None:
    text = "  {outer {nested} \\{literal\\} % hidden }\n tail}"
    value, end = extract_braced(text, 0)
    assert value.endswith(" tail")
    assert end == len(text)
```

Also cover escaped-command detection and whitespace/comments.

- [ ] **Step 2: Implement minimal `tex.py` functions**

Provide only `is_escaped`, `skip_tex_space`, `extract_braced`, and `command_at`; accept an exception factory/message where domain-specific error text must remain stable.

- [ ] **Step 3: Move `WorkflowError` and review-ID grammar**

`errors.py` owns `ManuscriptError` and `WorkflowError`. `review_ids.py` owns `REVIEW_ID`, `is_review_id()`, and `validate_review_id_list()`; retain `workspace.WorkflowError` compatibility import while all internal imports use `.errors`.

- [ ] **Step 4: Migrate callers and delete duplicates**

Run: `rg -n 'def (_is_escaped|_skip_space|_skip_tex_space|_extract_braced|is_review_id|validate_review_id_list)' src/sci_manuscript`.

Expected: only canonical helpers/ID definitions remain.

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_tex.py tests/test_provenance.py tests/test_review_audit.py tests/test_core.py -k 'parser or provenance or response or braced or review_id'`

### Task 4: Canonical paths and state migration

**Files:**
- Modify: `src/sci_manuscript/workspace.py`
- Modify: all path consumers under `src/sci_manuscript/`
- Modify: `tests/test_architecture.py`
- Modify: `tests/test_core.py`
- Modify: `tests/test_review_audit.py`

- [ ] **Step 1: Write RED path/state tests**

```python
def test_project_config_owns_workspace_paths(config: ProjectConfig) -> None:
    assert config.output_dir(1) == config.project / "revision_01" / "output"
    assert config.state_dir(1) == config.project / "state" / "revision_01"
    assert config.creation_record_path(1) == config.state_dir(1) / "creation.yaml"
    assert config.review_index_path(1) == config.state_dir(1) / "review_index.yaml"
```

- [ ] **Step 2: Add direct path methods**

Add `round_dir`, `output_dir`, `response_dir`, `submission_dir`, `state_dir`, `review_index_path`, `creation_record_path`, `tmp_root`, and `archive_root` to `ProjectConfig`.

- [ ] **Step 3: Move creation state with legacy read compatibility**

New revisions write `state/revision_NN/creation.yaml`; `_load_creation()` checks canonical first then `revision_NN/revision_creation.yaml`. Reindex/rollback update canonical records without changing digest fields.

- [ ] **Step 4: Replace canonical path concatenation**

Migrate build, review, diff, response, submission, and API callers to `ProjectConfig` methods. Architecture test parses AST path expressions and flags canonical literals outside `workspace.py` rather than relying on broad source substrings.

- [ ] **Step 5: Run workspace/state tests**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_core.py tests/test_review_audit.py tests/test_architecture.py -k 'revision or rollback or reindex or state or path or output'`

### Task 5: Extract workspace-adjacent domains

**Files:**
- Create: `src/sci_manuscript/templates.py`
- Create: `src/sci_manuscript/bibliography.py`
- Create: `src/sci_manuscript/authors.py`
- Modify: `src/sci_manuscript/workspace.py`
- Modify: `src/sci_manuscript/metadata.py`
- Modify: `src/sci_manuscript/compile.py`
- Modify: `src/sci_manuscript/api.py`
- Modify: `src/sci_manuscript/cli.py`
- Create: `tests/test_workspace.py`
- Create: `tests/test_metadata.py`
- Create: `tests/test_templates.py`

- [ ] **Step 1: Move template functions intact**

Move `resources_root`, publisher resolution/layout, token rendering, manuscript initialization, and preamble initialization to `templates.py`. Replace the hidden reviewer placeholder in `start_revision()` with one explicit template copy path supplied by lifecycle initialization.

- [ ] **Step 2: Move bibliography functions intact**

Move export discovery and `sync_bibliography()` to `bibliography.py`; preserve explicit-source precedence and atomic archive behavior.

- [ ] **Step 3: Move author-library domain intact**

Move `AuthorRecord`, `AffiliationRecord`, `AuthorLibrary`, configuration/load/resolve functions, `AuthorSelection`, and signing resolution to `authors.py`. Keep manuscript metadata serialization and publisher metadata rendering in `metadata.py` to avoid a second rendering layer.

- [ ] **Step 4: Update imports and run focused tests**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_authors.py tests/test_publishers.py tests/test_workspace.py tests/test_metadata.py tests/test_templates.py tests/test_core.py`

### Task 6: Separate review, response, locations, and runtime resources

**Files:**
- Create: `src/sci_manuscript/review.py`
- Modify: `src/sci_manuscript/response.py`
- Create: `src/sci_manuscript/locations.py`
- Modify: `src/sci_manuscript/diff.py`
- Create: `src/sci_manuscript/resources/revision/style.tex`
- Create: `src/sci_manuscript/resources/revision/marked_runtime.tex`
- Create: `src/sci_manuscript/resources/revision/location_runtime.tex`
- Delete: `src/sci_manuscript/resources/revision_style.tex`
- Modify: `tests/test_review_audit.py`
- Modify: `tests/test_revision_style.py`
- Modify: `tests/test_release_integration.py`

- [ ] **Step 1: Move review parsing/audit/state intact**

`review.py` owns comment/response-entry parsers, audit dataclasses, pending state, triad audit, and review-index persistence. `response.py` owns editable response initialization, letter body/template assembly, and compile only.

- [ ] **Step 2: Move locations intact**

Move registry/AUX parsing, range formatting, transparent compilation, and `dict[review_id, location]` production to `locations.py`; keep constants public only where release tests need them.

- [ ] **Step 3: Externalize runtime TeX byte-for-byte**

Load marked/location runtime templates with `importlib.resources`; move the current style resource under `resources/revision/style.tex`, while project initialization continues copying it as `manuscript/references/revision_style.tex`.

- [ ] **Step 4: Verify package and PDF semantics**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_revision_style.py tests/test_provenance.py tests/test_review_audit.py tests/test_release_integration.py -k 'runtime or location or revision or audit'`

### Task 7: Extract submission orchestration and shrink API

**Files:**
- Create: `src/sci_manuscript/submission.py`
- Modify: `src/sci_manuscript/api.py`
- Modify: `src/sci_manuscript/cli.py`
- Create: `tests/test_submission.py`
- Modify: `tests/test_core.py`
- Modify: `tests/test_release_integration.py`

- [ ] **Step 1: Move submission implementation intact**

Move submission workspace orchestration, cover/highlights/graphical-abstract compilation, package staging, checklist state, and final assembly into `submission.py`. Expose one internal function returning existing `Artifact`-compatible paths/labels without importing `api` from below.

- [ ] **Step 2: Keep facade result types in API**

`api.py` retains public result dataclasses, doctor/init, `ManuscriptProject`, and lifecycle ordering. Convert internal submission results into public `Artifact` records at the facade boundary.

- [ ] **Step 3: Test malformed response package semantics**

Assert clean and marked PDFs exist, checklist is `INCOMPLETE`, response PDF is absent, and warning includes the absolute `responses.tex` path.

- [ ] **Step 4: Run submission/API/CLI tests**

Run: `PYTHONPATH=src .venv/bin/pytest -q tests/test_submission.py tests/test_core.py tests/test_review_audit.py tests/test_release_integration.py -k 'submission or cli or malformed or package'`

### Task 8: Documentation, release evidence, and paper migration

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `references/revision_semantics.md`
- Modify: `references/workflow.md`
- Modify: `CHANGELOG.md`
- Move in paper: `manuscript/revision_01/output/bibliography_diagnostic_r01.md` -> `manuscript/00_archive/diagnostics/bibliography_diagnostic_r01.md`
- Move in paper: `manuscript/revision_01/revision_creation.yaml` -> `manuscript/state/revision_01/creation.yaml`

- [ ] **Step 1: Record release evidence**

Verify local/remote tags and GitHub releases. Evidence at baseline: remote `v1.0.0` exists; no `v1.1.0` tag or GitHub release; package metadata is `1.1.0`. Correct the unreleased 1.1.0 changelog entry without rewriting v1.0.0 history.

- [ ] **Step 2: Unify current docs**

All current docs state FINE math, reviewer red text only, author blue text only, deletion light-gray strikeout, and canonical output/state/tmp/archive/submission ownership. Remove active `allow-placeholders` documentation.

- [ ] **Step 3: Move paper infrastructure without byte changes**

Use `git mv` for the diagnostic and creation record. Remove every tracked `.DS_Store` with `git rm --cached` only; preserve local files.

- [ ] **Step 4: Verify paper structure and hashes**

Run source manifest comparison and assert only infrastructure/state/archive/index changes.

### Task 9: Full verification and audit branch publication

**Files:**
- All modified files from Tasks 1-8

- [ ] **Step 1: Run fresh Skill release gates**

```bash
export PATH="$PWD/.venv/bin:$PATH"
export PYTHONPATH="$PWD/src"
export SCI_MANUSCRIPT_CJK_FONT_DIR="/Users/wenv/Library/Caches/Tectonic/bundles/data/6ffe055852f8faf66c0acbe1a7fb27f87b869a90bad1204f3bf4d9683f597c7c"
python -m compileall -q src tests
pytest -q -m "not integration"
ruff format --check .
ruff check .
mypy src tests
python -m build
pytest -q -m integration
```

- [ ] **Step 2: Run wheel smoke test**

Install the newly built wheel into a fresh temporary venv; import every public module, confirm version `1.1.0`, run `sci-manuscript --help`, and verify packaged revision resources.

- [ ] **Step 3: Run real manuscript E2E**

Run doctor, status, build `revision_01`, and submission `revision_01` with the local source/wheel. Verify clean/marked/response PDFs, pdftotext, SVG/vector color/stroke semantics, rasterized Formula 6/reviewer/author/deletion/CJK pages, layout QA, Figure 1 at `0.7\\linewidth`, Figure 2 absent, Response 2-3 preserved, bibliography/cross-references/equation numbers, and no U+200B/sentinel/DIF leakage.

- [ ] **Step 4: Recompute scientific hashes**

Every protected prose/equation/citation/reviewer/response/bibliography/figure/table/metadata hash must match the baseline.

- [ ] **Step 5: Review exact diffs and staging sets**

Inspect `git diff`, `git diff --cached`, tracked files, import graph/cycles, output/state/tmp ownership, and excluded generated files. Stage explicit paths only.

- [ ] **Step 6: Commit and push without force**

Commit Skill `release/v1-architecture` and paper `audit/v1-architecture`, push with upstream, then require local HEAD equals `git ls-remote` for each branch. Do not touch main/master, tags, or releases.

## Self-review

- Spec coverage: all six release blockers, all requested module boundaries, five-way state ownership, 13 architecture invariants, release history evidence, paper migrations, real E2E, scientific protection, and GitHub publication map to Tasks 1-9.
- Placeholder scan: no TBD/TODO/future implementation placeholders remain.
- Type consistency: `ProjectConfig` path names, `ReviewAuditResult`, `Artifact`, and `dict[str, str]` locations are consistent across tasks.
