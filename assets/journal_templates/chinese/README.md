# Chinese journal template resource

- Template name: `kxtbcas`
- Template type: user-provided Chinese journal LaTeX workflow resource
- Source URL: not provided
- Source file: maintainer-provided `kxtbcas.cls` from a Chinese journal
  manuscript workspace
- Download date: not downloaded; copied locally on 2026-08-20
- Version: 2026/03/08, `CASAD-style journal template`
- Distribution: the supplied source class contained no embedded license notice
  or public source URL; the repository maintainer explicitly confirmed that the
  maintainer-provided template may be distributed publicly with v3.0.0

This resource provides a reusable starting point for Chinese journal projects.
Its current class implementation is `kxtbcas.cls`; it is not a universal or
official template for every Chinese journal. It was added at the user's
direction for reuse in future Chinese-journal projects.

The bundled copy changes only the two default private macOS font roots to `./`.
The class then uses its existing system font fallback logic when local font
files are absent. The source file remains unchanged.

The repository maintainer directed inclusion of this resource and confirmed
its public distribution with this project for the v3.0.0 release. See
`THIRD_PARTY_NOTICES.md` at the repository root.

The class requires an XeLaTeX-compatible engine and Chinese fonts. Verify the
current journal instructions and the target build environment before use.
