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

Two things could **not** be verified from the authoring environment because its
egress proxy blocks the domains:

| Blocked | Consequence |
|---|---|
| `jeffbrennan.dev` (the reference resume PDF) | The Typst template's exact metrics are a best guess. It is fully config-driven, so matching your real layout is a tuning exercise, not a rewrite. See §11. |
| `linkedin.com`, `indeed.com`, `developers.openai.com`, `opencode.ai` | Scraper selectors and agent-CLI flags are designed to be **configuration, not code** (§6, §7), so drift is a TOML edit. |

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
headline: Data Engineer
contact:
  - jeffbrennan10@gmail.com
  - jeffbrennan.dev
  - github.com/jeffbrennan
  - Boston, MA
---

## Experience

### Acme Data | Boston, MA
#### Senior Data Engineer | Jan 2023 – Present

- Rebuilt the ingestion path in PySpark, cutting the nightly window from
  6h to 40m. <!-- fact: m-ingest-window -->
- Consolidated 40 job clusters onto shared pools. <!-- fact: m-databricks-spend -->

### Previous Co | Remote
#### Data Engineer | Jun 2020 – Dec 2022

- ...

## Skills

- **Languages:** Python, SQL, Scala
- **Platforms:** Databricks, Snowflake, dbt

## Education

### Boston University | Boston, MA
#### B.A. Economics | 2016
```

Rules, in full:

| Construct | Meaning |
|---|---|
| YAML frontmatter | Document metadata: name, headline, contact list. |
| `## Heading` | Section. Renders as the ruled small-caps header. |
| `### Left \| Right` | Entry header. Text after `\|` is **right-aligned** on the same line. |
| `#### Left \| Right` | Entry subheader, same split. Conventionally role and dates. |
| `- item` | Bullet. Nesting one level deep is supported. |
| `**b**` `*i*` `` `c` `` `[t](u)` | Standard inline markdown; converted to Typst markup. |
| `<!-- fact: <id> -->` | Provenance tag consumed by `cvme verify` (§8) and stripped from output. |
| `---` (rule) | Explicit page break. |

The pipe is the only invention. Everything a section needs that is not
entry-shaped (Skills) is plain bullets, which the template renders without the
entry chrome. A literal pipe is escaped `\|`.

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

Confirmed working in the spike.

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

M1 is the milestone that matters. It is worth spending time tuning the template
against your existing PDF before anything else is built, because every later
milestone renders through it.

---

## 11. Open questions

1. **The reference layout.** I could not fetch
   `jeffbrennan.dev/jeff_brennan_data_engineer_resume.pdf` — blocked by this
   environment's egress proxy. To match it in M1, the useful inputs are: the PDF
   itself committed to the repo, or the font family, section order, and whether
   dates sit on the company line or the role line.
2. **Cover-letter length control.** Resumes autofit by tightening. Letters
   cannot — shrinking a letter to fit is worse than cutting a paragraph. Propose:
   letters *fail* over budget with a word-count delta and let you cut. Confirm.
3. **`~` in metrics.** `~$100k/month` is honest but the verifier must decide
   whether `$98k` in the corpus licenses `~$100k` in output. Propose: exact match
   only, and write the approximation into the corpus if you want to claim it.
4. **Agent default.** `codex` assumed. Flip in `cvme.toml` if `opencode` is your
   daily driver.
5. **Repo scope.** Plan assumes `cvme` is the tool and your documents live in a
   separate private directory (`--profile <dir>`, or `cvme.toml` discovery from
   cwd). The alternative — documents committed here — is fine if the repo stays
   private. Confirm before M0.
