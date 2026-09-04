# cvme — Implementation Plan

A CLI that turns markdown into typeset resume/cover-letter PDFs, pulls job
descriptions off LinkedIn/Indeed, and drives a coding agent to produce
tailored variants that cannot invent facts.

---

## 0. Status of this plan

The riskiest technical bet — the markdown-to-PDF engine — was **prototyped and
verified** before this plan was written. See `spikes/typst_spike.py`; it
compiles a resume-shaped page with right-aligned dates, bold/italic runs, a
size hierarchy, and section rules, in-process, with no LaTeX and no external
binary.

The existing resume was then supplied directly, its layout measured, and a
Typst template built that **reproduces it to within ~1pt** on every section
header, right-aligned date and line-spacing measurement. The recovered spec is
§12; the working template is `spikes/match/`.

One thing could not be verified from the authoring environment, because its
egress proxy blocks the domains: `linkedin.com`, `indeed.com`,
`developers.openai.com`, `opencode.ai`. Scraper selectors and agent-CLI flags
are therefore designed to be **configuration, not code** (§6, §7), so drift is
a TOML edit rather than a patch.

---

## 1. Design decisions, up front

### 1.1 Typst, not LaTeX / HTML / ReportLab

`typst-py` ships as an `abi3` wheel for cp38+ on Linux/macOS/Windows. It embeds
the whole Typst compiler, so `uv sync` is the only install step — no TeX
distribution, no headless browser, no system fonts required.

| Option | Why not |
|---|---|
| LaTeX (`pandoc` → `xelatex`) | Multi-GB system dependency; brittle install; slow. |
| WeasyPrint (HTML/CSS) | Pure Python, but weak on precise vertical rhythm and page-fitting; CSS paged-media support is partial. |
| ReportLab | You hand-build every box. All the layout, none of the typesetting. |
| **Typst** | Single wheel, sub-100ms compiles, real typesetting (grids, baseline control, widow/orphan handling), scriptable. |

Verified API: `typst.compile(input, output=None, root=None, font_paths=...,
ignore_system_fonts=False, format=None, ppi=None, sys_inputs=...,
pdf_standards=..., package_path=None, timestamp=None, pretty=False)`.

Three properties of that signature matter to this design:

- **`input` accepts a `dict[str, bytes]`** — a virtual filesystem. Templates and
  data go in as in-memory bytes; nothing is written to a temp dir. This is what
  the spike does.
- **`font_paths` + `ignore_system_fonts=True`** — vendor the fonts, get
  byte-identical output on every machine. Without this, output silently depends
  on what the developer happens to have installed.
- **`timestamp`** — pin it, and PDF bytes become reproducible, which is what
  makes golden-file tests possible (§9).

One licensing consequence, found while matching the reference: the current
resume sets its body in **Calibri**, which is proprietary to Microsoft and
cannot be vendored. **Carlito** is a metric-compatible OFL clone, so
substituting it preserves measure and line breaking with no visible change.
The name is set in **Fira Code SemiBold**, which is OFL and ships as-is. Both
go in `render/fonts/` from full upstream releases — not from webfont subsets,
whose partial glyph coverage causes silent fallback (the reference's ▪ bullet
hit exactly this).

### 1.2 Markdown is the authoring surface; a typed IR is the contract

The generator writes markdown. That is the whole reason the input format must
stay markdown and must stay simple: **a format an LLM writes unreliably is a
format that breaks the pipeline.** An elaborate TOML schema would be easier to
parse and much worse to generate.

So: markdown with YAML frontmatter, plus exactly **one** structural convention
beyond standard markdown — a pipe splits left-aligned from right-aligned text.
Everything else is ordinary markdown.

```
markdown ──parse──▶ typed IR (pydantic) ──render──▶ Typst source ──compile──▶ PDF
                          ▲
                    style config (TOML)
```

The IR is the seam. The parser never knows about fonts; the renderer never
knows about markdown. Adding a document type (a one-pager, a reference sheet)
means a new template, not a new parser.

### 1.3 Guardrails are code, not prompt text

You asked for no invented metrics and no AI-speak. A prompt asking for that is
necessary and **not sufficient** — it fails silently and you find out after you
have applied.

So every quantitative claim is checked by a deterministic verifier against a
fact corpus you control (`facts/metrics.md`, `facts/skills.md`), and a lint pass
rejects AI-speak. `cvme tailor` refuses to emit a document that fails either.
The prompt (§7.2) is the first line of defence; §8 is the one that actually
holds.

---

## 2. Repository layout

```
cvme/
├── pyproject.toml
├── cvme.toml                       # user config, created by `cvme init`
├── src/cvme/
│   ├── models.py                   # pydantic IR: Document, Section, Entry, Fact, JobPosting
│   ├── config.py                   # layered config resolution
│   ├── errors.py                   # CvmeError hierarchy → clean CLI exits
│   ├── cli/
│   │   ├── app.py                  # typer root
│   │   ├── render.py  job.py  tailor.py  verify.py  init.py  doctor.py
│   ├── md/
│   │   ├── parse.py                # markdown → IR
│   │   ├── inline.py               # markdown-it inline tokens → Typst markup
│   │   └── GRAMMAR.md              # the authoring contract (§3)
│   ├── render/
│   │   ├── engine.py               # IR + style → dict[str,bytes] → typst.compile
│   │   ├── fit.py                  # page-count autofit ladder (§5.2)
│   │   ├── templates/{resume,cover_letter,_common}.typ
│   │   └── fonts/                  # vendored OFL fonts + LICENSE
│   ├── style/
│   │   ├── schema.py               # pydantic style model
│   │   └── presets/{standard,compact,airy}.toml
│   ├── scrape/
│   │   ├── base.py                 # Scraper protocol, tier ladder, registry
│   │   ├── jsonld.py               # schema.org JobPosting — the generic extractor
│   │   ├── linkedin.py  indeed.py  generic.py
│   │   ├── browser.py              # Playwright, persistent profile
│   │   └── selectors.toml          # site selectors as data, not code
│   ├── generate/
│   │   ├── agent.py                # subprocess adapter, config-driven argv
│   │   ├── bundle.py               # assembles the prompt payload
│   │   └── prompts/{resume,cover_letter,_rules}.md
│   └── verify/
│       ├── facts.py                # numeric claim extraction + fact matching
│       ├── aispeak.py              # banned constructions
│       └── rules.toml
├── spikes/typst_spike.py           # the validated proof-of-concept
├── templates/                      # starter files `cvme init` copies out
│   └── {resume,cover_letter,skills,metrics}.md
├── docs/implementation-plan.md
└── tests/
```

---

## 3. The markdown grammar

The full contract lives in `src/cvme/md/GRAMMAR.md` and is embedded verbatim in
the generator prompt, so the model and the parser are never out of sync.

### 3.1 `resume.md`

```markdown
---
name: Jeff Brennan
contact:
  - text: jeffbrennan10@gmail.com
    url: mailto:jeffbrennan10@gmail.com
  - text: jeffbrennan.dev
    url: https://jeffbrennan.dev
---

## Summary

Careful preparation of public health data improves the lives of underserved
communities. I have six years of experience working at every level of the
healthcare data lifecycle. <!-- fact: s-experience-years -->

## Experience

### Data Engineer @ Medisolv | Jul 2023 – Present

- Oversee the ingestion and transformation of patient data (10B+ records/week,
  150TB+ data lake) for hundreds of hospital clients <!-- fact: m-ingest-scale -->
- Created a CLI to generate Databricks Workflows - enabling our team to
  programmatically tailor cluster configurations for clients with thousands to
  millions of patients

### Data Analyst @ New York-Presbyterian | Dec 2020 – Jul 2023

- Managed the calculation, tracking, and reporting of quality metrics, leading
  to $20M+ in savings <!-- fact: m-nyp-savings -->

## Education

### UTHealth Houston
#### Master of Science - Major in Epidemiology, Minor in Biostatistics | May 2020

Certificate: Data Science

## Skills

- **Languages**: Python (advanced), SQL (advanced), R (advanced)
- **Data Stack**: Transformation (pyspark, dbt, polars); Orchestration (azure
  data factory, airflow, dagster)
```

Rules, in full:

| Construct | Meaning |
|---|---|
| YAML frontmatter | Name and the contact list; each contact may carry a `url`, rendered as an underlined link. |
| `## Heading` | Section. Uppercased, bold, 12pt, no rule (§12). |
| `### Left \| Right` | Entry header line. Text after `\|` is **right-aligned** to the right margin on the same line. |
| `### Role @ Org \| Dates` | Within `## Experience`, ` @ ` splits the left side so the template can set the role bold and the org regular, as `**Role** – Org`. |
| `#### Left \| Right` | Second entry line, same split. Used by Education for `degree \| date`. |
| Plain paragraph under an entry | Follow-on line, unstyled (`Certificate: Data Science`). |
| `- item` | Bullet. Tight, hanging indent, drawn square marker. |
| `**b**` `*i*` `` `c` `` `[t](u)` | Standard inline markdown, converted to Typst markup. |
| `<!-- fact: <id> -->` | Provenance tag consumed by `cvme verify` (§8) and stripped from output. |
| `---` (rule) | Explicit page break. |

The pipe is the only real invention, and ` @ ` is a convenience within it.
Everything not entry-shaped — Summary, Skills — is ordinary markdown, which the
template renders without entry chrome. Literal `|` and `@` escape as `\|`, `\@`.

### 3.2 `cover_letter.md`

Frontmatter carries `recipient`, `company`, `role`, `date`; the body is
ordinary markdown paragraphs. No entry grammar.

### 3.3 The fact files

`facts/metrics.md` — every number you are allowed to claim:

```markdown
- [m-databricks-spend] Managed a Databricks platform at ~$100k/month spend.
- [m-ingest-window] Cut a nightly ingestion window from 6 hours to 40 minutes.
- [m-team-size] Led a team of 4 engineers.
```

`facts/skills.md` — every capability claim, with duration:

```markdown
- [s-pyspark] PySpark — 6 years, production, batch and streaming.
- [s-databricks] Databricks — 5 years, incl. Unity Catalog and workflow orchestration.
- [s-dbt] dbt — 2 years, ~200 models.
```

The bracketed ID is optional in authoring — `cvme verify` derives a stable slug
when it is absent — but writing it explicitly is what lets a bullet cite its
source. These files are the *only* corpus the verifier trusts, alongside the
base resume.

---

## 4. Configuration

`cvme.toml`, resolved in layers: **packaged defaults → `cvme.toml` → preset
(`--style compact`) → CLI flags**. Every layer is a partial; later wins.

```toml
[profile]
resume        = "base/resume.md"
cover_letter  = "base/cover_letter.md"
facts         = ["facts/skills.md", "facts/metrics.md"]
output_dir    = "applications"

[style.resume]
preset        = "standard"
font          = "Source Serif 4"
font_mono     = "JetBrains Mono"
base_size     = "10.5pt"
name_size     = "20pt"
section_size  = "11pt"
leading       = "0.58em"
margin_x      = "0.6in"
margin_y      = "0.5in"
accent        = "#1a1a1a"
rule_weight   = "0.6pt"
section_order = ["Experience", "Skills", "Education"]
max_pages     = 1
autofit       = true          # see §5.2

[style.cover_letter]
preset        = "standard"
max_pages     = 1

[generate]
agent          = "codex"
tone           = "direct, concrete, first-person, past tense"
bullets_per_role = { min = 2, max = 5 }
max_bullet_words = 32

[verify]
strict_numbers = true         # unsourced number = hard failure
banned_phrases_extra = []
```

---

## 5. Rendering (Milestone 1 — do this first)

### 5.1 Pipeline

`engine.py` builds a `dict[str, bytes]` — `main.typ` (the template),
`data.json` (the serialised IR), `style.json` (the resolved style) — and hands
it to `typst.compile`. The template reads both JSON files and does all layout.
Fonts come from `render/fonts/` with `ignore_system_fonts=True`.

Right-alignment, the thing plain markdown cannot do, is a two-column Typst grid:

```typst
grid(columns: (1fr, auto), align: (left, right),
  text(weight: "bold", size: style.entry_size)[#entry.left],
  text(weight: "bold", size: style.entry_size)[#entry.right])
```

Confirmed working in the spike, and used throughout `spikes/match/resume.typ`
to place dates, degree dates and the contact line.

The bullet glyph is drawn rather than typed — `box(width: 3.2pt, height: 3.2pt,
fill: black)` — so it never depends on a font shipping ▪ or on the reference's
Wingdings mapping.

### 5.2 Page-count autofit

`max_pages` is enforced, not suggested. `fit.py` compiles, counts pages
(`pypdf`), and if over budget walks a bounded **density ladder** — leading, then
inter-section spacing, then margins, then base font size — each step within
floors declared in the style config, recompiling after each. Compiles are cheap
enough that a five-step ladder is imperceptible.

If the floor is reached and it still overflows, it fails with a real diagnostic:
which section is longest, how many lines over, and the two or three bullets it
would drop first. It never silently shrinks type to 7pt.

`--no-autofit` renders as authored and only warns.

### 5.3 CLI

```
cvme render base/resume.md -o out/resume.pdf
cvme render base/resume.md --style compact --max-pages 1
cvme render base/resume.md --watch          # recompile on save
cvme render base/resume.md --png            # for quick visual diffing
```

---

## 6. Scraping (Milestone 4)

> **Superseded in part.** Research into the existing libraries changed this
> section's conclusions, in particular that the anonymous LinkedIn HTTP tier
> is probably no longer viable. See [job-sources.md](job-sources.md) for the
> evidence and the revised tier ladder.

### 6.1 Tier ladder

Each site gets an ordered list of strategies; the first that yields a valid
`JobPosting` wins. Every tier caches its raw HTML under `.cvme/cache/` keyed by
URL hash, so re-parsing never re-fetches and selector work is offline.

1. **JSON-LD** (`jsonld.py`) — `<script type="application/ld+json">` with
   `@type: JobPosting`. Standardised by schema.org, emitted by LinkedIn, most
   ATS platforms (Greenhouse, Lever, Ashby, Workday), and often Indeed. This is
   the most durable extractor in the project and is tried first *everywhere*.
2. **Site HTTP** — `httpx` + realistic headers.
   - LinkedIn: extract the numeric job ID from `/jobs/view/<id>` and hit the
     unauthenticated guest render endpoint
     `/jobs-guest/jobs/api/jobPosting/<id>`, which returns server-rendered HTML.
   - Indeed: `/viewjob?jk=<id>`, parse the embedded initial-state JSON.
3. **Browser** (`browser.py`) — Playwright over a **persistent** Chromium
   profile at `~/.cvme/browser/`, so a one-time manual login/CAPTCHA is
   remembered. This is the realistic path for Indeed.
4. **Manual** — `cvme job add --stdin`, `--file jd.txt`, or `--html saved.html`.

Tier 4 is a **first-class path, not a failure mode.** Indeed sits behind
commercial bot mitigation that changes without notice; anything else would be
dishonest about the reliability on offer. The CLI says which tier produced a
result.

Selectors live in `scrape/selectors.toml`. When a site changes, you edit data.

### 6.2 Output

Normalised to `JobPosting` (company, title, location, employment type, salary,
posted date, description, url, source, fetched_at, tier) and written as
markdown with YAML frontmatter to `jobs/<company>-<role>-<shortid>.md`, so job
descriptions are reviewable, diffable, and committable.

### 6.3 Conduct

Default 2s inter-request delay, honest UA identifying the tool, single-fetch
semantics (no crawling, no search-result enumeration), on-disk cache to avoid
refetching. This is a personal tool fetching pages you were going to open
anyway; it should behave like it.

---

## 7. Generation (Milestone 5)

### 7.1 Agent adapter

`cvme tailor` assembles a prompt bundle and shells out. The argv is **config**,
because these CLIs move fast:

```toml
[agent.codex]
argv  = ["codex", "exec", "--cd", "{workdir}", "-"]
stdin = true

[agent.opencode]
argv  = ["opencode", "run", "{prompt}"]
stdin = false

[agent.none]        # writes the prompt to a file and stops
```

`cvme doctor` probes each configured binary's `--help` and reports what it
found, so a flag change surfaces as a diagnostic rather than a stack trace.

The agent is told to **write files to given paths**; cvme then reads and
validates those files. Nothing depends on parsing agent stdout.

`--dry-run` prints the full assembled prompt and exits — which also makes the
tool useful with any assistant, not just the two wired up.

### 7.2 The prompt

Assembled from `prompts/_rules.md` + a task prompt + the payload (base document,
`GRAMMAR.md`, the fact corpus, the job posting, the style budget).

`_rules.md`, in substance:

**Sourcing.** Every number, duration, percentage, currency amount, team size,
and scale claim must come verbatim (or as a faithful restatement) from the
provided fact corpus or base resume. Tag each with `<!-- fact: <id> -->`. If the
job asks for something not in the corpus, omit it. Do not interpolate, round up,
estimate, or combine two facts into a third. Missing evidence is reported in a
`## Gaps` block at the end of the file, never papered over.

**Prohibited constructions.** Em dashes. "not just X, it's Y" and its variants
("isn't merely", "more than just"). "leverage", "utilize", "spearheaded",
"passionate about", "proven track record", "seamless", "robust", "cutting-edge",
"delve", "tapestry", "testament to", "in today's fast-paced". Rule-of-three
lists used for rhythm. Opening a cover letter with "I am writing to". Adjective
stacking before a noun. Sentences that state what something is not before
stating what it is.

**Voice.** Past tense for past roles. First person, implied subject, in resume
bullets. One claim per bullet. Lead with the action, not the tooling. Plain
words. Concrete nouns. Prefer the shorter sentence.

**Task.** Reorder and reselect from what exists; rewrite emphasis to match the
posting's language where the underlying fact already supports it. Do not invent
responsibilities. Stay within the bullet-count and word budget. Emit only the
markdown document, conforming to GRAMMAR.md.

### 7.3 Flow

```
cvme tailor jobs/acme-senior-de-a91f.md
  → assemble prompt bundle
  → run agent (writes applications/acme-senior-de/{resume,cover_letter}.md)
  → cvme verify   (hard gate — §8)
  → cvme render   (both to PDF, autofit to max_pages)
  → print a diff summary vs. the base resume
```

Outputs land in `applications/<company>-<role>/` alongside the job posting, so
each application is one self-contained, committable directory.

---

## 8. Verification (Milestone 3 — before generation, deliberately)

Built *before* `tailor`, so the generator never runs unguarded.

### 8.1 `verify/facts.py`

Extracts every numeric claim from the generated document — integers with scale
suffixes (`100k`, `4B`), currency, percentages, durations (`6 years`,
`40 minutes`), ratios, dates, team sizes — normalises them (`100k` ≡ `100,000` ≡
`$100K/mo`), and requires each to match a claim in the corpus.

- A claim with a `<!-- fact: id -->` tag is checked against **that** fact.
- An untagged claim is searched across the whole corpus.
- Unmatched → error, with the offending line, the number, and the nearest
  corpus candidates.

`strict_numbers = false` downgrades this to a warning for drafting.

### 8.2 `verify/aispeak.py`

Regex and heuristic rules from `verify/rules.toml`: banned phrases, em dash
detection (with a configurable allowance for ranges), the "not X but Y" family,
rule-of-three detection, adjective stacking, sentence-length distribution,
opener blacklist. Each hit reports file, line, column, rule ID, and a rewrite
suggestion.

### 8.3 CLI

```
cvme verify applications/acme-senior-de/resume.md
cvme verify applications/acme-senior-de/ --json     # machine-readable
```

Non-zero exit on any error. Usable standalone on hand-written documents, and
wired into `tailor` as a gate. `--fix` is deliberately out of scope: mechanical
rewriting of your own voice is how documents start sounding generated.

---

## 9. Tooling, types, tests

**`pyproject.toml`**

```toml
requires-python = ">=3.13"
dependencies = [
  "typer", "pydantic>=2", "markdown-it-py", "typst",
  "httpx", "selectolax", "pyyaml", "pypdf", "rich", "tomli-w",
]
[project.optional-dependencies]
browser = ["playwright"]
[project.scripts]
cvme = "cvme.cli.app:app"
[dependency-groups]
dev = ["pytest", "pytest-cov", "ruff", "pyrefly", "syrupy"]
```

Playwright is optional so the base install stays a pure-wheel `uv sync`;
`cvme doctor` tells you when a tier needs it.

**`pyrefly`** at `project.level = "standard"` in `[tool.pyrefly]`, `src` layout,
no untyped defs, CI-enforced.

**`ruff`** format + lint (`E,F,I,UP,B,SIM,RUF`), line length 88.

**Tests**

- Parser: markdown fixture → IR, golden JSON snapshots (`syrupy`).
- Renderer: IR → **Typst source** golden snapshots. Diffing generated Typst is
  legible; diffing PDF bytes is not. A handful of end-to-end cases additionally
  assert page count and non-zero PDF size, with `timestamp` pinned for
  reproducibility.
- Autofit: a deliberately overlong document must land within `max_pages`; an
  impossible one must fail with the structured diagnostic.
- Scrapers: saved HTML fixtures per site per tier. **No network in tests.**
- Verify: adversarial corpus — invented metrics, em dashes, "not just X",
  rounded-up numbers — each must be caught.
- Agent adapter: subprocess mocked; assert argv construction and file handling.

**CI** — GitHub Actions on 3.13 and 3.14: `ruff format --check`, `ruff check`,
`pyrefly check`, `pytest`.

---

## 10. Milestones

| # | Deliverable | Gate |
|---|---|---|
| **M0** | uv scaffold, typer skeleton, config loader, `cvme doctor`, CI green | `cvme --help` |
| **M1** | Grammar, parser, IR, Typst templates, `cvme render` + `--watch` | Your real resume renders to a PDF you would send |
| **M2** | Style config, presets, autofit ladder, cover-letter template | `--style compact --max-pages 1` holds |
| **M3** | Fact corpus loading, `cvme verify`, AI-speak lint | Adversarial fixtures all caught |
| **M4** | `cvme job fetch` — JSON-LD, LinkedIn, Indeed, browser, manual | LinkedIn via HTTP; Indeed via browser or paste |
| **M5** | Prompt suite, agent adapter, `cvme tailor` end-to-end | A tailored variant passes verify unassisted |
| **M6** | `cvme apply <url>` one-shot, `cvme init` scaffolding, README | `cvme apply <url>` produces a reviewed application dir |
| **M7** | `cvme convert` — PDF back into the grammar (§13) | Rendering the fixture and converting it back returns the same IR |
| **M8** | `cvme ats` — check the rendered PDF as a parser reads it (§14) | A drawn bullet marker fails the check that a typed one passes |

M1 is the milestone that matters, and it is already part-built: `spikes/match/`
renders your existing resume to spec (§12). What remains in M1 is the markdown
parser feeding that template, rather than the template itself.

---

## 11. Open questions

1. ~~The reference layout.~~ **Resolved** — measured and reproduced; see §12.
   One judgement call is left in it: the reference has small inconsistencies
   (one company name set at 11.48pt instead of 11.01pt, a bullet group indented
   32.4pt where the rest use 32.4pt from a different origin) that look like Word
   artifacts rather than intent. The template normalises them. Say if any were
   deliberate.
2. ~~Cover-letter length control.~~ **Implemented as proposed**, since it was
   the recommendation: `on_overflow` is a tri-state (`fit`, `warn`, `error`),
   the letter preset uses `error`, and the diagnostic reports paragraph and
   word counts. Say if you would rather letters tightened after all.
3. ~~`~` in metrics.~~ **Implemented as proposed**: matching is on the
   normalised numeric value, so `$98k` does not license `$100k`. The `~` is not
   part of the value, so `~$100k` and `$100k` do compare equal; write the
   approximation into the corpus and it verifies.
4. **Agent default.** `codex` assumed. Flip in `cvme.toml` if `opencode` is your
   daily driver.
5. **Repo scope.** Plan assumes `cvme` is the tool and your documents live in a
   separate private directory (`--profile <dir>`, or `cvme.toml` discovery from
   cwd). The alternative — documents committed here — is fine if the repo stays
   private. Confirm before M0.

---

## 12. Recovered reference spec

Measured from the supplied PDF with `pdfplumber` (character positions, font
names and sizes), and reproduced in `spikes/match/resume.typ`. This is the
`standard` preset's starting point.

### Page

| Property | Value |
|---|---|
| Paper | US Letter, 612 × 792pt |
| Margins | left/right 0.8in (57.6pt), top/bottom 0.5in |
| Length | 1 page |

### Type scale

| Role | Font | Size | Weight |
|---|---|---|---|
| Name | Fira Code | 19.5pt | SemiBold (600) |
| Section header | Calibri → **Carlito** | 12pt | Bold, uppercased |
| Body, bullets, summary | Carlito | 11pt | Regular |
| Job title, school, degree, skill label | Carlito | 11pt | Bold |
| Dates | Carlito | 10pt | Bold |

**There are no horizontal rules.** The only rectangles in the reference are
the underlines on the two contact hyperlinks. Section headers are separated by
whitespace alone — worth stating, because ruled headers are the default
assumption for this kind of layout and the first spike wrongly used them.

### Layout

| Element | Treatment |
|---|---|
| Header | Name left at the margin, contact right-aligned to the right margin, **same line**, bottom-aligned across the size difference. Contacts pipe-separated, each an underlined link. |
| Entry header | `**Role** – Company` left; dates bold 10pt hard right. One line. |
| Education | School bold on its own line; degree bold on the next line **with the date right-aligned against the degree, not the school**; optional plain follow-on lines. |
| Bullets | Marker at +18pt from margin, text at +32.4pt (hanging indent; wrapped lines align to the text edge). |
| Skills | Bullets, `**Label**: body`. |

### Vertical rhythm

| Gap | Value |
|---|---|
| Line to line (11pt body) | 13.44pt baseline-to-baseline |
| Between bullets | same as line — bullets are tight, no extra space |
| Before a section header | ~7pt |
| After a section header | ~11pt |
| Before an entry | ~6.7pt |
| Header block to first section | ~10pt |

In Typst this comes out as `par(leading: 0.73em)` with a tight list; the
measured result is 13.4–13.5pt against the reference's 13.4–13.5pt.

### Verification

`tests/geometry.py` measures a rendered PDF and `tests/test_render_geometry.py`
asserts against it. Measurement is by **text baseline**, read from each
character's text matrix — not by bounding-box top, which moves with ascender
height and so shifts whenever font weight or size changes. That distinction
mattered: it accounted for roughly half the apparent error during tuning.

Against the reference, per-line spacing error is now:

| Measure | Value |
|---|---|
| Mean absolute error | 0.26pt |
| Max error | 0.90pt |
| Lines beyond 0.7pt | 2 of 40 |
| Pages | 1, as the reference |

The residual is at the reference's own noise floor. Word set its gap after a
section header anywhere between 24.0pt and 25.7pt depending on the section — a
1.7pt spread with no apparent intent — where cvme is uniform at 24.9pt. The
remaining outliers are all instances of that inconsistency, so closing them
further would mean reproducing Word's arbitrariness rather than the design.

Comparing geometry rather than PDF bytes is what makes this a usable
regression test, and §9's golden-file strategy is built on it.

---

## 13. Conversion (Milestone 7)

`cvme convert` reads an existing PDF resume and writes the grammar. It exists
so the first document does not have to be retyped, and so a resume whose only
surviving copy is a PDF can re-enter the pipeline.

### 13.1 Pipeline

```
PDF ──extract──▶ styled lines ──recover──▶ structure ──emit──▶ markdown
```

`convert/pdftext.py` reads glyphs and their positions; `convert/structure.py`
recovers structure and writes it out. The split matters: extraction is about
what the PDF says, recovery is about what a resume means, and only the second
half is heuristic.

### 13.2 What extraction has to reconstruct

A PDF has no words, lines or paragraphs. Three facts have to be recovered
before structure can be read at all:

| Fact | How |
|---|---|
| Spaces | Word processors emit positioned glyphs and no space characters. A gap wider than 0.2em is a space; kerning stays under 0.1em, so the two populations separate cleanly. |
| Lines | Group by text-matrix baseline, not bounding box: a box top moves with ascender height, so a 19.5pt name and its 11pt contacts read as two lines. A 2.5pt tolerance covers a header whose two halves sit a fraction apart. |
| Weight | From the font name (`Bold`, `SemiBold`, `Italic`), which is also what splits a bold role from its regular organisation — punctuation is unreliable, weight is not. |

### 13.3 What structure infers

| Construct | Signal |
|---|---|
| Letterhead | The first line of page 1, always. A name set large and bold is otherwise indistinguishable from a section header. |
| Contacts | The right-hand column of that line, split on `|`, `•`, `·`. Link annotations supply the URL; failing that, an address becomes `mailto:` and a domain `https://`. |
| Section header | Bold, at the left margin, and either larger than the body or set uppercase. Uppercase is title-cased back, since the template uppercases it again. |
| Entry header | A bold left side at the margin with a right-aligned cluster, or a wholly bold line. The bold/regular boundary splits `Role @ Org`. |
| Sub-entry | A second entry-like line one line-height below the first: `#### degree \| date`. |
| Bullet | A marker glyph — from a symbol font, or one of the usual characters — followed by text at a deeper indent. A deeper marker nests. |
| Continuation | Indented, no marker: the tail of the block above, joined with a space. |

### 13.4 The gate

The round-trip test is the specification: render `tests/fixtures/resume.md`,
convert the PDF back, and require the same IR. It fails if the renderer and the
converter ever disagree about what a document looks like, which is the only
assertion that covers extraction, spacing, structure and emission at once.

Conversion is a starting point and says so on stdout. A PDF records layout, not
intent: the section a human reads as "Projects" is bold 12pt text either way.

---

## 14. ATS checks (Milestone 8)

Everything in `docs/machine-readability.md` was, until M7, a claim about how
the output extracts. With a converter in the box those claims are testable: run
structure recovery over your own PDF and compare it to the document you wrote.

`cvme ats` renders the document, reads the PDF back, and reports the
differences. The rules are listed in `docs/machine-readability.md`; the split
between them is deliberate. An error means the document written and the
document read are different documents -- a section lost, a bullet list that
extracts as one paragraph, a letterhead with no address in it. A warning is a
judgement call the author owns, such as a proficiency in parentheses or a
section named something a parser will not map to a field.

The test that justifies the command renders the fixture with `marker_glyph=""`.
The output is visually identical apart from the marker shape, passes every
other check, and loses every bullet boundary in extraction. Nothing in the
source, the style or the rendered page shows it; only reading the artefact back
does.
