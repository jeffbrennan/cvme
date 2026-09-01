# cvme

Typeset resumes and cover letters from markdown.

```bash
uv sync
uv run cvme doctor
```

## Status

Under construction, milestone by milestone. See
[docs/implementation-plan.md](docs/implementation-plan.md).

| Milestone | State |
|---|---|
| M0 — scaffold, tooling, CI, `cvme doctor` | done |
| M1 — markdown grammar, parser, Typst renderer, `cvme render` | done |
| M2 — page autofit, machine-readable output | next |
| M3 — fact corpus and the `cvme verify` guardrails | |
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

```bash
uv run cvme render path/to/resume.md -o out/resume.pdf
uv run cvme render resume.md --style compact --png
uv run cvme render resume.md --set leading=6.0 --set margin_x=50
uv run cvme render resume.md --watch
```

The authoring grammar is [`src/cvme/md/GRAMMAR.md`](src/cvme/md/GRAMMAR.md).
`tests/fixtures/resume.md` is a complete worked example.
