# cvme

Typeset resumes and cover letters from markdown.

```bash
uv sync
uv run cvme doctor          # check the rendering environment
uv run cvme init my-docs    # scaffold a project to fill in
cd my-docs && uv run cvme render resume
```

## Status

Under construction, milestone by milestone. See
[docs/implementation-plan.md](docs/implementation-plan.md).

| Milestone | State |
|---|---|
| M0 — scaffold, tooling, CI, `cvme doctor` | done |
| M1 — markdown grammar, parser, Typst renderer, `cvme render` | done |
| M2 — page autofit, machine-readable output, cover letters | done |
| M2b — project config, `cvme init` | done |
| M3 — fact corpus and the `cvme verify` guardrails | done |
| M4 — job description scraping | deferred |
| M5 — agent-driven tailoring | deferred |

## Design

Markdown is the authoring surface. It parses to a typed intermediate
representation, which a Typst template renders to PDF:

```
markdown ──parse──▶ typed IR ──render──▶ Typst source ──compile──▶ PDF
                        ▲
                  style config (TOML)
```

Fonts are vendored and system fonts are disabled, and the PDF timestamp is
pinned, so the same source produces byte-identical output everywhere.

## Usage

A project is a directory with a `cvme.toml`, found by walking up from wherever
you run the command. Documents are named there, so you render by name and the
output lands in the configured directory:

```bash
uv run cvme render resume
uv run cvme render cover_letter
```

Verification checks that every number is sourced and the prose does not read
as generated:

```bash
uv run cvme verify              # every configured document
uv run cvme verify resume
uv run cvme verify draft.md --facts facts/metrics.md --json
```

Any markdown file works without a project:

```bash
uv run cvme render path/to/resume.md -o out/resume.pdf
uv run cvme render resume.md --style compact --png
uv run cvme render resume.md --set leading=6.0 --set margin_x=50
uv run cvme render resume.md --watch
uv run cvme render resume.md --max-pages 1        # tighten until it fits
uv run cvme render resume.md --pdf-standard ua-1  # accessibility-tagged
uv run cvme render cover_letter.md --template cover_letter --style letter
```

`--max-pages` is enforced: the renderer walks a bounded ladder of density
adjustments and fails with a diagnostic naming the longest material if the
floors are reached. See [docs/machine-readability.md](docs/machine-readability.md)
for how the output reads to a parser.

The authoring grammar is [`src/cvme/md/GRAMMAR.md`](src/cvme/md/GRAMMAR.md).
`tests/fixtures/resume.md` is a complete worked example.

## Guardrails

`cvme verify` exists because a prompt asking a model not to invent numbers
fails silently, and you find out after you have applied.

- **Every quantitative claim must be sourced.** Numbers are extracted from the
  document and normalised, so `100k`, `100,000` and `$100K` compare as one
  value, then matched against `facts/metrics.md`, `facts/skills.md` and your
  base resume. Matching is exact: `$98k` in the corpus does not license
  `$100k` in the output, because rounding up is the failure this catches. A
  bullet may cite its source with `<!-- fact: id -->`, and is then checked
  against that fact specifically.
- **Prose is linted for generated register.** Em dashes, the "not just X, it's
  Y" construction, a list of stock phrases, weak bullet openers, and
  rule-of-three cadence. Rules live in
  [`src/cvme/verify/rules.toml`](src/cvme/verify/rules.toml).

Exit codes are distinct so a script can tell failures apart: `1` bad input,
`2` page budget, `3` verification.
