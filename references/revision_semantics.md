# Revision semantics

This document is the normative contract for marked manuscripts. The workflow is
defined as four independent layers. A project must not introduce local
exceptions to these rules.

## 1. Provenance layer

Let `P` be the flattened direct-parent TeX source and `C_raw` the flattened
current TeX source.

`\review{IDs}{body}` is an authorship/provenance annotation only. It is removed
before structural comparison, producing a provenance-free current source `C`
and a sidecar set of non-overlapping reviewer intervals

```text
R = {(start_i, end_i, reviewer_ids_i)}.
```

The wrapper never creates a visual change by itself. Therefore text that is
unchanged between `P` and `C` remains unmarked even when it lies inside a
reviewer interval. Nested scopes inherit parent IDs and union child IDs in
first-seen order. The sidecar is canonicalized to non-overlapping effective
segments, merging adjacent segments with identical ID tuples.

`\ReviewReference{ID}{key[,keys...]}` is declared in `responses.tex`. It links
real rendered bibliography changes to reviewer provenance and response
locations; it never controls bibliography color or modifies `.bib` data.

## 2. Structural-diff layer

Only provenance-free `P` and `C` are sent to adjacent `latexdiff`. Reviewer IDs
are deliberately absent from this stage.

The structural comparison uses these fixed rules:

- direct-parent comparison only;
- UTF-8 input;
- citation markup disabled;
- Chinese front-matter commands explicitly registered as text commands;
- mathematics compared with `--math-markup=WHOLE`.

Mathematics is atomic revision state. Any change inside an inline or display
formula marks the complete old formula as deleted and the complete current
formula as added; formula-internal fragments are never compared or refined.
Inline mathematics remains separated from prose decoration.

## 3. Refinement policy

A block replacement may be refined to character-level changes only when all of
the following are true:

```text
pure_prose(old, new)
AND max(len(old), len(new)) <= 2000
AND similarity(old, new) >= 0.70
```

Similarity is `difflib.SequenceMatcher(..., autojunk=False).ratio()`.
`pure_prose` rejects TeX-structural tokens (`\ { } $ % & # _ ^ ~`).

The decision is intentionally conservative:

- eligible similar prose is refined so unchanged characters remain ordinary;
- dissimilar prose remains one deletion plus one addition;
- long replacements remain atomic to bound runtime and avoid accidental
  character-level matches across unrelated passages;
- TeX-bearing replacements remain structural blocks.

The 0.70 threshold and 2000-character ceiling are part of the public revision
contract. Changing either requires tests, documentation, and a release note.

## 4. Semantic rendering layer

After structural differences are known, every actual addition interval is
mapped back to `C` and split at reviewer-provenance boundaries in `R`.
Rendering is mutually exclusive:

| Semantic state | Text rendering | Mathematics rendering |
| --- | --- | --- |
| Author addition | blue text | blue mathematics |
| Reviewer/editor-linked addition | red text | red mathematics |
| Deletion | light-gray strikeout | light-gray strikeout |
| Unchanged content | ordinary manuscript text | ordinary mathematics |

A changed span can never be both author-blue and reviewer-red. Reviewer
provenance applies only to added current text; deletions remain light gray regardless
of reviewer scope.

Chinese deletion strikeout uses a punctuation-continuous CJK decorator.
Reviewer and author additions use color only. Mathematics is never passed
through CJK/ulem text-decoration scanners. This preserves TeX grouping and
prevents marked output from creating layout boxes that do not exist in the clean
manuscript.

Changed labelled display equations bypass formula-internal diffing: the complete
old equation is rendered as one unnumbered light-gray deletion and the complete
current equation as one author-blue or reviewer-red numbered addition.
This preserves the current equation number and prevents structurally different
formula fragments from being interleaved or forced into one display box.

### Generated bibliography

The visible bibliography is part of the manuscript state. Each side of an
adjacent comparison is compiled independently from that round's manuscript
citations, effective BibTeX database, and publisher bibliography style. The
resulting `.bbl` is the formatting source of truth; raw `.bib` text is never
inserted into the marked manuscript or compared as visible prose.

Generated `\bibitem` boundaries use citation keys as hidden stable identity.
Entry bodies, not citation numbers or ordering, determine machine states:
`unchanged`, `modified`, `added`, or `deleted`. The marked bibliography renders
the current revision only, with current numbering, normal journal styling, and
normal link colors. Old entries and red/blue/gray bibliography revision styling
are forbidden.

For a modified or added key, `\ReviewReference` records the current rendered
entry's final marked line range. A deleted key is valid but has no current
location. An unchanged key yields a neutral warning and no location. A key
absent from both rendered states is a fatal provenance error that reports the
review ID, key, and absolute `responses.tex` path. Citation keys never reach the
rendered PDF.

## 5. Reviewer locations

Reviewer line locations are generated in a layout-equivalent compilation of
the final marked source. Invisible internal spans label actual reviewer-linked
additions and eligible current bibliography entries without changing rendering.
Body and bibliography ranges are sorted, deduplicated, and merged with the same
overlap and adjacency rules.

## 6. Fidelity and release invariants

Revision validation has two independent fidelity layers.

**Source fidelity** checks the generated marked TeX, both materialized historical
bibliographies, current-only marked entries, and unit-level refinement
operations. Old and new replacement content must remain represented by deletion,
addition, reviewer-addition, and unchanged spans without character loss.
Character-level refinement may interleave unchanged text with several diff
macros, so a complete old or new sentence is not required to remain one
contiguous source substring.

**Render fidelity** checks the compiled PDF. The current manuscript text must
compile, reviewer/author/deletion colors must be present in rendered pixels, and
marked rendering must introduce no layout overflow absent from the clean build.
PDF text extraction is useful for ordinary current text but is not a fidelity
oracle for deleted or character-refined text: strikeout, CJK
font handling, and interleaved diff macros can change extraction order without
changing the visible manuscript.

A revision implementation is acceptable only when all of the following pass:

1. unit tests for provenance extraction, refinement policy, bibliography
   identity/current numbering, and lossless old/new replacement representation;
2. formatting, linting, typing, package build, and wheel smoke tests;
3. real LaTeX integration tests with blue, red, and light-gray rendered pixels;
4. clean-versus-marked layout QA with zero marked-specific overflow;
5. a real manuscript E2E when a consuming manuscript repository is available.

Generated PDFs may differ in pagination from the parent because deleted content
is displayed, but the marked rendering itself must not introduce an overflow
absent from the clean current manuscript.
