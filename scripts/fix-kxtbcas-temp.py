from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Publisher-specific metadata rendering follows the renamed canonical key.
metadata_path = ROOT / "src" / "metadata.py"
metadata = metadata_path.read_text(encoding="utf-8")
metadata = metadata.replace(
    'elif metadata.publisher == "chinese":',
    'elif metadata.publisher == "kxtbcas":',
)
metadata_path.write_text(metadata, encoding="utf-8")

# Canonicalize remaining publisher-key comparisons in tests and fixtures.
for path in (ROOT / "tests").rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    text = text.replace('publisher == "chinese"', 'publisher == "kxtbcas"')
    text = text.replace('publisher != "chinese"', 'publisher != "kxtbcas"')
    text = text.replace('("chinese", "elsevier", "nature", "acs")', '("kxtbcas", "elsevier", "nature", "acs")')
    text = text.replace(
        '"sci_manuscript.compile.probe_cjk_environment",\n        lambda _engine, _telemetry=None:',
        '"sci_manuscript.compile.probe_kxtbcas_fonts",\n        lambda:',
    )
    path.write_text(text, encoding="utf-8")

# Existing on-disk projects that still contain publisher: chinese remain readable
# through normalize_publisher(); new examples and canonical resources use kxtbcas.
for base in (ROOT / "src" / "resources", ROOT / "evals", ROOT / "references"):
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml", ".json", ".md", ".tex"}:
            continue
        text = path.read_text(encoding="utf-8")
        text = text.replace("publisher: chinese", "publisher: kxtbcas")
        text = text.replace('"publisher": "chinese"', '"publisher": "kxtbcas"')
        text = text.replace("journal_templates/chinese", "journal_templates/kxtbcas")
        path.write_text(text, encoding="utf-8")

Path(__file__).unlink()
