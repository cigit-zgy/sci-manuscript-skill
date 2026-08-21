# Agent behavior evaluations

`evals/` describes how an agent should select and operate this skill. It does
not replace the software tests in `tests/`.

## Files

- `evals.json` follows Anthropic skill-creator's current schema. Each realistic
  workflow prompt has a human-readable expected outcome and verifiable
  expectations.
- `trigger_evals.json` contains realistic bilingual near-boundary queries for
  description triggering. It uses the query/`should_trigger` format accepted by
  skill-creator's trigger evaluator.
- `initialization.yaml`, `revision.yaml`, `missing_information.yaml`,
  `zotero.yaml`, and `publisher_template.yaml` are focused stable behavior cases
  for user-information gates, shared references, Zotero boundaries, and real
  publisher resource selection.

## Evaluation boundary

`tests/` verifies deterministic Python behavior, paths, compilation, revision
ancestry, PDF production, and cleanup. `evals/` verifies agent behavior such as
triggering, routing, authorization, and avoidance of scientific-content
overreach.

Structural JSON validation is deterministic and may run in ordinary CI. A
runtime LLM evaluation requires a supported agent harness and must record the
actual model, date, outputs, and evidence. Do not report an eval as passed when
only its JSON definition was validated.
