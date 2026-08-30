#!/usr/bin/env bash
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
