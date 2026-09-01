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
| M1 — markdown grammar, parser, Typst renderer, `cvme render` | next |
| M2 — style presets, page autofit, machine-readable output | |
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

Fonts are vendored and system fonts are disabled, so the same source produces
the same PDF everywhere.
