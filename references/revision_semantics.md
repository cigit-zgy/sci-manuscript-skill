# Region-aware revision highlighting semantics

This document is the normative contract for the final marked manuscript. A
project must not introduce local diff semantics. Canonical region identities and
boundaries are defined in [manuscript_regions.md](manuscript_regions.md).

## 1. Hard identity and reasoning contract

The marked manuscript is the **current clean manuscript plus revision
presentation**. Removing package-owned highlighting/provenance markup must
reproduce the exact current scientific source projection: paragraphs, headings,
equations, floats, labels, citations, bibliography, numbering, cross-references,
whitespace, and structural seams. Parent-only content is never displayed.

The selected reasoning pipeline is fixed:

```text
STRUCTURE
    |
MATCH
    |
IDENTITY
    |
CHANGE
    |
PROVENANCE
    |
PRESENTATION
    |
LOCATION
```

- **STRUCTURE** projects parent/current source into L0--L4 objects and records
  each object's kind, exact source interval, structural path, owner container,
  and sibling order.
- **MATCH** permits correspondence only between compatible parent/current
  objects inside the same ancestry and owner domain.
- **IDENTITY** applies the region-specific normalized identity defined in
  [manuscript_regions.md](manuscript_regions.md). An `identical-to` proof is an
  unchanged hard veto.
- **CHANGE** determines WHAT changed and selects the current L3 natural unit.
  This stage is completely owner-free.
- **PROVENANCE** determines WHO owns an already-changed unit: `AUTHOR` or
  `REVIEWER(ID/IDs)`.
- **PRESENTATION** renders RubineRed, ForestGreen, native xcolor `blue`, or
  black without changing current scientific structure.
- **LOCATION** projects reviewer-owned visible change events to the final
  TeX-native line numbers.

In compact terms, STRUCTURE is the canonical region projection, MATCH is
same-context region matching, CHANGE asks `WHAT changed?`, and PROVENANCE asks
`WHO owns it?`.

WHAT-before-WHO is a hard invariant. `\review` participates only in
PROVENANCE. It cannot alter STRUCTURE, MATCH, IDENTITY, or CHANGE. Therefore
unchanged text inside `\review` is `UNCHANGED` and black; being inside a wrapper
is never evidence that content changed.

`latexdiff` remains auxiliary change evidence. It does not choose final heading,
prose, equation, table, list, caption, or frontmatter granularity and is never a
layout authority. It cannot create a change certificate or decide provenance.
When its addition evidence overlaps an identity-certified unit, the audit records
a `DETECTOR_DISAGREEMENT`; identity wins and the unit remains black.

The correctness rule is therefore:

```text
IDENTITY DETERMINES CORRECTNESS
CHANGE REQUIRES POSITIVE EVIDENCE
SEGMENTATION ONLY DETERMINES PRESENTATION GRANULARITY
NO CHANGE CERTIFICATE = NO REVISION COLOR
```

## 2. Change-state vocabulary

The semantic model uses only these states:

| State | Meaning | Default visible consequence |
| --- | --- | --- |
| `UNCHANGED` | A unique region-specific `identical-to` proof exists. | black |
| `CHANGED` | The same logical object is matched, but its L3 content changed. | whole current natural unit red/green after provenance |
| `ADDED` | The current object has no compatible parent correspondence. | whole current natural unit red/green after provenance |
| `MOVED_COMPATIBLE` | Position changed while identity remains proven and the region's move rule permits unchanged visual content. | body remains black; structural audit may record the move |
| `STRUCTURAL_CHANGED` | Owner context, ancestry, sequence, span, asset, or another region-defined structural property changed materially. | region-specific structural event and, only where allowed, current-unit presentation |
| `AMBIGUOUS` | Evidence cannot establish one safe correspondence among duplicate candidates. | build fails closed; color is never authorized |

Parent-only content is absent from the current marked manuscript rather than a
seventh visible state. Implementation audit reasons such as `CONTENT`,
`CURRENT_ONLY`, `STRUCTURAL_MOVE`, and `REORDERED` are bounded evidence fields:
they map to `CHANGED`, `ADDED`, or `STRUCTURAL_CHANGED`; they do not expand the
semantic state vocabulary. Duplicate ambiguity is counted separately, and an
identical moved equation maps to `MOVED_COMPATIBLE` even when label, ancestry,
or sequence metadata forms a structural event.

## 3. Proof and render certificates

The implementation uses three compact proof records and no class hierarchy:

- `IdentityCertificate` binds one current unit to exact/normalized-identical
  parent unit IDs and is a black hard veto.
- `ChangeCertificate` binds one `CHANGED` or proved `ADDED` current unit to a
  deterministic `event_id`. Only this record authorizes revision presentation.
- `StructuralEvent` records moves, asset changes, ancestry changes, and related
  non-visual facts. It never creates a visual certificate by itself.

The renderer consumes validated change certificates, resolves ownership only
from current-source provenance, and inserts exactly one canonical author or
reviewer macro per authorized event. Executing that macro writes a compact
`REVISION|event_id|owner|IDs` record to the package SCI sidecar. TeX may expand
stored frontmatter after body-source macros, so source order and execution order
need not match; event ID, ownership, uniqueness, and cardinality must match
exactly.

The required invariant is:

```text
authorized visual events == ChangeCertificates == unique RenderCertificates
unexpected == missing == duplicate == owner conflicts == 0
```

## 4. Region-specific revision units

Identity, parent scope, move rules, and protected content are defined only by
the canonical master table in
[manuscript_regions.md](manuscript_regions.md#5-canonical-region-contract-table).
This table is a presentation summary and does not establish a second matching
contract.

| Current region | Natural unit when changed | Presentation exception |
| --- | --- | --- |
| document/secondary title | whole current title | none |
| author/affiliation/note | whole affected current item/field | none |
| funding | affected grant item | unaffected grants black |
| abstract/prose/footnote/backmatter | sentence; long-sentence clause | protected L4 islands remain atomic |
| keywords | affected keyword item | unaffected keywords black |
| H1/H2/H3/H4+ | whole visible current heading | generated number is not content |
| inline math | enclosing prose unit | no internal math-token diff |
| display equation | whole current equation body | identical body is always black |
| figure asset | structural event | pixels never tinted; caption separate |
| figure/table caption | sentence; long-sentence clause | unchanged caption black |
| table | whole row or cell | merged/span change selects current merged cell |
| list | whole short item; sentence/clause in long item | no cross-owner matching |
| bibliography entry | no visual change unit | prose black; provenance/audit only |
| citation/cross-reference/DOI/URL | protected inline unit | native link blue, never revision red/green |

Heading numbers, equation numbers, citation numbers, table/figure numbers, and
bibliography order generated by the current toolchain are not revision content.

## 5. Prose segmentation and matching

Chinese strong sentence boundaries are `。！？；`; English strong boundaries are
`. ! ? ;`. English segmentation conservatively protects abbreviations,
decimals, DOI values, URLs, TeX commands, and inline math.

Weak clause boundaries are `，：` for Chinese and `, :` for English. They are
used only when a sentence exceeds one named threshold:

- Chinese: more than 50 visible lexical atoms; each final clause has at least
  15 atoms;
- English: more than 30 words; each final clause has at least 10 words;
- every original sentence produces at most three deterministic revision units.

Within the same structural context, whole-block identity is tested first. Only a
different block proceeds to whole-sentence identity; only a different long
sentence proceeds to clause identity. Exact/normalized identity anchors are
established before unmatched units are classified. No fuzzy, semantic, NLP, or
embedding similarity participates. The final states are:

```text
exact matched unit -> black
paired but changed unit -> whole current unit highlighted
current-only unit -> whole current unit highlighted
parent-only unit -> absent
```

Character-, word-, and short-phrase-level fragments are not final presentation
modes. A substantively changed ordinary sentence is highlighted as one whole
unit even when only a few lexical atoms changed. Segmentation never converts an
identity-certified sentence into a change.

## 6. Structural moves

A source-file relocation is not a move when the rendered hierarchy, relative
logical order, and normalized content remain compatible. An identical prose,
heading, list, or table unit in a different heading ancestry, a heading with a
different parent, or a reordered paragraph/list/table sequence is a structural
revision. Equations follow the stronger mathematical-body veto below.

Global exact-content suppression is forbidden. Matching is local to compatible
document region and structural path. Automatic renumbering caused by surrounding
content is not itself a revision.

## 7. Equations, figures, tables, and lists

A display equation uses conservative normalized identity. Comments, line wraps,
and TeX-ignored math whitespace do not change identity; commands, variables,
numbers, operators, grouping, arguments, superscripts, subscripts, and visible
text-command content do. A normalized-identical mathematical body is always
black, including when its file, position, subsection ancestry, label, tag, or
environment metadata changes. Those metadata changes may be recorded as
structural events but cannot color identical mathematics. Only a substantively
changed body colors the whole current equation body while retaining the current
environment, label, tag, and number.

Figure pixels are never colored. A changed asset is an owned structural event
with provenance and audit evidence, but an unchanged caption remains black and
is never used as a visual proxy. A changed caption follows the prose natural-unit
rule. Table changes use current row/cell units. Merged-cell span changes color
the whole current merged cell. Added and reordered list items are current
structural changes.

## 8. Provenance, colors, and deletion

Change detection precedes provenance. `\review{IDs}{body}` defines ownership
intervals only and cannot make unchanged text changed. Reviewer-owned current
units are RubineRed, author-owned current units are ForestGreen, and unchanged
content is black.

If one changed sentence/clause contains both reviewer and author changes, split
only at provenance boundaries into larger readable segments. If ownership cannot
be assigned without guessing, fail with an actionable audit; never silently pick
one color and never fall back to character diff.

Parent-only content is absent. There is no strikeout, gray deletion, restored
parent structure, or deleted bibliography entry. A pure reviewer deletion uses
the existing response note:

- Chinese: `修改位置：相关内容已删除，当前稿无对应高亮文本。`
- English: `Location: The relevant text has been removed; no corresponding highlighted text remains in the revised manuscript.`

## 9. Protected references and bibliography

Citation identity is the BibTeX key set, never the rendered number. Citation
commands, cross-references, and reference-related DOI/URL links are protected
islands. Their source syntax is preserved and their visual link color remains
native xcolor `blue` (#0000FF) in clean and marked output, independent of
author/reviewer ownership. RubineRed or ForestGreen prose may appear on both
sides of a blue citation without consuming it.

The current bibliography is the sole visible authority. Entry prose remains
black; DOI/URL links remain blue. Citation provenance and explicit
`\ReviewReference` continue to drive audit and response locations only. AUTHOR
versus REVIEWER remains a hard `REFERENCE_PROVENANCE_CONFLICT`.

## 10. Locations, state, and acceptance

TeX-native `lineno + \linelabel + AUX` remains the only location backend.
Response font/layout, bibliography snapshots, historical round immutability,
submission provenance, and artifact freshness contracts are unchanged. A new
renderer implementation identity must make prior marked artifacts stale; a
response depending on those locations must become stale with it.

Acceptance requires all of the following to be true:

- exact current-source projection;
- whitespace and paragraph identity;
- block-topology identity;
- section/equation/figure/table labels and citation state from AUX;
- rendered bibliography identity from BBL and BibTeX keys;
- a complete package-owned marked TeX sidecar registry;
- exact identity/ownership equality between expected change certificates and
  executed render certificates;
- protected citation style identity;
- zero ambiguous units, unexpected/missing/duplicate render events, unresolved
  additions, and reference/provenance conflicts;
- deterministic region audit counts and actionable ambiguity diagnostics.

All machine audits remain under `tmp/`; only canonical PDFs belong in revision
`output/`. Final PDFs are delivery artifacts and are never reverse-parsed to
infer scientific, revision, provenance, response, numbering, bibliography, or
location correctness.
