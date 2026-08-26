# Highlighted revised manuscript semantics

This document is the normative contract for the final marked manuscript. A
project must not introduce local diff semantics.

## 1. Hard identity contract

The marked manuscript is the **current clean manuscript plus revision
highlighting**. After revision color/provenance markup is stripped, marked and
clean must contain identical current scientific content and structure:
paragraphs, headings, equations, floats, labels, citations, bibliography,
numbering, and cross-references. Parent-only content never appears in marked
source or PDF.

The direct-parent comparison is:

```text
parent + current without review wrappers
              |
          latexdiff
              v
     current-addition evidence only
              v
 provenance intersection + 60% fallback
              v
 markup inserted into exact current source
              v
          marked PDF
```

`latexdiff` is an addition detector, not a renderer or layout authority.
Deletion markup is disabled and is never parsed or rendered. The raw
`latexdiff` document is diagnostic evidence and is never published or compiled
as the final marked document.

## 2. Provenance and visible states

Removing `\review{IDs}{body}` yields the unchanged `body` bytes plus sidecar
source intervals. Nested scopes inherit and union IDs in first-seen order. The
wrapper defines ownership, not change extent: only a detected current addition
inside effective review provenance is reviewer-owned. Unchanged reviewed text
remains black; additions outside review provenance are author-owned.

| Current state | Appearance |
| --- | --- |
| unchanged | black |
| reviewer-owned addition or replacement | RubineRed |
| author-owned addition or replacement | ForestGreen |

There is no deletion appearance. Citation markers and reference-related DOI/URL
links use xcolor `ProcessBlue` from `dvipsnames` in clean and marked output. Bibliography prose
and unchanged manuscript text remain black; publisher-specific internal-link
behavior is not overridden.

## 3. Adaptive highlighting

The default is native fine-grained latexdiff addition spans. For an easily
recognized current paragraph, heading, or caption, addition coverage is the
visible added length divided by total visible current length. Coverage below
0.60 stays fine-grained. Coverage at or above 0.60 may highlight the entire
current block only when every addition has exactly the same effective
provenance. Mixed author/reviewer additions or different reviewer ownership
disable whole-block collapse.

Whitespace-only evidence is never wrapped because a macro around a blank line
would change paragraph topology. Text spans are split at immutable current
seams: blank-line separators, explicit `\par`, comments, heading command
boundaries, displays, floats, and lists. Equal provenance never merges separate
current blocks. No semantic parser, sentence alignment,
generic LaTeX AST, grapheme engine, or similarity graph is part of this design.

## 4. Structure, moves, and equations

Only the current manuscript executes headings, lists, floats, displays, labels,
tags, counters, and paragraph boundaries. Highlight markup cannot insert blank
lines, `\par`, vertical spacing, or parent structural commands. Heading color is
placed inside the visible title field rather than around the structural command.

Move handling is intentionally exact: a normalized current block that exists
unchanged in the parent may be treated as a pure move and left black. A moved
and rewritten block follows normal best-effort addition detection. There is no
fuzzy move analysis.

Inline math uses a safe addition span when available and may otherwise color the
whole current inline expression. A substantively changed display equation may
be colored as one current block. Its environment boundary, label, tag, number,
and cross-reference remain those of clean; no old equation is displayed and no
Math AST is required.

## 5. Citations and bibliography

Citation identity is the BibTeX key, never the rendered number. Every current
citation-family command uses the normal pure-blue link style, whether its key
set is unchanged, added, removed, or replaced and whether it lies inside a fine
or whole red/green block. Citation command ranges are protected blue islands
subtracted from revision highlight spans. Parent-only citation commands never
execute, so marked cannot introduce `[?]` through deleted citations.

The current bibliography is the sole visible authority for entries, order,
numbering, and content. Removed entries are absent; bibliography prose for every
retained, new, and same-key corrected entry remains black, while DOI/URL links
remain xcolor `ProcessBlue`. Citation provenance is preferred;
`\ReviewReference{ID}{key[,keys...]}` remains the explicit reviewer ownership
mechanism for reference audit and response locations, never bibliography color.
For a newly added key, citation ownership is canonical. `\ReviewReference` may
agree with it or union multiple reviewer IDs only when the reviewer comment
actually caused the reference addition or metadata correction. A response that
merely mentions or discusses a reference does not assign ownership. AUTHOR
versus REVIEWER is a hard `REFERENCE_PROVENANCE_CONFLICT` rather than two
silently different colors.

## 6. Reviewer locations and pure deletions

Locations are resolved using package-generated, TeX-native `lineno` start/end
labels emitted by the final marked source. Python parses only the package-owned
`sci:loc:` AUX namespace and never identifies line-number glyphs from PDF
geometry. Reviewer-red prose/math contributes through visible revision spans;
reviewer-owned citation or bibliography changes contribute through transparent,
layout-neutral reference-location spans. Author-owned references, unchanged
content, parent-only deletions, and number drift never contribute.

A review with only a current citation/reference change receives its real current
line range and is not treated as a pure deletion. `\ReviewReference` therefore
owns provenance and location tracking only; it has no visible-color role.

If a review has deletion provenance but no reviewer-red current addition, the
response must not invent a nearby line. Chinese output says
`修改位置：相关内容已删除，当前稿无对应高亮文本。`; English output says
`Location: The relevant text has been removed; no corresponding highlighted text remains in the revised manuscript.`
Use an empty `\review{ID}{}` marker in current source to retain explicit
deletion-only provenance without adding scientific content.

## 7. Acceptance

Source projection must prove that stripping highlight semantics reproduces the
exact current source projection. A deterministic topology fingerprint must also
prove identical paragraph separators and heading, display, float, table, and
list boundary sequences. PDF projection must prove identical current scientific
text. AUX state must prove identical section, equation, figure,
table, citation, bibliography, and label numbering. The audit records fine and
whole blocks, provenance spans, exact moves, equations, citations,
bibliography entries, pure-deletion reviews, paragraph counts, topology and
identity booleans, reference conflicts, and unresolved additions. All identity
booleans must be true, reference conflicts must be zero, and unresolved
additions must be zero before handoff. The audit remains under `tmp/run_*` and
is never published to revision `output/`.
