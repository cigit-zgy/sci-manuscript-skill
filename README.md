# SCI Manuscript Skill

A deterministic LaTeX manuscript lifecycle for agent-assisted scientific writing workflows. The package manages project initialization, adjacent revision creation, safe rollback, revision-chain repair, clean builds, submission packaging, and explicit bibliography synchronization while preserving user ownership of scientific content.

## Architecture

The repository intentionally has **no `src/sci_manuscript/` directory**. Setuptools maps `src/` directly to the installed `sci_manuscript` package. Internal responsibilities are separated as follows:

```text
SKILL.md
   ↓
CLI / public API
   ↓
workflow/                 one lifecycle operation, one implementation owner
   ↓
domain/                   revision identity, manuscript metadata, review model
latex/                    compilation and marked-manuscript generation
infrastructure/           filesystem discovery, hashing, manifests, transactions
resources/                templates and workflow contracts
```

The critical revision contract is gap-free and adjacent:

```text
initial_submission (r00) → revision_01 (r01) → revision_02 (r02) → ...
```

Revision creation requires explicit confirmation in the CLI. Rollback is allowed only for the latest revision when user-owned sources remain unchanged from the creation manifest. Reindexing repairs a broken sequence transactionally and verifies that protected scientific sources retain identical hashes.

## Marked manuscript

![Marked manuscript](docs/images/marked_manuscript.png)

## Response letter

![Response letter](docs/images/response_letter.png)

The two screenshots above intentionally use exactly the same pixel dimensions. This is enforced by the automated test suite.

## Install

```bash
python -m pip install -e '.[dev]'
```

## Core commands

```bash
sci-manuscript init --project paper --title "Title" --journal "Journal" --publisher elsevier
python paper/run.py status --project paper
python paper/run.py revision --project paper --reviews reviews.md
python paper/run.py rollback --project paper
python paper/run.py reindex --project paper
python paper/run.py submission --project paper
```

## Safety invariants

Scientific manuscript prose, figures, tables, response text, bibliography content and submission prose are user-owned. The runtime does not autonomously rewrite them. Revision creation copies the parent state and records a creation manifest. Rollback refuses deletion after protected edits. Reindex changes revision identity and generated artifacts only, with transactional rollback on failure.

## Quality gates

CI runs tests, formatting, Ruff, Mypy, wheel/sdist builds, distribution auditing, installed-wheel smoke tests, architecture ownership checks, transaction fault-injection tests, and README image dimension checks.
