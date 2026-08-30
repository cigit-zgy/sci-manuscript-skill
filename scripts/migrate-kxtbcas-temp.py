from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "src" / "resources" / "journal_templates"
OLD = RESOURCES / "chinese"
KXTB = RESOURCES / "kxtbcas"

if OLD.exists():
    if KXTB.exists():
        raise SystemExit("both chinese and kxtbcas publisher resources exist")
    OLD.rename(KXTB)
if not KXTB.is_dir():
    raise SystemExit("KXTB-CAS resource directory is missing")

# Exact class font contract, copied from the reference KXTB-CAS usage model.
cls_path = KXTB / "kxtbcas.cls"
cls = cls_path.read_text(encoding="utf-8")
font_block_start = cls.index("% Portable bundled default:")
font_api_start = cls.index(r"\newcommand{\kxtbsetfontroot}")
font_block = r'''% Template-local exact font contract. The font files are staged into
% ./fonts by this publisher resource; silent typeface substitution is forbidden.
\def\kxtb@latinfontpath{./fonts/}
\def\kxtb@cjkfontpath{./fonts/}
\def\kxtb@latinfont@upright{TimesNewRoman-Regular.ttf}
\def\kxtb@latinfont@bold{TimesNewRoman-Bold.ttf}
\def\kxtb@latinfont@italic{TimesNewRoman-Italic.ttf}
\def\kxtb@latinfont@bolditalic{TimesNewRoman-BoldItalic.ttf}
\def\kxtb@cjkfont@upright{SimSun.ttf}
\def\kxtb@cjkfont@bold{SimSun-Bold.ttf}
\def\kxtb@cjkfont@italic{SimSun.ttf}
\def\kxtb@mathfont{STIX Two Math}

'''
cls = cls[:font_block_start] + font_block + cls[font_api_start:]
latin_start = cls.index(r"\newcommand{\kxtb@applylatinfonts}")
math_start = cls.index(r"\newcommand{\kxtb@applymathfont}")
loaders = r'''\newcommand{\kxtb@applylatinfonts}{%
  \IfFileExists{\kxtb@latinfontpath\kxtb@latinfont@upright}{%
    \setmainfont[
      Path=\kxtb@latinfontpath,
      UprightFont=\kxtb@latinfont@upright,
      BoldFont=\kxtb@latinfont@bold,
      ItalicFont=\kxtb@latinfont@italic,
      BoldItalicFont=\kxtb@latinfont@bolditalic
    ]{\kxtb@latinfont@upright}%
    \setsansfont[
      Path=\kxtb@latinfontpath,
      UprightFont=\kxtb@latinfont@upright,
      BoldFont=\kxtb@latinfont@bold,
      ItalicFont=\kxtb@latinfont@italic,
      BoldItalicFont=\kxtb@latinfont@bolditalic
    ]{\kxtb@latinfont@upright}%
  }{%
    \ClassError{kxtbcas}{Required Times New Roman files are missing}{The KXTB-CAS publisher setup must stage the exact fonts before compilation.}%
  }%
}

\newcommand{\kxtb@applycjkfonts}{%
  \IfFileExists{\kxtb@cjkfontpath\kxtb@cjkfont@upright}{%
    \setCJKmainfont[
      Path=\kxtb@cjkfontpath,
      UprightFont=\kxtb@cjkfont@upright,
      BoldFont=\kxtb@cjkfont@bold,
      ItalicFont=\kxtb@cjkfont@italic
    ]{\kxtb@cjkfont@upright}%
    \setCJKsansfont[
      Path=\kxtb@cjkfontpath,
      UprightFont=\kxtb@cjkfont@upright,
      BoldFont=\kxtb@cjkfont@bold,
      ItalicFont=\kxtb@cjkfont@italic
    ]{\kxtb@cjkfont@upright}%
  }{%
    \ClassError{kxtbcas}{Required SimSun files are missing}{The KXTB-CAS publisher setup must stage the exact fonts before compilation.}%
  }%
}

'''
cls = cls[:latin_start] + loaders + cls[math_start:]
for forbidden in (
    "FandolSong",
    "FandolHei",
    "TeX Gyre Termes",
    "Songti SC",
    "STSong",
    "Heiti SC",
    "STHeiti",
):
    if forbidden in cls:
        raise SystemExit(f"fallback typeface remains in KXTB-CAS class: {forbidden}")
cls_path.write_text(cls, encoding="utf-8")

fonts = KXTB / "fonts"
fonts.mkdir(exist_ok=True)
(fonts / "README.md").write_text(
    "# KXTB-CAS fonts\n\n"
    "This directory belongs only to the KXTB-CAS publisher resource. Runtime staging copies legally installed Times New Roman and SimSun files here in the isolated build source. Font binaries are not redistributed with the package.\n\n"
    "Required filenames: `TimesNewRoman-Regular.ttf`, `TimesNewRoman-Bold.ttf`, `TimesNewRoman-Italic.ttf`, `TimesNewRoman-BoldItalic.ttf`, `SimSun.ttf`, and `SimSun-Bold.ttf`. Missing exact fonts are a build error; no substitute family is selected.\n",
    encoding="utf-8",
)

scripts = KXTB / "scripts"
scripts.mkdir(exist_ok=True)
(scripts / "setup-fonts.sh").write_text(
    r'''#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FONT_DIR="$ROOT/fonts"
mkdir -p "$FONT_DIR"

search_dirs=()
if [[ -n "${KXTBCAS_FONT_SOURCE_DIR:-}" ]]; then
  search_dirs+=("$KXTBCAS_FONT_SOURCE_DIR")
fi
search_dirs+=(
  "$HOME/Library/Fonts"
  "/Library/Fonts"
  "/System/Library/Fonts"
  "$HOME/.local/share/fonts"
  "/usr/local/share/fonts"
  "/usr/share/fonts"
  "/Applications/Microsoft Word.app/Contents/Resources/DFonts"
)

copy_required() {
  local target="$1"
  shift
  if [[ -s "$FONT_DIR/$target" ]]; then
    return
  fi
  local directory candidate found
  for directory in "${search_dirs[@]}"; do
    [[ -d "$directory" ]] || continue
    for candidate in "$@"; do
      found="$(find "$directory" -type f -iname "$candidate" -print -quit 2>/dev/null || true)"
      if [[ -n "$found" ]]; then
        cp "$found" "$FONT_DIR/$target"
        return
      fi
    done
  done
  echo "Missing required KXTB-CAS font: $target" >&2
  echo "Install the exact Times New Roman / SimSun files or set KXTBCAS_FONT_SOURCE_DIR." >&2
  exit 1
}

copy_required "TimesNewRoman-Regular.ttf" "TimesNewRoman-Regular.ttf" "Times New Roman.ttf" "times.ttf"
copy_required "TimesNewRoman-Bold.ttf" "TimesNewRoman-Bold.ttf" "Times New Roman Bold.ttf" "timesbd.ttf"
copy_required "TimesNewRoman-Italic.ttf" "TimesNewRoman-Italic.ttf" "Times New Roman Italic.ttf" "timesi.ttf"
copy_required "TimesNewRoman-BoldItalic.ttf" "TimesNewRoman-BoldItalic.ttf" "Times New Roman Bold Italic.ttf" "timesbi.ttf"
copy_required "SimSun.ttf" "SimSun.ttf" "simsun.ttf"
copy_required "SimSun-Bold.ttf" "SimSun-Bold.ttf" "SimSun Bold.ttf" "simsunb.ttf"
''',
    encoding="utf-8",
)

(KXTB / "README.md").write_text(
    "# KXTB-CAS / 科学通报\n\n"
    "This publisher resource follows the `structure-object-perspective` KXTB-CAS class contract. Latin text is Times New Roman; Chinese text is SimSun. The original display-family roles (`\\sffamily`) resolve to the same serif files, so title and section typography remain serif while the original bold/size/alignment rules are preserved.\n\n"
    "The resource owns its font resolution. During an isolated build, `scripts/setup-fonts.sh` copies legally installed exact font files into that build's local `fonts/` directory. No shared Fandol/TeX-Gyre fallback is used for KXTB-CAS, and missing exact fonts stop the build.\n",
    encoding="utf-8",
)

# Canonical publisher key with a legacy metadata alias for existing projects.
metadata_path = ROOT / "src" / "metadata.py"
metadata = metadata_path.read_text(encoding="utf-8")
metadata = metadata.replace(
    'PUBLISHERS = ("elsevier", "nature", "acs", "chinese", "custom")\n'
    'PUBLISHER_LANGUAGES = {\n'
    '    "chinese": "zh",\n',
    'PUBLISHERS = ("elsevier", "nature", "acs", "kxtbcas", "custom")\n'
    'PUBLISHER_ALIASES = {"chinese": "kxtbcas"}\n'
    'PUBLISHER_LANGUAGES = {\n'
    '    "kxtbcas": "zh",\n',
    1,
)
anchor = 'def validate_publisher_language(publisher: str, language: str) -> None:\n'
if 'def normalize_publisher(' not in metadata:
    metadata = metadata.replace(
        anchor,
        'def normalize_publisher(publisher: str) -> str:\n'
        '    """Return the canonical publisher resource key."""\n'
        '    normalized = publisher.strip().lower()\n'
        '    return PUBLISHER_ALIASES.get(normalized, normalized)\n\n\n'
        + anchor,
        1,
    )
metadata = metadata.replace(
    'def validate_publisher_language(publisher: str, language: str) -> None:\n'
    '    """Reject publisher and language combinations outside the release matrix."""\n'
    '    if publisher == "custom":\n',
    'def validate_publisher_language(publisher: str, language: str) -> None:\n'
    '    """Reject publisher and language combinations outside the release matrix."""\n'
    '    publisher = normalize_publisher(publisher)\n'
    '    if publisher == "custom":\n',
    1,
)
metadata = metadata.replace(
    '    publisher = _text(journal.get("publisher"), "journal.publisher").lower()\n',
    '    publisher = normalize_publisher(\n'
    '        _text(journal.get("publisher"), "journal.publisher")\n'
    '    )\n',
    1,
)
metadata = metadata.replace(
    'before="Packaged publisher resource key: chinese, elsevier, nature, or acs.",',
    'before="Packaged publisher resource key: kxtbcas, elsevier, nature, or acs.",',
)
metadata_path.write_text(metadata, encoding="utf-8")

compile_path = ROOT / "src" / "compile.py"
compile_text = compile_path.read_text(encoding="utf-8")
compile_text = compile_text.replace('config.metadata.publisher != "chinese"', 'config.metadata.publisher != "kxtbcas"')
compile_text = compile_text.replace('config.metadata.publisher == "chinese"', 'config.metadata.publisher == "kxtbcas"')

probe_anchor = '\ndef probe_cjk_environment(\n'
if 'def stage_kxtbcas_fonts(' not in compile_text:
    helper = '''\nKXTBCAS_FONT_FILES = (\n    "TimesNewRoman-Regular.ttf",\n    "TimesNewRoman-Bold.ttf",\n    "TimesNewRoman-Italic.ttf",\n    "TimesNewRoman-BoldItalic.ttf",\n    "SimSun.ttf",\n    "SimSun-Bold.ttf",\n)\n\n\ndef stage_kxtbcas_fonts(target: Path) -> tuple[Path, ...]:\n    """Stage exact KXTB-CAS fonts into one isolated build source."""\n    target.mkdir(parents=True, exist_ok=True)\n    script = target / "scripts" / "setup-fonts.sh"\n    if not script.is_file():\n        source = (\n            resources_root()\n            / "journal_templates"\n            / "kxtbcas"\n            / "scripts"\n            / "setup-fonts.sh"\n        )\n        script.parent.mkdir(parents=True, exist_ok=True)\n        shutil.copy2(source, script)\n    result = subprocess.run(\n        ["bash", str(script)],\n        cwd=target,\n        text=True,\n        stdout=subprocess.PIPE,\n        stderr=subprocess.PIPE,\n        check=False,\n    )\n    if result.returncode != 0:\n        details = "\\n".join(\n            part.strip() for part in (result.stdout, result.stderr) if part.strip()\n        )\n        raise WorkflowError(\n            "KXTB-CAS exact font staging failed. "\n            "Times New Roman and SimSun are required.\\n" + details\n        )\n    staged = tuple(target / "fonts" / name for name in KXTBCAS_FONT_FILES)\n    missing = tuple(path.name for path in staged if not path.is_file())\n    if missing:\n        raise WorkflowError(\n            "KXTB-CAS font staging did not produce: " + ", ".join(missing)\n        )\n    return staged\n\n\ndef probe_kxtbcas_fonts() -> CjkProbeResult:\n    """Check exact KXTB-CAS font availability without modifying user files."""\n    with tempfile.TemporaryDirectory(prefix="sci-manuscript-kxtbcas-fonts-") as temporary:\n        try:\n            staged = stage_kxtbcas_fonts(Path(temporary))\n        except WorkflowError as exc:\n            return CjkProbeResult(False, str(exc))\n    names = ", ".join(path.name for path in staged)\n    return CjkProbeResult(True, f"Exact KXTB-CAS fonts resolved: {names}")\n\n'''
    compile_text = compile_text.replace(probe_anchor, helper + probe_anchor, 1)

old_stage = '''    if config.language == "zh" or config.metadata.publisher == "kxtbcas":\n        stage_cjk_fonts(target)\n'''
new_stage = '''    if config.language == "zh" and config.metadata.publisher != "kxtbcas":\n        stage_cjk_fonts(target)\n'''
compile_text = compile_text.replace(old_stage, new_stage, 1)
copy_anchor = '''    for resource in publisher_resource(config).iterdir():\n        destination = target / resource.name\n        if resource.is_dir():\n            shutil.copytree(resource, destination, dirs_exist_ok=True)\n        else:\n            shutil.copy2(resource, destination)\n'''
if 'stage_kxtbcas_fonts(target)' not in compile_text[compile_text.index('def stage_runtime_resources'):]:
    compile_text = compile_text.replace(
        copy_anchor,
        copy_anchor
        + '    if config.metadata.publisher == "kxtbcas":\n'
        + '        stage_kxtbcas_fonts(target)\n',
        1,
    )
ensure_old = '''    result = probe_cjk_environment(engine or config.engine, telemetry)\n    if not result.ready:\n        raise WorkflowError(f"Chinese environment is blocked: {result.detail}")\n'''
ensure_new = '''    result = (\n        probe_kxtbcas_fonts()\n        if config.metadata.publisher == "kxtbcas"\n        else probe_cjk_environment(engine or config.engine, telemetry)\n    )\n    if not result.ready:\n        raise WorkflowError(f"Chinese environment is blocked: {result.detail}")\n'''
compile_text = compile_text.replace(ensure_old, ensure_new, 1)
compile_path.write_text(compile_text, encoding="utf-8")

api_path = ROOT / "src" / "api.py"
api = api_path.read_text(encoding="utf-8")
api = api.replace(
    '    probe_cjk_environment,\n',
    '    probe_cjk_environment,\n    probe_kxtbcas_fonts,\n',
    1,
)
api = api.replace(
    '    SubmissionSettings,\n    validate_publisher_language,\n',
    '    SubmissionSettings,\n    normalize_publisher,\n    validate_publisher_language,\n',
    1,
)
api = api.replace('publisher == "chinese"', 'publisher == "kxtbcas"')
api = api.replace(
    '    if engine not in SUPPORTED_ENGINES:\n',
    '    if publisher is not None:\n'
    '        publisher = normalize_publisher(publisher)\n'
    '    if engine not in SUPPORTED_ENGINES:\n',
    1,
)
old_probe = '''    if language == "zh" or publisher == "kxtbcas":\n        cjk = (\n            probe_cjk_environment(selected)\n            if selected is not None\n            else CjkProbeResult(False, engine_error)\n        )\n        checks = (\n            *checks,\n            DoctorCheck("CJK compilation probe", cjk.ready, cjk.detail, True),\n        )\n'''
new_probe = '''    if language == "zh" or publisher == "kxtbcas":\n        cjk = (\n            probe_kxtbcas_fonts()\n            if publisher == "kxtbcas"\n            else (\n                probe_cjk_environment(selected)\n                if selected is not None\n                else CjkProbeResult(False, engine_error)\n            )\n        )\n        label = (\n            "KXTB-CAS exact fonts"\n            if publisher == "kxtbcas"\n            else "CJK compilation probe"\n        )\n        checks = (*checks, DoctorCheck(label, cjk.ready, cjk.detail, True))\n'''
api = api.replace(old_probe, new_probe, 1)
api = api.replace(
    '    if publisher not in PUBLISHERS:\n        raise WorkflowError(f"Unsupported publisher: {publisher}")\n',
    '    publisher = normalize_publisher(publisher)\n'
    '    if publisher not in PUBLISHERS:\n'
    '        raise WorkflowError(f"Unsupported publisher: {publisher}")\n',
    1,
)
api_path.write_text(api, encoding="utf-8")

# Canonicalize configuration examples and tests without rewriting natural-language "Chinese".
for base in (ROOT / "tests", ROOT / "evals", ROOT / "references"):
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".tex"}:
            continue
        value = path.read_text(encoding="utf-8")
        value = value.replace('publisher="chinese"', 'publisher="kxtbcas"')
        value = value.replace("publisher='chinese'", "publisher='kxtbcas'")
        value = value.replace('"publisher": "chinese"', '"publisher": "kxtbcas"')
        value = value.replace("'publisher': 'chinese'", "'publisher': 'kxtbcas'")
        value = value.replace("publisher: chinese", "publisher: kxtbcas")
        value = value.replace("journal_templates/chinese", "journal_templates/kxtbcas")
        path.write_text(value, encoding="utf-8")

for path in (ROOT / "README.md", ROOT / "SKILL.md"):
    if not path.is_file():
        continue
    value = path.read_text(encoding="utf-8")
    value = value.replace("publisher: chinese", "publisher: kxtbcas")
    value = value.replace("journal_templates/chinese", "journal_templates/kxtbcas")
    value = value.replace("publisher='chinese'", "publisher='kxtbcas'")
    value = value.replace('publisher="chinese"', 'publisher="kxtbcas"')
    path.write_text(value, encoding="utf-8")

# Package contract: canonical resource exists and generic legacy folder is gone.
if OLD.exists():
    raise SystemExit("legacy chinese resource directory remains")
for required in (
    "TimesNewRoman-Regular.ttf",
    "TimesNewRoman-Bold.ttf",
    "TimesNewRoman-Italic.ttf",
    "TimesNewRoman-BoldItalic.ttf",
    "SimSun.ttf",
    "SimSun-Bold.ttf",
    "./fonts/",
):
    if required not in cls_path.read_text(encoding="utf-8"):
        raise SystemExit(f"missing KXTB-CAS font contract: {required}")

Path(__file__).unlink()
