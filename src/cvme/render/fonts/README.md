# Vendored fonts

Bundled so that output is byte-identical on every machine. `cvme` renders with
`ignore_system_fonts=True`, so whatever is installed locally cannot change the
result.

| File | Family | Licence | Why |
|---|---|---|---|
| `Carlito-{Regular,Bold,Italic}.ttf` | Carlito | OFL 1.1 | Metric-compatible substitute for Calibri, which is proprietary to Microsoft and cannot be redistributed. Substituting it preserves measure and line breaking. |
| `FiraCode-SemiBold.ttf` | Fira Code | OFL 1.1 | Display face for the name. |

Regenerate with `scripts/fetch_fonts.py`. These are converted from the
`@fontsource` webfont builds, which are per-unicode-range **subsets** covering
Latin and Latin Extended. That is enough for the documents cvme targets; if you
need wider coverage, swap in the full upstream OFL releases — the file names are
all that the loader cares about.
