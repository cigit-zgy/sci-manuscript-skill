# Canonical manuscript regions

This document is the normative, publisher-independent structure and relation
contract used by revision highlighting. It defines identities and safe source
boundaries. It is not a general TeX AST, a semantic parser, or a publisher
visual-style specification.

## 1. Projection invariant

A projection is an ordered set of exact source intervals over one flattened
manuscript. It never rewrites source, executes macro expansion, or treats a
source filename as document identity. Unsupported syntax cannot merge adjacent
structures: it remains `UNKNOWN_REGION` when its boundaries are safe, or fails
with `REGION_CLASSIFICATION_AMBIGUOUS` when they are not.

## 2. Manuscript hierarchy

The hierarchy has five layers with non-overlapping responsibilities.

### L0 — Document

The complete current manuscript document. L0 establishes the single current
layout and structure authority.

### L1 — Structural containers

- frontmatter;
- mainmatter and H1 sections;
- H2 subsections;
- H3/H4+ nested sections;
- backmatter and bibliography;
- a secondary-language summary where the publisher supports one.

L0/L1 determine structural context and ancestry. They scope matching but are
not themselves the normal visual highlight unit.

### L2 — Structural blocks

- paragraph and heading;
- display equation;
- figure and table;
- list;
- figure/table caption;
- funding and keywords;
- frontmatter fields, footnotes, backmatter statements, and bibliography
  entries.

L2 determines block type, hard source seams, owner container, and the matching
domain. A block cannot match across an incompatible L1 path or L2 owner.

### L3 — Revision units

- prose sentence and long-prose clause;
- whole visible heading title;
- whole equation body;
- table row and table cell;
- list item, or sentence/clause within a long item;
- caption sentence/clause;
- grant item;
- keyword item.

L3 is the smallest natural unit that may be classified as changed and visually
highlighted. Character, word, and short-phrase islands are not revision units.

### L4 — Protected inline units

- citation;
- DOI and URL;
- cross-reference;
- inline math;
- a TeX atomic construct whose syntax cannot be split safely.

L4 preserves atomic source syntax and inline semantics. Citation, DOI, URL, and
link-styled cross-reference islands retain native xcolor `blue` even inside a
RubineRed or ForestGreen L3 unit. Inline math and other TeX atoms follow the
enclosing unit presentation but never receive an internal fine diff.

Structure, matching, identity, provenance, presentation, and location are
therefore separate concerns. Neither L2/L3 classification nor L4 protection
assigns change ownership.

## 3. Structural path and order

`structural_path` describes rendered hierarchy rather than files. A main-text
paragraph may have a path such as:

```text
("mainmatter", "heading_h1:3", "heading_h2:2")
```

Changing `sections/a.tex` to `sections/b.tex` without changing the flattened
hierarchy does not change this path. Moving a paragraph from subsection 3.3 to
subsection 3.2 does.

Sibling `ordinal` records logical sequence within one parent path. It supports
move/reorder decisions and local disambiguation but is never content identity
by itself. Generated section, equation, figure, table, citation, and
bibliography numbers do not participate in identity.

## 4. Relation vocabulary

The manuscript/revision model uses only these relations:

| Relation | Meaning | Consumer |
| --- | --- | --- |
| `contains` | One L0/L1/L2 object is the structural parent or container of another. | ancestry and matching scope |
| `ordered-before` | Two siblings under the same parent have a logical sequence. | move/reorder and duplicate disambiguation |
| `matches` | A parent/current pair is a candidate correspondence inside a compatible scope. | revision comparison |
| `identical-to` | The region-specific normalized identity is equal. | unchanged hard veto |
| `owned-by` | A changed L3 unit has `AUTHOR` or `REVIEWER(ID/IDs)` provenance. | red/green presentation and response audit |
| `references` | A citation, cross-reference, DOI, or URL points to a scientific/document object. | protected reference semantics |

`depends-on` is reserved for the build/artifact DAG. It must not describe
manuscript containment, ancestry, correspondence, identity, or provenance.

## 5. Canonical region contract table

Normalization removes comments and TeX-ignored source whitespace only. It
does not erase commands, identifiers, numbers, math operators, grouping,
superscripts, subscripts, arguments, or visible text-command whitespace.

| Region | Parent scope | Identity | Revision unit | Move rule | Protected content | Presentation |
| --- | --- | --- | --- | --- | --- | --- |
| Heading | strict ancestor section path | level + normalized visible title + strict ancestor path + sibling context | whole visible title | ancestry change is structural | TeX atoms in title | whole RubineRed/ForestGreen only when changed |
| Paragraph | owning section/block | normalized natural-unit content + strict local context | sentence; long-sentence clause | compatible source-file/local relocation may stay black; hierarchy/order change is structural | all L4 units | coarse unit RubineRed/ForestGreen; unchanged black |
| Display equation | owning section/block | normalized mathematical body | whole mathematical body | identical body stays black after same-section move, cross-subsection move, file relocation, or sequence change | labels/tags and TeX math atoms | whole RubineRed/ForestGreen only for substantive body change |
| Figure | owning section | asset digest + owning figure context | structural event; caption is separate | asset/context change is structural | asset bytes | pixels never tinted; audit/provenance/location only |
| Caption | owning figure/table identity | normalized text + owner identity | sentence; long-sentence clause | never matches across owners | all L4 units | changed natural units red/green; unchanged black |
| Table | owning section | owning table context/label | row or cell | table-context change is structural | nested TeX/table constructs | presentation delegated to row/cell |
| Table row | owning table | normalized row content + local order/context | whole row | added/reordered row is structural | cells and TeX atoms | whole current row red/green when added/reordered |
| Table cell | owning table + row | row/column/spanning context + normalized cell content | whole cell | merged/span change selects the whole current merged cell | TeX atoms and links | whole changed cell red/green |
| List | owning section/block | list owner + local structural context | item | no cross-owner matching | nested items and TeX atoms | presentation delegated to item |
| List item | owning list | normalized item + local list context/order | whole short item; sentence/clause in a long item | move/reorder is local to the same owner | all L4 units | coarse current item unit red/green |
| Funding | frontmatter/backmatter funding field | normalized grant item; a shared label/wrapper is not part of each grant identity | grant item | only the affected grant changes | TeX atoms and links | affected grant red/green; others black |
| Keyword | frontmatter keyword field | normalized keyword item | keyword item | order/context is local to the field | TeX atoms | affected keyword red/green; others black |
| Bibliography entry | bibliography | BibTeX key | no visual revision unit | current bibliography owns order | DOI/URL | prose black; audit/provenance only |
| Citation | enclosing L3 unit | BibTeX key set | protected inline unit | rendered number never defines identity | complete citation command | native xcolor `blue` |
| DOI/URL | enclosing L3 unit or bibliography entry | normalized DOI/URL | protected inline unit | relocation follows the enclosing object | complete link token/command | native xcolor `blue` |
| Cross-reference | enclosing L3 unit | label key | protected inline unit | rendered number never defines identity | complete reference command | preserve link styling; native `blue` when link-styled |

The principal identity rules are hard contracts:

- a display equation is identified by normalized mathematical body, never by
  label, environment, ancestry, or rendered number;
- a citation is identified by BibTeX key, a DOI by normalized DOI, and a URL by
  normalized URL;
- a caption cannot match outside its owning figure/table;
- duplicate paragraph, row, cell, and item candidates require ancestry, owner,
  logical order, and local sibling evidence before any pairing is accepted.

## 6. Identity proof order

Segmentation cannot create change. Every revision-capable region is evaluated
in this order:

1. **Whole block identity.** A normalized-identical paragraph/block is entirely
   `UNCHANGED`; emit identity certificates for its current natural units and
   stop. Sentence or clause matching cannot override this veto.
2. **Whole sentence identity.** Only a changed prose block proceeds to sentence
   comparison. An exact or normalized-identical sentence is `UNCHANGED` and
   stops before clause segmentation.
3. **Long-sentence clause identity.** Only a sentence already proved different
   and above the language threshold may be segmented. Identical clauses remain
   black; the remaining clause units require positive change/addition proof.
4. **Substructural identity.** Equations, table rows/cells, list items, captions,
   grant items, and keyword items use their own identity from the master table.

Exact source identity and normalized scientific identity are distinct proof
kinds. Normalization may remove comments, insignificant line wrapping, and
layout-only whitespace (including CJK source line breaks around protected
links/punctuation). It cannot remove words, identifiers, numbers, operators,
citation keys, math commands, or semantic punctuation.

## 7. Hard seams and prose granularity

Final visual spans cannot cross these source boundaries:

- frontmatter field;
- paragraph separator or explicit `\par`;
- heading command boundary;
- display environment;
- figure or table environment;
- list and list-item boundary;
- bibliography entry;
- a preserved source comment that owns a newline.

Ordinary prose is deliberately segmented into coarse readable units. These
thresholds are implementation policy, not project metadata knobs:

| Language | Whole-sentence limit | Long-sentence clause minimum | Maximum units per sentence |
| --- | --- | --- | --- |
| Chinese | `sentence_max_atoms = 50` | `clause_min_atoms = 15` | `max_units_per_sentence = 3` |
| English | `sentence_max_words = 30` | `clause_min_words = 10` | `max_units_per_sentence = 3` |

Chinese strong boundaries are `。！？；`; English strong boundaries are
`. ! ? ;`. Only sentences beyond the applicable limit may split at conservative
Chinese `，：` or English `, :` boundaries. Undersized clauses merge
deterministically with an adjacent clause, and remaining groups merge to at
most three units. TeX commands, citations, references, inline math, DOI values,
URLs, decimals, and English abbreviations are protected from false boundaries.

## 8. Canonical publisher mapping

Chinese, Elsevier, Nature, and ACS templates map their TeX shapes into this one
model. Publisher adapters only recognize equivalent field/environment
spellings. Section names such as Introduction, Methods, Results, Discussion,
and Conclusions are H1 title content, never region types or highlighter
selectors.

The minimum recognized syntax is:

- `\title`, `\entitle`, author/affiliation/note/funding fields;
- abstract, secondary-abstract, and keyword fields/environments;
- `\section`, `\subsection`, `\subsubsection`, `\paragraph`;
- prose paragraphs and footnotes;
- `equation` and `equation*` displays;
- figures, captions, and declared image assets;
- tables, captions, rows, cells, `\multirow`, and `\multicolumn`;
- itemize/enumerate lists and `\item`;
- citation-family, cross-reference, URL, DOI, and href commands;
- bibliography boundary and materialized `\bibitem` entries;
- Chinese secondary-summary fields.

The projector is a conservative TeX scanner, not a generic AST. Complex
`align`, `gather`, `multline`, and `displaymath` location support remains
outside this contract and retains the existing fail-closed boundary.

## 9. Classification and matching failure

When classification cannot preserve a hard seam, fail with:

```text
REGION_CLASSIFICATION_AMBIGUOUS
file: <path>
line: <line>
region context: <path or UNKNOWN_REGION>
nearby TeX: <bounded source excerpt>
```

Unknown content may remain unhighlighted only when its boundaries are known
and no changed evidence is silently discarded. Projection never guesses across
an ambiguous structural boundary.

Duplicate matching follows `contains`, `ordered-before`, and strict owner/path
context. If multiple normalized-identical candidates still cannot be uniquely
disambiguated, the matcher must never guess: the unit is `AMBIGUOUS` and the
build fails closed. `AMBIGUOUS` never authorizes red/green presentation. Wrong
sibling or owner pairing is never a silent fallback.
