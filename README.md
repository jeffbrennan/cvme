# cvme

Typeset resumes and cover letters from markdown.

```bash
uv sync
uv run cvme doctor          # check the rendering environment
uv run cvme init my-docs    # scaffold a project to fill in
cd my-docs && uv run cvme render resume
```

For a standalone install and a workspace outside the source checkout:

```bash
uv tool install .            # from this checkout (or `uv tool install cvme` once published)
cvme init ~/Documents/job_hunt/2026
cd ~/Documents/job_hunt/2026
cvme render resume
```

The generated application bundles live under `applications/` in that
workspace by default. Set `project.applications_dir` in `cvme.toml` to put them
elsewhere; absolute paths and paths relative to the config file both work.

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
| M4 — job capture: ATS APIs, JSON-LD, manual paths | partial (offline tiers) |
| M5 — agent-driven tailoring | done |
| M7 — `cvme convert`: an existing PDF resume back into markdown | done |
| M8 — `cvme ats`: check the rendered PDF the way a parser reads it | done |
| M9 — `cvme prep` and `cvme apps`: one directory per posting, tracked | done |

## Design

Markdown is the authoring surface. It parses to a typed intermediate
representation, which a Typst template renders to PDF:

```
markdown ──parse──▶ typed IR ──render──▶ Typst source ──compile──▶ PDF
                        ▲
                  style config (TOML)
```

`cvme convert` runs that pipeline backwards, so an existing PDF becomes a
source file this project can render, verify and tailor:

```
PDF ──extract──▶ styled lines ──recover──▶ structure ──emit──▶ markdown
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

Start from a resume you already have. `cvme convert` reads a PDF and writes
the markdown grammar, so an existing document becomes an editable source file
in one step:

```bash
uv run cvme convert base.pdf              # writes base.md beside it
uv run cvme convert base.pdf -o resume.md
uv run cvme convert base.pdf --stdout
```

Structure is recovered from geometry, because geometry is all a PDF records: a
bold line larger than the body is a section header, a date hard against the
right margin makes an entry header, a marker glyph followed by indented text is
a bullet, and an indented line without a marker continues the bullet above it.
Weight and slant become `**bold**` and `*italic*`, link annotations become
markdown links, and spaces are rebuilt from the gaps between glyphs — word
processors routinely emit no space characters at all. Read the result before
rendering it: a PDF records layout, not intent.

Capture a posting:

```bash
uv run cvme job fetch https://boards.greenhouse.io/acme/jobs/4012345
uv run cvme job fetch 'https://www.indeed.com/viewjob?jk=abc123'
uv run cvme job fetch https://www.linkedin.com/jobs/view/123
uv run cvme job add --html saved.html --url https://www.linkedin.com/jobs/view/123
pbpaste | uv run cvme job add --stdin --url https://x.example/1 --title T --company C
```

Search LinkedIn and Indeed in bulk and digest only postings not seen before:

```toml
[search]
blocked_companies = ["Raytheon", "Palantir"]
preferred_titles = ["data engineer", "platform engineer"]
excluded_titles = ["manager", "director"]
include_keywords = ["python", "spark", "databricks"]
exclude_keywords = ["security clearance"]
locations = ["New York, NY"]
remote_only = false
minimum_score = 2
request_interval_seconds = 5.0
max_detail_requests_per_run = 10

[[search.sources]]
site = "linkedin"
query = "data engineer"
location = "New York, NY"
pages = 2
posted_within_days = 7

[[search.sources]]
site = "indeed"
query = "data engineer"
location = "New York, NY"
pages = 2
posted_within_days = 7
```

Set `remote = true` on a source to request remote-only results from that board.
For “remote or NYC,” configure one NYC source and a second remote source; the
database deduplicates jobs returned by both.

Every outbound search or uncached detail fetch shares the configured minimum
interval. The detail-request cap leaves excess postings queued for the next
run; `--limit` can lower that cap for a one-off run but cannot raise it.

```bash
cvme digest                 # discover, parse, filter, and rank new postings
cvme digest --no-search     # process queued, unparsed postings only
cvme digest --retry-errors  # retry pages that were unavailable last time
```

Hard exclusions (company, title, keyword, location, and remote-only) are
applied before ranking. Preferred titles score three points; matching keywords,
an allowed location, and remote work score one each. Accepted postings are
written to `jobs/`, ready for `cvme tailor`. All identities and decisions live
in `.cvme/jobs.sqlite3`, so a posting remains deduplicated even when its search
URL or rank changes. Public search/detail pages can still return login or
challenge pages; those are recorded as errors and can be retried after using a
saved/manual capture path.

Tailor to a posting. The agent writes the documents, cvme verifies them, and
only then renders:

```bash
uv run cvme tailor northwind                    # uses the configured agent
uv run cvme tailor northwind --dry-run          # print the prompt, change nothing
uv run cvme tailor northwind --agent none       # write the prompt to paste elsewhere
```

## One posting, one directory

`cvme prep` runs the whole pipeline against a single posting: capture it,
score how well your corpus answers it, tailor every document, verify, render,
and write the background to read before the interview.

```bash
cvme prep https://boards.greenhouse.io/acme/jobs/4012345
cvme prep 'https://www.linkedin.com/jobs/view/123' --fit-only   # score it, stop
pbpaste | cvme prep 'https://www.linkedin.com/jobs/view/123' --stdin \
    --title 'Staff Data Engineer' --company Acme
cvme prep northwind --note 'shorter, led with the platform work'
```

It produces, or adds a version to:

```
hunts/2026/01_northwind-health_staff-data-engineer_2026-01-04/
    posting.md    the posting as captured, unedited
    report.md     the computed fit score, then the written background
    apps/
        index.md  every version, and how each differs from the one before
        cv1.md  cv1.pdf  cover_letter1.md  cover_letter1.pdf
        cv2.md  cv2.pdf  cover_letter2.md  cover_letter2.pdf
```

Running it again on the same posting adds version 2 beside version 1 rather
than overwriting it, because the comparison worth having is against what you
nearly sent. `--new` forces a separate hunt instead. The filename stem comes
from `hunt_stem` on the document, so `[documents.base]` can still be filed as
`cv1.md`.

### The fit score

The score is computed, and it shows its working. A model asked to rate a fit
returns a number that reads well and cannot be checked, which is the failure
`cvme verify` exists to catch everywhere else.

The posting is read for terms from a packaged vocabulary of tools, practices
and domains, weighted by how often the posting names each one, and those terms
are looked for in your fact corpus and base documents. Skills carry 60 points,
the title 15, the stated years of experience 15, and the location 10. A posting
your own filters exclude scores zero and says which filter did it. Extend the
vocabulary for your field under `[fit.extra_terms]` in `cvme.toml`.

What that buys is the second half of `report.md`: which of the posting's own
requirements your corpus answers, and which it does not.

```
**Fit 58/100 (fair)**

| component | earned | of | why |
|---|---|---|---|
| skills | 30 | 60 | 7/14 terms, weighted by mention count |
| title | 15 | 15 | matches 'data engineer' |
| experience | 15 | 15 | asks 6y, corpus evidences 7y |
| location | 5 | 10 | no preferred locations set |

**Answered.** databricks (2), airflow, data quality, kubernetes, python, sql

**Not answered.** claims (2), delta lake, healthcare, pyspark, rust, terraform
```

The rest of the report is written by the agent from the posting and your
corpus, with anything it recalls rather than reads kept under its own
`## From general knowledge (unverified)` heading. The score is never asked of
the agent, so nothing in the report asserts a number that cannot be recomputed.

### Tracking what you have not sent

```bash
cvme apps list                       # prepared and unsent, best fit first
cvme apps list --status applied,interviewing
cvme apps list --all
cvme apps show northwind             # every version, and what changed between them
cvme apps submit northwind           # sent: file it under applied/
cvme apps status northwind interviewing --note 'call tuesday'
cvme apps status northwind rejected
```

Statuses are `prepared`, `applied`, `interviewing`, `offer`, `rejected` and
`withdrawn`. Refiling moves the whole directory, so what is still sitting at
the top level of the year is exactly what is still unsent. The index over it
lives in `.cvme/jobs.sqlite3` beside job discovery, because a posting found by
`cvme digest` and an application prepared from it are the same job.

A reference can be a full slug, part of one, or a company name; where it is
ambiguous the command says what it could have meant rather than guessing.

Check the artefact rather than the source. `cvme ats` renders the document,
reads the PDF back with the converter, and reports every place where the
machine reading differs from what was written:

```bash
uv run cvme ats resume        # render, read back, report
uv run cvme ats out/resume.pdf --json
```

The checks are the questions a parser asks: is there text, does the letterhead
yield an address, do the dates parse, do the bullets separate, are the sections
named something it maps to a field, and does the structure it recovers match
the structure you wrote. That last one is the whole question asked once, and it
is why this exists: markers that are drawn rather than typed look perfect and
extract as one undivided paragraph.

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
`2` page budget, `3` verification and `cvme ats`, `4` fetch, `5` agent,
`6` conversion, `7` a missing or inconsistent hunt.

`cvme tailor` treats verification as a gate, not a report. A document that
invents a metric is never rendered, and any PDF from an earlier run is removed
rather than left sitting beside a rejected draft.

A generated draft ends with a `## Gaps` section listing every requirement the
corpus could not answer. It is dropped at the render boundary and never reaches
a PDF: it is written for you, and it is the last thing you would send.

Generated quantitative claims must carry an `<!-- fact: id -->` citation.
Matching retains the measured subject and qualifier, so `14 facilities` does
not license `14 engineers`, and `100k`, `~100k`, and `100k+` are distinct. Fact
checking fails closed when no corpus is configured; use `--no-facts` for an
explicit prose-only check or `tailor --no-verify` to bypass the generation gate.

Job postings are untrusted input. Their text is wrapped in a per-run random
boundary with instructions to treat it only as reference data. Automated agents
run in a temporary staging directory containing only the assembled prompt, and
their draft is copied to the application directory only after the process exits.
The same holds for the report: the agent sees the posting, the corpus, and
nothing else, and it has no network access to check anything it recalls.
