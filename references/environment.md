# Environment inspection and recovery

Read this reference only when `doctor`, publisher tests, or compilation reports
a missing or incompatible dependency. All inspection commands are read-only.
Never install, upgrade, activate, or modify an environment before the user
confirms the exact target environment and installation method.

## Required runtime

| Category | Accepted dependency |
| --- | --- |
| Python | Python 3.11 or newer |
| YAML | PyYAML 6.x and ruamel.yaml 0.18.x |
| LaTeX | Tectonic (primary) or the traditional `latexmk` driver |
| Revisions | `latexdiff` |
| CJK environment probe | Poppler `pdftotext` |
| Optional presentation QA | Poppler render/font tools when explicitly used |
| Bibliography | Tectonic-integrated BibTeX, external BibTeX, or Biber |
| Response typography | a TeX-usable installed serif from the platform policy |

Chinese publisher projects additionally require XeLaTeX-compatible
compilation and usable Chinese fonts. Ruff, Mypy, Zotero, and Better BibTeX are
optional and must not block manuscript use.

## Read-only diagnosis

Identify the intended Python before running workflow imports:

```bash
python3 --version
command -v python3
command -v tectonic latexmk xelatex pdflatex
command -v latexdiff pdftotext bibtex biber
```

Then run the installed command:

```bash
sci-manuscript doctor
sci-manuscript doctor --language zh
```

`doctor` reports `READY` and exits 0 only when every required category is
available. It reports `BLOCKED` and exits 2 when at least one is missing. The
diagnostic remains usable when PyYAML is absent, so a missing YAML package is
reported normally rather than as an import traceback.

The target-aware Chinese check compiles a minimal `xeCJK` document with the
selected engine, extracts that isolated probe's PDF text, and verifies non-empty
Chinese glyphs. This is an environment capability probe, not manuscript,
revision, or response correctness validation. Normal marked/response builds do
not reverse-parse final PDFs.
It reports `BLOCKED` on a compile, package, engine, extraction, or glyph failure;
it never installs or silently switches toolchains.

Response compilation independently probes font candidates with the selected
correspondence TeX engine. The fixed policies are:

- macOS Latin: Times New Roman, Times, TeX Gyre Termes; CJK: Songti SC,
  STSong, Noto Serif CJK SC;
- Windows Latin: Times New Roman, Cambria, Georgia; CJK: SimSun, NSimSun,
  Noto Serif CJK SC;
- Linux Latin: Times New Roman, TeX Gyre Termes, Liberation Serif, Nimbus
  Roman; CJK: Noto Serif CJK SC, Source Han Serif SC, FandolSong.

The first TeX-usable family is selected and recorded in the run audit. If every
candidate fails, `RESPONSE_LATIN_FONT_UNAVAILABLE` or
`RESPONSE_CJK_FONT_UNAVAILABLE` reports the platform and attempted families.
Fonts remain host-installed or temporarily staged from an existing host TeX
installation; no font binary is distributed by the package.

macOS font resolution and embedded-font output are integration-verified on the
real release environment. Windows and Linux candidate ordering and resolver
logic are covered at the logic-test level; actual availability remains a host
property and must be confirmed on the target machine. This boundary does not
justify a new Windows/Linux LaTeX CI matrix without a reproducible host issue.

If the selected interpreter is older than Python 3.11, do not alter the system
Python. Ask which Conda environment or virtual environment should be used.

## Approval boundary

When required dependencies are missing:

1. show the complete `doctor` result;
2. identify the selected Python/Conda environment and package manager;
3. ask whether the user wants commands only or wants the agent to install into
   that environment;
4. wait for explicit approval;
5. apply only the approved change and rerun `doctor`.

If the user declines, stop without initializing a manuscript project. Never
interpret a request to create a paper as permission to modify Homebrew, Conda,
system Python, TeX Live, Zotero, or editor settings.

## Installation examples after approval

For a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "PyYAML>=6,<7"
```

For an existing Conda environment selected by the user:

```bash
conda install -n <environment> "python>=3.11" "pyyaml>=6,<7"
```

For the primary release-tested macOS toolchain, include Poppler when the CJK
probe or optional presentation tools are required:

```bash
brew install tectonic latexdiff poppler
```

Package names and availability differ by operating system and distribution;
verify the local package manager rather than copying an unverified command.
After any approved installation, activate the chosen Python environment and
rerun `doctor`.

## Compiler policy

`doctor --engine tectonic` checks Tectonic and its integrated bibliography
workflow. `doctor --engine latex` checks `latexmk`, the language-appropriate
driver, and BibTeX/Biber. `doctor --engine auto` applies exactly the runtime
resolution order: use Tectonic when present, otherwise use the traditional
driver. It never silently changes an explicitly selected engine.

Tectonic is the primary release-gated engine. The traditional driver is a
supported recovery/deployment path when a suitable TeX distribution is already
installed, but it does not have the same cross-platform release evidence.
Chinese uses XeLaTeX. English uses pdfLaTeX unless its source requires XeLaTeX.

The scientific preamble uses packages for mathematics, chemistry, units,
tables, figures, algorithms, publisher references, engine detection, and
conditional CJK support. Tectonic obtains compatible packages through its
bundle.

The bundled Chinese class uses system font fallbacks when project-local font
files are absent. Tectonic may report absolute system-font access as a
reproducibility warning. A successful build requires source/TeX-state
validation. Rendered-page inspection is separate presentation QA when the
handoff makes a visual-layout claim; manuscript PDF text extraction is not a
scientific correctness gate.
