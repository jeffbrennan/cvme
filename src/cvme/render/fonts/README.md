# Vendored fonts

Bundled so that output is byte-identical on every machine. `cvme` renders with
`ignore_system_fonts=True`, so whatever is installed locally cannot change the
result.

Each body family is vendored in three faces — Regular, SemiBold and Italic —
and named so that Typst sees one family holding all three. SemiBold rather than
Bold is deliberate: a resume spends bold on every role, every date and every
skill label, and at 700 that reads as shouting. Typst resolves `weight: "bold"`
to the nearest weight a family ships, so `**bold**` lands on the 600 face.

| Family | Licence | Why |
|---|---|---|
| Carlito | OFL 1.1 | Metric-compatible substitute for Calibri, which is proprietary to Microsoft and cannot be redistributed. The `standard` preset's face. |
| IBM Plex Sans | OFL 1.1 | Technical humanist sans. `rule`. |
| Source Sans 3 | OFL 1.1 | Sets more economically than the rest; the density presets use it. `terminal`, `brief`. |
| Source Serif 4 | OFL 1.1 | Text serif built to hold up at small sizes. `ledger`. |
| EB Garamond | OFL 1.1 | Book serif. Small x-height, so it is set larger and still occupies less width. `quarto`. |
| Inter | OFL 1.1 | Interface sans, wide apertures. `slate`. |

Display faces for the letterhead, one weight each:

| Family | Licence | Used by |
|---|---|---|
| Fira Code | OFL 1.1 | `standard`, `rule`, `slate`, `terminal`, `brief` |
| IBM Plex Mono | OFL 1.1 | `quarto` |
| JetBrains Mono | OFL 1.1 | `ledger` |

Regenerate with `scripts/fetch_fonts.py`. These are converted from the
`@fontsource` webfont builds, which are per-unicode-range **subsets** covering
Latin and Latin Extended. That is enough for the documents cvme targets; if you
need wider coverage, swap in the full upstream OFL releases — the file names
and the name-table rewrite in the script are all the loader cares about.
