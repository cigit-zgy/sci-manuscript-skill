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
reviewer interval. Nested reviewer scopes are invalid; multiple reviewer IDs
belong in one wrapper.

Legacy `\user{...}` remains transparent and does not create reviewer provenance.

## 2. Structural-diff layer

Only provenance-free `P` and `C` are sent to adjacent `latexdiff`. Reviewer IDs
are deliberately absent from this stage.

The structural comparison uses these fixed rules:

- direct-parent comparison only;
- UTF-8 input;
- citation markup disabled;
- Chinese front-matter commands explicitly registered as text commands;
- display mathematics compared with `--math-markup=WHOLE`.

`WHOLE` is a semantic policy, not a project-specific workaround. A display
formula is a structured mathematical object whose internal TeX grouping should
not be rewritten by diff commands. If a display formula changes, its old and
new formula blocks are treated atomically. Inline mathematics remains embedded
in surrounding prose but is separated from text-decoration rendering later.

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
| Author addition | blue wave underline | blue content |
| Reviewer/editor-linked addition | green straight underline | green content |
| Deletion | red strikeout | red content |
| Unchanged content | ordinary manuscript text | ordinary mathematics |

A changed span can never be both author-blue and reviewer-green. Reviewer
provenance applies only to added current text; deletions remain red regardless
of reviewer scope.

Chinese text decorations use punctuation-continuous CJK decorators. Mathematics
is never passed through CJK/ulem line-decoration scanners. This preserves TeX
grouping and prevents marked output from creating layout boxes that do not exist
in the clean manuscript.

## 5. Reviewer locations

Reviewer line locations are generated in a separate transparent compilation of
the current source. This compilation uses reviewer intervals only for line
labels and never for colors. Consequently response-letter location generation
cannot change marked-manuscript rendering.

## 6. Fidelity and release invariants

Revision validation has two independent fidelity layers.

**Source fidelity** checks the generated marked TeX and unit-level refinement
operations. Old and new replacement content must remain represented by deletion,
addition, reviewer-addition, and unchanged spans without character loss.
Character-level refinement may interleave unchanged text with several diff
macros, so a complete old or new sentence is not required to remain one
contiguous source substring.

**Render fidelity** checks the compiled PDF. The current manuscript text must
compile, reviewer/author/deletion colors must be present in rendered pixels, and
marked rendering must introduce no layout overflow absent from the clean build.
PDF text extraction is useful for ordinary current text but is not a fidelity
oracle for deleted or character-refined text: strikeout, wave underline, CJK
font handling, and interleaved diff macros can change extraction order without
changing the visible manuscript.

A revision implementation is acceptable only when all of the following pass:

1. unit tests for provenance extraction, refinement policy, and lossless
   old/new replacement representation;
2. formatting, linting, typing, package build, and wheel smoke tests;
3. real LaTeX integration tests with blue, green, and red rendered pixels;
4. clean-versus-marked layout QA with zero marked-specific overflow;
5. a real manuscript E2E when a consuming manuscript repository is available.

Generated PDFs may differ in pagination from the parent because deleted content
is displayed, but the marked rendering itself must not introduce an overflow
absent from the clean current manuscript.
