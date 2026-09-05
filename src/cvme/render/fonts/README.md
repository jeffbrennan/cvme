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
| Source Sans 3 | OFL 1.1 | Sets economically and holds up small. The `sans` preset's face. |
| Source Serif 4 | OFL 1.1 | Text serif with a large x-height, so it survives 10pt. The `serif` preset's face. |
| Carlito | OFL 1.1 | Metric-compatible substitute for Calibri, which is proprietary to Microsoft and cannot be redistributed. `standard`, `compact`, `airy`. |
| IBM Plex Sans | OFL 1.1 | Technical humanist sans. No preset ships it; `--set body_font='IBM Plex Sans'` does. |
| EB Garamond | OFL 1.1 | Book serif. Small x-height, so it wants a larger size than the others. |
| Inter | OFL 1.1 | Interface sans, wide apertures. |

Display faces for the letterhead and the section headings, one weight each:

| Family | Licence | Used by |
|---|---|---|
| Fira Code | OFL 1.1 | Every preset |
| IBM Plex Mono | OFL 1.1 | Available; no preset ships it |
| JetBrains Mono | OFL 1.1 | Available; no preset ships it |

Regenerate with `scripts/fetch_fonts.py`. These are converted from the
`@fontsource` webfont builds, which are per-unicode-range **subsets** covering
Latin and Latin Extended. That is enough for the documents cvme targets; if you
need wider coverage, swap in the full upstream OFL releases — the file names
and the name-table rewrite in the script are all the loader cares about.
