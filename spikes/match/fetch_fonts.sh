#!/usr/bin/env bash
# Fetch and convert the two fonts the reference layout uses.
#
# Calibri is proprietary and cannot be redistributed. Carlito is a
# metric-compatible OFL clone, so substituting it preserves line breaks and
# measure. Fira Code (the name font) is OFL and used as-is.
#
# These fontsource builds are per-unicode-range SUBSETS -- fine for a demo,
# but the real package should vendor full upstream OFL releases so that
# glyph coverage does not silently fall back.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p fonts && rm -rf .fontwork && mkdir -p .fontwork

for p in fira-code carlito; do
  curl -sSL "https://registry.npmjs.org/@fontsource/$p/-/$p-5.3.0.tgz" -o ".fontwork/$p.tgz"
  mkdir -p ".fontwork/$p" && tar xzf ".fontwork/$p.tgz" -C ".fontwork/$p"
done
cp .fontwork/*/package/LICENSE fonts/ 2>/dev/null || true

uv run --with "fonttools[woff]" python - <<'PY'
from fontTools.ttLib import TTFont
import pathlib
out = pathlib.Path("fonts")
for dst, src in {
    "Carlito-Regular.ttf": ".fontwork/carlito/package/files/carlito-latin-400-normal.woff2",
    "Carlito-Bold.ttf": ".fontwork/carlito/package/files/carlito-latin-700-normal.woff2",
    "Carlito-Italic.ttf": ".fontwork/carlito/package/files/carlito-latin-400-italic.woff2",
    "FiraCode-SemiBold.ttf": ".fontwork/fira-code/package/files/fira-code-latin-600-normal.woff2",
}.items():
    f = TTFont(src); f.flavor = None; f.save(out / dst); print("wrote", out / dst)
PY
rm -rf .fontwork
