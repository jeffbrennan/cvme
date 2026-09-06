# LinkedIn sync

`base.md` is the source of truth for what is true about your career. The
LinkedIn profile is a second copy of the same claims, maintained by hand, in a
web form, and it drifts the moment the resume changes. This feature makes the
profile a projection of the document instead.

The sync is one-way and the last step is manual: cvme writes a changeset and
you paste it in. That is not a shortcut, it is the ceiling — see below.

Because the paste is manual, `cvme linkedin check` audits the result against
what LinkedIn actually holds, and fails on drift. That is the part that keeps
the manual step honest.

## Why there is no API push

LinkedIn's **Profile Edit API** is real and documented. It creates, updates and
deletes positions, educations and skills under `/v2/people/id={person}/…`. It
is also **restricted to developers LinkedIn has approved through a partner
programme**.

What a self-serve developer app can get is:

| Product | Scopes | What it does |
|---|---|---|
| Sign In with LinkedIn (OpenID Connect) | `openid`, `profile`, `email` | Name, headline, picture, email. Read-only. |
| Share on LinkedIn | `w_member_social` | Post to the feed. |

None of those writes a profile section. So an automated push is not a hard
problem, it is a product LinkedIn does not sell to individual developers.
Anyone offering it is either a partner or driving a browser against LinkedIn's
terms of use, which this project will not do — the same judgement is already
recorded for job capture in `jobs/sources.py`.

cvme therefore does the part that is actually hard, which is knowing *what
changed*, and leaves the twenty seconds of pasting to you.

## How much pasting

The first run lists everything, because cvme has not recorded a profile yet:
one entry per position, plus the headline, About and skills. LinkedIn's editor
is per-entry anyway — Experience → that role → Edit is its own modal — so
there is no tooling that would make the first pass a single paste.

After `cvme linkedin record`, the changeset holds only what moved. Editing one
bullet in `base.md` produces one position to update. That is the state you
live in; the first run is a one-off.

```
$ cvme linkedin diff          # after recording, and one edited bullet
update position 'Staff Data Engineer @ Northwind Analytics'
```

## Checking against the live profile

`record` on its own is a promise: you telling cvme the paste happened. `check`
is evidence.

```bash
cvme linkedin check ~/Downloads/Profile.pdf     # one click to produce
cvme linkedin check ~/Downloads/export.zip      # a few minutes, complete
cvme linkedin check <source> --show             # print what cvme read, and stop
```

It exits non-zero on drift, so it works as a CI or cron check.

### Where the profile comes from

| Source | How | Effort | Reports |
|---|---|---|---|
| **Profile PDF** | Your profile → More → **Save to PDF** | one click, immediate | headline, About, roles, degrees |
| **Data export** | Settings & Privacy → Data Privacy → **Get a copy of your data** | emailed in minutes | all of it, including skills |

The PDF is the one to reach for. cvme already reads PDF resumes -- that is what
`cvme convert` does -- and a profile PDF is resume-shaped, so the whole path is
the existing pipeline pointed at a different document:

```
PDF ──convert──▶ markdown ──parse──▶ document IR ──project──▶ Profile
```

### Why not just fetch the public profile page

Because it is forbidden, not because it is hard.

LinkedIn's user agreement prohibits automated access, and *hiQ Labs v.
LinkedIn* settled that in 2022: a **$500,000 judgment against hiQ for breach of
that agreement**, plus a permanent injunction to stop scraping and delete
everything it had taken. The widely-quoted ruling in that case — that scraping
public pages is not a *CFAA* crime — left the contract claim untouched, and
LinkedIn won it. In practice logged-out profile views are also gated, reduced,
and served behind an auth wall from anything that looks automated.

This project already takes that position for job capture (`jobs/sources.py`
reports what it cannot reach rather than bypassing it), and the same reasoning
applies here.

### Findings

| Finding | Means | Fails |
|---|---|---|
| `missing` | in your documents, not on LinkedIn | yes |
| `stale` | on LinkedIn, but not what your documents say | yes |
| `extra` | on LinkedIn, not in your documents | only with `--strict` |

`extra` does not fail by default because a one-way sync promises "everything
`base.md` says is on the profile", not "the profile says nothing else". A
resume drops an old job for space and the profile keeping it is correct;
endorsed skills you would not claim in print are the same story. `--strict` is
for anyone who wants the profile to be exactly the document.

```
$ cvme linkedin check ~/Downloads/Profile.pdf
read profile PDF (Profile.pdf)
stale   position 'Staff Data Engineer @ Northwind Analytics'
missing position 'Data Engineer @ GreyHarbor Health'
1 missing, 1 stale
not checked  skills (this source does not report them in full)
```

### What a source will not vouch for

Every source declares which parts of a profile it actually reports, and the
audit compares only those. A profile PDF prints a "Top Skills" section holding
about three of them, so a profile with thirty skills would otherwise audit as
twenty-seven missing — a fact about the PDF dressed up as drift in your
profile. So the PDF does not vouch for skills, `check` says so on every run,
and the export is what you use when the skills list is the thing you want
checked.

The same applies to a partial download: an export of Skills alone checks
skills and says nothing about your positions. A table that is present but
empty is different, and does count — a `Skills.csv` holding only its header is
LinkedIn saying you have no skills.

### Recording from a check

`--record` writes the profile it read as the state, so whatever you have not
applied yet stays outstanding and the next `sync` is exactly the remainder.

Two things it deliberately does not do. Entries cvme does not manage are left
out, so a job you meant to keep never becomes a standing instruction to delete
it — unless you pass `--strict`, which means you do want it gone. And parts the
source could not see keep whatever was already recorded, so checking with a PDF
does not blank the skills a previous export established.

### If the read looks wrong

`--show` prints the profile cvme recovered from the source and stops, which is
the fastest way to tell a real drift from a parsing problem. For a PDF,
`cvme convert <file> --stdout` shows the markdown underneath it.

The export archive's columns are read by name through an alias table, not by
position, because LinkedIn publishes no schema for it and has renamed these
before. A file whose columns cannot be understood is an error that names the
headers actually found.

## Commands

```bash
cvme linkedin diff       # what has changed since the last recorded sync
cvme linkedin sync       # write out/linkedin-changeset.md
cvme linkedin check SRC  # audit against a profile PDF or export; fails on drift
cvme linkedin record     # mark the current documents as applied
cvme linkedin status     # sources, and what is outstanding
cvme linkedin reset      # forget the state; offer the whole profile again
```

`sync --record` records as it writes, for when you paste as you go. Prefer
`check --record`: it records what LinkedIn says rather than what you intended,
and a profile PDF is one click away.

## Design

```
base.md ──parse──┐
                 ├─merge──▶ document IR ──project──▶ Profile ──diff──▶ changeset.md
linkedin.md ─────┘                                      ▲    └─diff──▶ audit
   (optional)                                           │           ▲
                                             last recorded state    │
                              profile PDF / data export ──read──────┘
```

The audit is the same comparison read the other way round. Diffing the
projected profile against the live one turns `add` into "missing", `update`
into "stale" and `remove` into "extra", so there is one comparison engine
rather than two that can disagree.

Five decisions are worth stating.

**The overlay is a patch, not a second document.** `linkedin.md` is written in
the same grammar and holds only what should read differently: a longer About,
five more bullets under the current role. Everything it does not mention comes
from `base.md`. Two whole documents kept in step by hand is the problem this
feature exists to solve, and shipping a second one would have recreated it.

Entries match on role, organisation and **start** date. Not the end date: the
role most likely to be extended in an overlay is the one that reads "Present"
today, and matching on it would silently append a duplicate job the day you
left.

**The diff is against what cvme last applied.** The comparison that matters for
a one-way sync is "what have I written since I last pushed". The state lives in
`.cvme/linkedin/state.json` and is written only when you say a sync was
applied, so an abandoned paste leaves the changes outstanding.

Nothing cvme runs can see your profile on its own, so `record` does not claim
to: it is a separate step because recording a sync that never happened is the
one lie that would make every later diff wrong. `check` is how that claim gets
evidence behind it, which is why `check --record` is the better habit.

**Over-long fields are refused, not truncated.** LinkedIn's composer caps the
headline at 220 characters, About at 2,600 and a role description at 2,000. A
sync that quietly cut a sentence in half would put it on a public profile.
cvme names every over-long field and stops before writing anything.

**Sections it cannot map are reported.** There is no LinkedIn field for a
`Projects` section, so cvme says so rather than dropping it silently.

**Text is normalised on the way into the model, not at comparison time.** A
description that has been through LinkedIn's storage and back comes home with
different trailing whitespace, and a trailing space is not a claim that
changed. Normalising at the boundary means the sync diff and the audit are
comparing the same thing.

## The mapping

| `base.md` | Profile | Limit |
|---|---|---|
| `headline:` frontmatter, then `title:`, then the current role | Headline | 220 |
| untitled lead section, or `## Summary` | About | 2,600 |
| `## Experience` entries | Positions | title 100, description 2,000 |
| `## Education` entries | Education | |
| `## Skills` bullets, split per term | Skills | 50 skills, 100 each |
| `## Gaps` | nothing — it is addressed to you | |

A lone date on a degree line is a graduation, so it becomes the *end* date. On
a position a lone date means you started then and are there still. Reading the
degree the same way would put "2020 – Present" on a master's you finished.

Reading a degree back out of a PDF needs the same rule in reverse. A PDF has no
paragraphs, so the degree beneath a school heading arrives as loose prose with
the award date buried in it, sometimes with the next line run onto the end. The
PDF reader splits that line at the first real month-year — real, because "Master
of Science 2020" names no month and a looser pattern would eat the word before
the year.

Skills read the way a resume writes them. `Python (advanced)` is the skill
`Python`: the bracket qualifies it. `Orchestration (airflow, dagster)` is
`airflow` and `dagster`: the bracket is a list and the label is a category.
Whether the bracket holds a separator is what tells the two apart.

Markup does not survive: LinkedIn renders none of it, so `**bold**` would
arrive as literal asterisks. Links keep their target — `[docs](https://x)`
becomes `docs (https://x)` — because a URL on a profile is only reachable if
it is written out.

## Configuration

Everything below is the default; none of it needs writing.

```toml
[linkedin]
document = "resume"
# overlay = "base/linkedin.md"   # unset: linkedin.md beside the resume, if present
fields = ["headline", "summary", "positions", "educations", "skills"]
changeset = "linkedin-changeset.md"
```

Drop a name from `fields` to keep a section you curate on LinkedIn out of the
sync entirely. It stops producing changes rather than producing one last
removal of everything in it.
