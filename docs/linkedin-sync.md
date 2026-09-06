# LinkedIn sync

`base.md` is the source of truth for what is true about your career. The
LinkedIn profile is a second copy of the same claims, maintained by hand, in a
web form, and it drifts the moment the resume changes. This feature makes the
profile a projection of the document instead.

The sync is one-way and the last step is manual: cvme writes a changeset and
you paste it in. That is not a shortcut, it is the ceiling — see below.

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

## Commands

```bash
cvme linkedin diff       # what has changed since the last recorded sync
cvme linkedin sync       # write out/linkedin-changeset.md
cvme linkedin record     # mark the current documents as applied
cvme linkedin status     # sources, and what is outstanding
cvme linkedin reset      # forget the state; offer the whole profile again
```

`sync --record` does both in one step, for when you paste as you go.

## Design

```
base.md ──parse──┐
                 ├─merge──▶ document IR ──project──▶ Profile ──diff──▶ changeset.md
linkedin.md ─────┘                                      ▲
   (optional)                                           │
                                             last recorded state
```

Four decisions are worth stating.

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

cvme cannot see your profile, so it does not claim to. `cvme linkedin record`
is a separate step on purpose: recording a sync that never happened is the one
lie that would make every later diff wrong.

**Over-long fields are refused, not truncated.** LinkedIn's composer caps the
headline at 220 characters, About at 2,600 and a role description at 2,000. A
sync that quietly cut a sentence in half would put it on a public profile.
cvme names every over-long field and stops before writing anything.

**Sections it cannot map are reported.** There is no LinkedIn field for a
`Projects` section, so cvme says so rather than dropping it silently.

## The mapping

| `base.md` | Profile | Limit |
|---|---|---|
| `headline:` frontmatter, then `title:`, then the current role | Headline | 220 |
| untitled lead section, or `## Summary` | About | 2,600 |
| `## Experience` entries | Positions | title 100, description 2,000 |
| `## Education` entries | Education | |
| `## Skills` bullets, split per term | Skills | 50 skills, 100 each |
| `## Gaps` | nothing — it is addressed to you | |

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
