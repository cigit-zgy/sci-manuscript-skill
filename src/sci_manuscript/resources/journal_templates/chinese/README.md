# Chinese journal template resource

- Template name: `kxtbcas`
- Template type: original project-maintained Chinese manuscript class
- Designer: Guangyao Zhao
- Version: 2026/03/08, `CASAD-style journal template`
- Distribution: repository MIT License

`kxtbcas.cls` is an original project-maintained class designed by Guangyao Zhao
as a reusable Chinese scientific manuscript workflow. It is distributed under
the repository MIT License. It is not an official template supplied by every
Chinese journal; users must verify current target-journal requirements.

The bundled copy adapts private font roots for portable resource staging and
retains the class's system-font selection behavior. The accompanying workflow
adds the project-managed Chinese journal defaults for paragraph indentation,
hyperlink colors, and compressed numeric citations.

The class requires an XeLaTeX-compatible engine and Chinese fonts. Verify the
current journal instructions and the target build environment before use.

`kxtbcas-numeric.bst` is the bundled author-format layer for Scientific
Bulletin-style numeric references: family name first, given-name initials
without full stops, three authors followed by `et al.`, and no ISSN output. A
non-empty DOI is emitted exactly once at the end of an entry as `DOI: 10...`.
Standard DOI resolver prefixes are removed at rendering time without rewriting
the source `.bib`; entries without DOI receive no empty label. Journal
abbreviations still depend on correct exported bibliography metadata.
