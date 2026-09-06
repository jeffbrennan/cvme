# LinkedIn sync

`base.md` is the source of truth for what is true about your career. The
LinkedIn profile is a second copy of the same claims, maintained by hand, in a
web form, and it drifts the moment the resume changes. This feature makes the
profile a projection of the document instead.

## What LinkedIn actually allows

Read this before designing anything around the API.

The **Profile Edit API** is real and documented. It creates, updates and
deletes positions, educations, skills, certifications and the rest, under
`/v2/people/id={person}/…`. It is also **restricted to developers LinkedIn has
approved through a partner programme**.

What a self-serve developer app can get today is:

| Product | Scopes | What it does |
|---|---|---|
| Sign In with LinkedIn (OpenID Connect) | `openid`, `profile`, `email` | Name, headline, picture, email. Read-only. |
| Share on LinkedIn | `w_member_social` | Post to the feed. |

None of those writes a profile section. So for almost everyone, a fully
automated push does not exist — not because it is hard, because LinkedIn does
not sell it. Anyone claiming otherwise is either a partner or driving a browser
against LinkedIn's terms of use.

cvme therefore ships two transports and defaults to the one that works.

## The two transports

### `--transport review` (default)

Writes `out/linkedin-changeset.md`: every field that has changed since the last
recorded sync, in the order LinkedIn's own editor presents them, with the new
text in a fenced block to copy and where in the UI to paste it.

This needs no LinkedIn app, no OAuth, and no approval. The manual step is real,
but it is small and bounded: not "reconcile a profile against a PDF", but
"paste these two fields".

### `--transport api`

The real thing, against the documented endpoints. It will return 403 unless
your app carries a Profile Edit permission. It is implemented so that the day
that access arrives, the sync is a flag rather than a project — and the
projection, the diff and the state are shared with the review transport, so
they are exercised either way.

## Design

```
base.md ──parse──┐
                 ├─merge──▶ document IR ──project──▶ Profile ──diff──▶ Changeset
linkedin.md ─────┘                                      ▲                  │
   (optional)                                           │           ┌──────┴──────┐
                                             last recorded state    review      api
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

**The diff is against what cvme last applied, not against LinkedIn.** The
comparison that matters for a one-way sync is "what have I written since I last
pushed". It also has to be, because reading positions back needs the same
partner access as writing them. The state lives in `.cvme/linkedin/state.json`
and is written only when a sync is applied, so an abandoned push leaves the
changes outstanding.

For `review` that means cvme cannot know you pasted the file in, so it does not
claim you did. `cvme linkedin record` is the confirmation, and it is a separate
step on purpose.

**Over-long fields are refused, not truncated.** LinkedIn's composer caps the
headline at 220 characters, About at 2,600 and a role description at 2,000. A
sync that quietly cut a sentence in half would put it on a public profile.
cvme names every over-long field and stops.

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

## Credentials

Only needed for `--transport api`.

* Stored at `~/.config/cvme/linkedin.json` (or `$XDG_CONFIG_HOME/cvme/`), never
  in the project — `cvme.toml` is committed and a client secret is not.
* Created `0600` inside a `0700` directory, opened through `os.open` so the
  file is never briefly world-readable. A file that other users can read is
  **refused rather than repaired**: it may already have been read, and fixing
  the mode would hide that.
* `CVME_LINKEDIN_CLIENT_ID` / `_SECRET` override the file, for CI or for anyone
  keeping the secret in a password manager.
* The flow is the authorization code grant over a loopback redirect bound to
  `127.0.0.1`. The `state` parameter is 32 random bytes per run, compared with
  `secrets.compare_digest` before the code is exchanged. LinkedIn is a
  confidential client, so there is a client secret and no PKCE to use instead.
* Nothing prints the secret. `cvme linkedin status` shows the last four
  characters of the client id and whether a secret and token exist.

## Commands

```bash
cvme linkedin diff       # what has changed since the last recorded sync
cvme linkedin sync       # write out/linkedin-changeset.md
cvme linkedin record     # mark the current documents as applied
cvme linkedin status     # credentials, sources, and what is outstanding
cvme linkedin reset      # forget the state; offer the whole profile again

cvme linkedin setup      # register a LinkedIn app, once, for --transport api
cvme linkedin login
cvme linkedin logout
cvme linkedin sync --transport api
```

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
