# Environment inspection and recovery

Read this reference only when `doctor`, publisher tests, or compilation reports
a missing or incompatible dependency. All inspection commands are read-only.
Never install, upgrade, activate, or modify an environment before the user
confirms the exact target environment and installation method.

## Required runtime

| Category | Accepted dependency |
| --- | --- |
| Python | Python 3.11 or newer |
| YAML | PyYAML 6.x |
| LaTeX | Tectonic, or `latexmk` with pdfLaTeX/XeLaTeX |
| Revisions | `latexdiff` |
| PDF QA | Poppler `pdftotext` and `pdftoppm` |
| Bibliography | Tectonic-integrated BibTeX, external BibTeX, or Biber |

Chinese publisher projects additionally require XeLaTeX-compatible
compilation and usable Chinese fonts. Ruff, Mypy, Zotero, and Better BibTeX are
optional and must not block manuscript use.

## Read-only diagnosis

Identify the intended Python before running workflow imports:

```bash
python3 --version
command -v python3
command -v tectonic latexmk pdflatex xelatex
command -v latexdiff pdftotext pdftoppm bibtex biber
```

Then run from the skill source or an initialized project:

```bash
python3 scripts/run.py doctor
python run.py doctor
```

`doctor` reports `READY` and exits 0 only when every required category is
available. It reports `BLOCKED` and exits 2 when at least one is missing. The
diagnostic remains usable when PyYAML is absent, so a missing YAML package is
reported normally rather than as an import traceback.

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

For the compact supported macOS toolchain:

```bash
brew install tectonic latexdiff poppler
```

TeX Live is an alternative, not a simultaneous requirement. Package names and
availability differ by operating system and distribution; verify the local
package manager rather than copying an unverified command. After any approved
installation, activate the chosen Python environment and rerun `doctor`.

## Compiler policy

`auto` uses Tectonic when available and otherwise uses the supported
`latexmk` toolchain. Pass `--engine tectonic` or `--engine latex` only for an
explicit reproducibility or diagnostic requirement. Traditional Chinese builds
require XeLaTeX.

The scientific preamble uses packages for mathematics, chemistry, units,
tables, figures, algorithms, publisher references, engine detection, and
conditional CJK support. Tectonic obtains compatible packages through its
bundle; traditional LaTeX environments must provide them locally.

The bundled Chinese class uses system font fallbacks when project-local font
files are absent. Tectonic may report absolute system-font access as a
reproducibility warning. A successful build still requires PDF text extraction
and rendered-page inspection before handoff.
