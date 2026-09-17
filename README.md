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
uv tool install cvme         # or `uv tool install .` from this checkout
cvme init ~/Documents/job_hunt/2026
cd ~/Documents/job_hunt/2026
cvme render resume
```

To drive it from another project — a repo that holds your documents, say —
add it as a dependency instead:

```bash
uv add cvme
uv run cvme render resume
```

Fonts and Typst templates ship inside the wheel, so a released install needs
nothing else on the machine. `cvme doctor` reports what it found.
Publishing is described in [docs/releasing.md](docs/releasing.md).

The generated application bundles live under `applications/` in that
workspace by default. Set `project.applications_dir` in `cvme.toml` to put them
elsewhere; absolute paths and paths relative to the config file both work.

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

A recruiter who asks for your resume is not a posting: there is nothing to
tailor to and nothing to file. `cvme send` renders the untailored document once
per role title, named for the recipient rather than for the project:

```bash
uv run cvme send 'Senior Data Engineer'
uv run cvme send 'Data Engineer' 'Senior Data Engineer' 'Staff Data Engineer'
uv run cvme send 'Data Engineer' --md --dir outbox
```

Output goes to `project.send_dir` (`send/` by default) as
`<name>_<normalized_role>.pdf`, using the same title normalisation the hunt
filenames use: grades and qualifiers are dropped, `Sr.` becomes `senior`, and
formal levels such as Senior, Staff and Principal are kept. Two titles that
normalise to one filename are refused rather than silently overwritten. The
PDF is rendered rather than copied, so a role name never ends up attached to a
stale render.

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

Capture tries ATS APIs for supported ATS URLs, then JSON-LD and site-specific
HTML for public pages. Saved HTML uses the same JSON-LD and site selectors
before falling back to page text. Entity-escaped JSON-LD descriptions are
converted to Markdown. If JSON-LD has no salary, capture reads the range and
any stated pay period from the description into `salary`; an explicit
structured salary takes precedence.

Both LinkedIn postings [1000000001](https://www.linkedin.com/jobs/view/1000000001/)
and [1000000002](https://www.linkedin.com/jobs/view/1000000002/) were fetched
successfully through public HTTP on 2026-09-05. Recorded job-bearing HTML
fragments cover their descriptions, metadata, salaries, and cache reuse in
offline tests. Sites may still require login or challenge completion; use
saved HTML or pasted text when public HTTP cannot retrieve the posting.

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
        v1/
            morgan_avery_staff_data_engineer.md
            morgan_avery_staff_data_engineer.pdf
            morgan_avery_staff_data_engineer_cover_letter.md
            morgan_avery_staff_data_engineer_cover_letter.pdf
        v2/  # the next version, with the same filenames
```

Running it again on the same posting adds version 2 beside version 1 rather
than overwriting it, because the comparison worth having is against what you
nearly sent. `--new` forces a separate hunt instead. Filenames use the candidate name from the base document
and the normalized posting title: `<name>_<title>.md` and `.pdf`. Cover letters
add `_cover_letter`. Numeric grades, Specialist qualifiers, and trailing
department/location text are removed; explicit Senior, Staff, Principal and
Lead levels are preserved. Grade III is not automatically promoted to Senior.
The posting and document contents retain their original titles. Both `prep`
and `tailor` use this naming convention. `prep` stores revisions under `v1/`,
`v2/`, etc., and still recognizes legacy numbered files when choosing the next
version. `hunt_stem` is retained only for that legacy lookup.

To finish drafts written by hand or by an assistant in your current session,
put them in a directory named by document key (`base.md` and `cover_letter.md`
for a project with those documents), plus `report.md` for the role brief:

```bash
cvme prep path/to/posting.md --drafts-dir path/to/drafts --note 'Azure platform emphasis'
```

This imports the drafts without invoking an agent, applies the same citation
verification and PDF page limits, and records a new application version. The
computed fit/pay/work-life block is prepended to the imported brief. All selected
drafts must exist and be nonempty before a hunt is changed. Use `--no-report`
if no brief is supplied, or `-d base` to import only that document. Do not combine
`--drafts-dir` with `--agent`. Source drafts remain untouched.

### The fit score

The score is computed, and it shows its working. A model asked to rate a fit
returns a number that reads well and cannot be checked, which is the failure
`cvme verify` exists to catch everywhere else.

The score has four axes, each out of 100 and reported on its own. **Skills** is
the posting's terms from a packaged vocabulary of tools, practices and domains,
weighted by how often the posting names each one and looked for in your fact
corpus and base documents. **Role and logistics** is the title, the stated years
of experience, and the location. **Culture** is the posting's own reading of the
hours. **Domain** is the cause the engineering serves: it starts neutral at 50
and your preferences move it up or down. A weighted composite ranks the posting,
and a gated axis caps it, so a wrong domain or a bad week cannot be carried by a
strong skills match. Extend the vocabulary for your field under
`[fit.extra_terms]` in `cvme.toml`. A posting your own filters exclude scores
zero and says which filter did it.

#### Personal preferences: WANTS.md

The axes answer four questions: skills asks whether the work is doable, role
whether the seat is right, domain whose cause the engineering serves, and
culture whether the week is shaped the way you want. Every preference rule is
tagged with the axis it moves. Add a preferences file to configure them
(relative to `cvme.toml`):

```toml
[fit]
wants = "WANTS.md"
```

`WANTS.md` contains YAML frontmatter for deterministic scoring and ordinary
Markdown notes for the written company/role assessment. For example:

```yaml
---
version: 1
weights:
  skills: 35
  role: 20
  domain: 35
  culture: 10
gate:
  domain: 30
  culture: 25
rules:
  - name: Modern platform not mentioned
    weight: -8
    axis: role
    when: absent
    any_of: [Databricks, Snowflake]
    reason: Prefer a modern data platform; confirm the stack if unstated.
  - name: Platform ownership
    weight: 8
    axis: role
    any_of: [platform engineering, data platform, developer experience]
    reason: I want to build infrastructure other engineers use.
  - name: Mission-driven domain
    weight: 12
    axis: domain
    any_of: [climate, renewable energy, clean energy, decarbonization]
    reason: Favour the causes you want to serve; the same list scores theirs against you.
  - name: Grind culture cues
    weight: -18
    axis: culture
    any_of: [intense urgency, thrive under pressure, whatever it takes]
    reason: I want a calmer week, and volunteering this language is the tell.
  - name: AI startup
    weight: -15
    axis: domain
    any_of: [AI platform, AI-powered]
    requires_any: [startup, early stage, venture backed]
    reason: Prefer organizations with a longer operating history.
---
# What I want next
A calm, product-focused team, platform ownership, and honest hours.
Ask about testing standards and the balance of maintenance vs. new work.
```

Each rule needs a unique `name`, nonzero integer `weight` (-40 to +40),
`reason`, and nonempty `any_of` phrase list. Optional fields:

| field | default | meaning |
|---|---|---|
| `axis` | `role` | Which axis the weight moves: `skills`, `role`, `culture`, or `domain` |
| `when` | `present` | `present`: any phrase appears; `absent`: none appears |
| `scope` | `posting` | Match `company`, `title`, `description`, or all three |
| `requires_any` | `[]` | If supplied, at least one of these phrases must also appear |
| `unless_any` | `[]` | Suppress the rule if any of these phrases appears |

Matching ignores case and punctuation and uses whole tokens (`SAS` does not
match `Sassy`). Each rule counts once regardless of repetitions or matching
aliases. Empty capture fields do not trigger absence rules. Missing mentions
are evidence about the captured posting, not proof about an employer. Context
guards help, but phrase rules do not infer an employer's industry, age, or
engineering quality. Prefer specific industry phrases over incidental words
like “finance,” and scope named-employer preferences to `company`.

`cvme prep` (including `--fit-only`) scores each axis, then ranks the posting by
a weighted composite of them. The `weights` table sets the composite, normalised
by their sum (defaults 35/20/35/10 for skills/role/domain/culture). A `gate`
entry caps the composite at an axis's own score when that axis falls below its
floor (defaults: domain 30, culture 25), so a strong skills match cannot rescue
a posting whose domain or hours you are avoiding. Exclusion filters still force
zero. Reports show every axis, its weight, the gates that fired, and every
matched rule with its phrases, reason, and axis. The stored application carries
the composite and the four axis scores, and `cvme apps list` can sort by any of
`fit`, `skills`, `role`, `domain`, or `culture`. `max_adjustment` is accepted
for older files but is no longer what decides the ranking. With no configured
file, every posting is scored on the axes with no preference weights. A
configured missing or invalid file raises an error rather than silently dropping
your preferences.

Only the report prompt receives WANTS notes. They never enter the skills
corpus, verification evidence, or resume/cover-letter prompts. Do not add
`WANTS.md` to `project.facts`. Existing reports/scores are not rewritten;
use `prep --fit-only` to review a posting under your current preferences.

What that buys is the second half of `report.md`: which of the posting's own
requirements your corpus answers, and which it does not.

```
**Fit 58/100 (fair)**

| axis | score | weight | what moved it |
|---|---|---|---|
| skills | 50 | 35% | 7/14 terms, weighted by mention count |
| role & logistics | 88 | 20% | title 15/15, experience 15/15, location 5/10 |
| domain | 62 | 35% | the cause the engineering serves |
| culture | 50 | 10% | the posting's own reading of the hours |

**Answered.** airflow, data quality, docker, kubernetes, python, spark, sql

**Not answered.** go, kafka, rust, scala, snowflake, terraform, typescript

**Pay** $150k-190k (as stated: $150,000 - $190,000 per year)

**Work-life 50/100 (busy)**

| signal | worth | what it predicts |
|---|---|---|
| unlimited pto | -12 | no accrued balance to pay out, and no floor on what is actually taken |
| fast paced | -8 | the pace is advertised before the work is, which is a ranking |
| parental leave | +10 | the leave is paid and its length is written down |
```

The rest of the report is written by the agent from the posting and your
corpus, with anything it recalls rather than reads kept under its own
`## From general knowledge (unverified)` heading. The score is never asked of
the agent, so nothing in the report asserts a number that cannot be recomputed.

### What the posting says it pays, and what it says about the hours

Both are read from the posting and reported beside the fit, because a strong
match that pays under your current job, or that advertises itself with "we are
a family" and "unlimited PTO", is not the one to spend the evening on.

Pay is annualised so the column compares: a range, a single figure, or an
hourly rate all become one number, and the words it was read from are kept
beside it. A figure is only believed where the posting marks it as money, so
"5+ years" and "10,000 records per year" are not read as salaries.

The work-life score is the same argument as the fit score. Asking a model what
a company is like to work at produces an answer worth nothing; what can be
checked is the vocabulary the posting chose. It starts at 60, subtracts what
each cost phrase is worth, adds what each lift is worth, and names every
phrase it found:

```
work-life 34/100 (busy)
   -12 unlimited pto: no accrued balance to pay out, and no floor on what is actually taken
   -10 many hats: the role is undefined by design, and expands to fit the gaps
    -8 fast paced: the pace is advertised before the work is, which is a ranking
   +10 parental leave: the leave is paid and its length is written down
```

Costs include `996`, `we are a family`, `rockstar`, `unlimited PTO`,
`wear many hats`, `lean team`, `full stack`, `fast paced`, `hustle`,
`always on`, `crunch`, `competitive salary` and `comfortable with ambiguity`.
Lifts include `four day work week`, `no on call`, `collective bargaining`,
`25 days of PTO`, `paid parental leave`, `sabbatical`, `core hours`,
`blameless postmortems`, `company shutdown` and `sustainable pace`. A phrase
counts once however often it appears, and a promise is not charged for what it
promises to avoid: "no on-call" does not also score as "on call". Where a
posting says nothing either way the band is `unstated`, because silence is not
the same as sixty.

Add your own tolerances in `cvme.toml`; naming a packaged phrase replaces its
weight rather than doubling it:

```toml
[culture.extra_costs]
"relocation required" = 12

[culture.extra_lifts]
"no travel" = 8
```

### Tracking what you have not sent

```bash
cvme apps list                       # prepared and unsent, best fit first
cvme apps list --sort salary         # or wlb, age, waiting, updated, company, ...
cvme apps list --sort age --reverse  # newest first instead of oldest
cvme apps list --status applied,interviewing
cvme apps list --all
cvme apps show northwind             # every version, and what changed between them
cvme apps rescan                     # re-read every posting for pay and hours
cvme apps submit northwind           # sent: file it under applied/
cvme apps status northwind interviewing --note 'call tuesday'
cvme apps status northwind rejected
```

```
prepared, not yet sent, by fit
    fit domain skills company             title                   salary       work-life  where   age  status    v
 89 strong     77     82 Acme Analytics      Senior Data Engineer             -    0 grind  onsite   6d  prepared  2
 82 strong     62     71 Globex              Senior Data Engineer             -   unstated  hybrid   4d  prepared  1
 81 strong     62     69 Hypergrowth Labs    Founding Data Engineer  $140k-170k    0 grind  hybrid   2d  prepared  1
 78 strong     77     64 Northwind Health    Staff Data Engineer     $185k-215k  100 calm   remote   1d  prepared  1

4 prepared  median pay 200k of 2 stated  mean work-life 33 of 3 stated
```

`--sort` takes `fit`, `salary`, `wlb`, `age` (longest sitting first), `waiting`
(longest since it was sent), `updated`, `company`, `title`, `status`,
`versions`, and the axes `skills`, `role`, `domain` and `culture`; `--reverse`
flips whichever it is. `--columns` picks and orders the cells, from
`fit, skills, role, domain, culture, company, title, salary, wlb, age, waiting,
status, versions, where, location, note, slug, url, directory`. Where the
terminal is too narrow to hold the default set, the rightmost columns are
dropped rather than every column squeezed, and the listing says which.

`cvme apps rescan` re-reads each captured `posting.md` for pay and hours and
updates the table -- after the lexicon changes, or for applications prepared
before those columns existed. It leaves the fit score alone: that is measured
against your corpus and belongs to the run that produced the documents.

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

### Styles

A style is a TOML file of resolved numbers in
[`src/cvme/style/presets`](src/cvme/style/presets). Every preset is one column,
standard section names, real bullet glyphs and extractable text -- the things a
parser reads -- so the choice between them is a choice about the human reader
only.

| Preset | Body | Name | The idea |
|---|---|---|---|
| `sans` | Source Sans 3 | Fira Code | One accent, monospace section headings, a rule under the letterhead and a hairline under each section. |
| `serif` | Source Serif 4 | Fira Code | The same design in a text serif, with the leading it needs. |
| `standard` | Carlito | Fira Code | The reference layout. No rules, no colour, no accent. |
| `compact` | Carlito | Fira Code | `standard`, tightened, for a page and a half of content. |
| `airy` | Carlito | Fira Code | `standard`, opened up, on a two-page budget. |

`sans` and `serif` are the same set of decisions in two type families, which is
why there are two of them and not six: a variation that only changes the font
is a font argument, not a style.

### Accents

An accent is the one colour a document spends. Setting it moves the name, the
section headings, the rule under the letterhead and the links together, because
the presets leave all four unset and falling back to it:

```bash
uv run cvme render base --style sans --accent navy
uv run cvme render base --style sans --accent '#8a1538'
```

Named colours are in [`src/cvme/style/color.py`](src/cvme/style/color.py):
black, graphite, slate, navy, teal, forest, maroon, burgundy, plum, rust. A hex
value is checked against a 4.5:1 contrast floor and refused with the measured
ratio if it fails, because a brand colour chosen for a white logo on a coloured
field is routinely too pale to set type in.

The presets ship near-black, so a document is monochrome until asked otherwise.
To match a company you are applying to, name them in `cvme.toml` and `cvme prep`
does the rest:

```toml
[accent]
default = "graphite"

[accent.companies]
"Northwind Analytics" = "#004b87"
"Ridgeway Health" = "forest"
```

Every other knob a preset sets is a field on `Style`, and any of them overrides
from the command line:

```bash
uv run cvme render resume.md --style sans --set section_rule=0
uv run cvme render resume.md --style serif --set link_underline=true
```

Colour fields fall back rather than default: an empty `name_color` is `accent`
before it is `ink`, and an empty `date_color` is `muted` before it is `ink`. A
preset therefore reads as the short list of decisions it actually makes.

The authoring grammar is [`src/cvme/md/GRAMMAR.md`](src/cvme/md/GRAMMAR.md).
`tests/fixtures/resume.md` is a complete worked example.

## Keeping LinkedIn in step

`base.md` is the source of truth; the profile is a projection of it. `cvme
linkedin` reports what has changed since the last time you pushed, so an edit
to one bullet is one field to update rather than a profile to re-read.

```bash
cvme linkedin diff       # what has changed since the last recorded sync
cvme linkedin sync       # write out/linkedin-changeset.md
cvme linkedin record     # mark the current documents as applied
cvme linkedin status
```

The paste is manual, because LinkedIn's Profile Edit API is partner-only and
driving a browser to write a profile would violate its terms. `cvme linkedin
check` audits the result against what LinkedIn actually holds and exits
non-zero on drift, so it works as a CI or cron check.

```bash
cvme linkedin check ~/Downloads/Profile.pdf   # More > Save to PDF: one click
cvme linkedin check ~/Downloads/export.zip    # the data export: slower, complete
cvme linkedin check <source> --record         # record what LinkedIn says
cvme linkedin check <source> --show           # print what cvme read, and stop
```

Findings are `missing` (in your documents, not on LinkedIn), `stale` (on
LinkedIn, out of date) or `extra` (on LinkedIn, not in your documents). The
first two fail; `extra` only fails under `--strict`, because a resume drops an
old job for space and the profile keeping it is not drift.

An optional `linkedin.md` beside the resume carries the longer copy a profile
has room for. It is a patch, not a second resume: write only what should read
differently, and everything else comes from `base.md`;
`base/linkedin.md.example` is a template to rename.

The opt-in browser capture reads your own signed-in profile instead of a PDF.
**LinkedIn's user agreement prohibits automated access and does not carve out
your own profile, so the account risk is yours to opt into.**

```bash
uv sync --extra browser && uv run playwright install chromium
cvme linkedin login            # a window opens; you sign in
cvme linkedin check --browser
```

The full design -- the changeset format, per-section capture status, what each
source vouches for, and the mapping table -- is in
[docs/linkedin-sync.md](docs/linkedin-sync.md).

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

## Repository content

This is a public tool and its packaging is public too. Every example in the
repository, the docs, and the tests is synthetic: `example.com` contacts,
invented employers such as Northwind Health, and placeholder names such as
Morgan Avery. Real documents, contact details, and captured source material are
never kept here, because a published version cannot be unpublished and a commit
cannot be unshared.

Two mechanisms keep that true:

- **The sdist is narrow.** It contains only `src/`, `README.md`, and `LICENSE`.
  Design docs and test fixtures are development material and are not packaged.
- **A scan fails the build.** `scripts/check_private.py` reports an email that
  is not a reserved example domain, and any term in a private list. CI runs it
  on every change, and the release workflow runs it against the built sdist and
  wheel before upload, so nothing reaches an index unscanned. The list is
  supplied through the `CVME_PRIVATE_TERMS` repository secret, which keeps the
  public repository from containing the words it forbids; without it the
  generic patterns still run.
