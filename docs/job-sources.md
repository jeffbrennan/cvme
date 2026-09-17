# Getting a job description

cvme fetches one posting at a time, from a URL you give it. This records the
order the extractors are tried in, the fetch failure modes, and what the tool
deliberately will not do.

## Live verification, 2026-09-05

Public HTTP works for the two LinkedIn URLs tested with
`cvme job fetch --no-cache` and the tool's identifying user-agent:

| Posting | Extractor | Captured salary |
|---|---|---|
| [Northwind Health, Data Engineer III](https://www.linkedin.com/jobs/view/1000000001/) | JSON-LD, with an entity-escaped HTML description | $110000 - $165000 per year |
| [Regional Transit Authority, Specialist Data Engineer](https://www.linkedin.com/jobs/view/1000000002/) | Public HTML selectors; no JobPosting JSON-LD | $115,000 - $135,000 per year |

Recorded fixtures retain job-bearing fragments and omit unrelated page chrome
and tracking. The tests verify live-response parsing, saved-page parsing,
salary extraction, metadata, Markdown round trips, and cache reuse. Browser
automation is not implemented; ATS and Indeed paths retain their offline
coverage, and this verification only exercised LinkedIn live.

## Bot challenges (2026-09-13)

Some aggregators sit behind a Cloudflare managed challenge and answer the
honest `cvme` user-agent with `403` and a "Just a moment..." interstitial:
the whole site, every route, whatever headers are sent. [HiringCafe](https://hiringcafe.com)
is one, and its postings carry a proper `JobPosting` JSON-LD, so the blocker
is the fetch and nothing else.

When a response looks like a challenge, the fetcher retries the same URL
through `curl_cffi`'s browser TLS profiles, `chrome120` then `safari17_0`
(order deliberate: 120 passes where newer fingerprints do not). The page this
returns is the page a browser is served, and the existing JSON-LD extractor
parses it unchanged. The tier is reported as `jsonld` with the real source
name; a challenge that cannot be passed falls through to the same
save-or-paste message as any other failed fetch. One profile answered
HiringCafe during the verification: `chrome124` returned `403` and `chrome120`
returned the posting.

This is a deliberate posture question rather than a technical one. It does not
solve a challenge, plant a cookie, or spoof a human: it shapes the TLS and
header fingerprint like the browser already looking at the page. It is closer
to reading the page a browser would get than to the vendored mobile API key
this project declined, but it is still presenting as something the request is
not, and it is recorded here so that choice stays visible.

## Tier ladder

These are extraction tiers. Underneath them the fetch itself retries a bot
challenge through browser TLS profiles (see *Bot challenges* above), and the
tiers below run on whatever HTML that returns.

0. **ATS API**, when the URL is or resolves to Greenhouse, Lever or Ashby.
   These have documented, public, no-auth JSON APIs. A large share of postings
   on LinkedIn and Indeed are mirrors of a posting hosted on one of them, so
   following the "apply on company site" link gives better text through a
   front door.
1. **JSON-LD** from whatever HTML we hold. LinkedIn, Indeed and every major
   ATS emit `<script type="application/ld+json">` with `@type: JobPosting`, a
   documented standard with named fields rather than a CSS selector that rots
   on the next redesign. This is the primary extractor everywhere.
2. **Site-specific HTML parse**, selectors in `selectors.toml` as data.
3. **Browser**, driving the user's own persistent Chromium profile so a
   one-time login is remembered. For sites that need a signed-in session.
4. **Manual**: paste, a saved `.html`, or the clipboard. First-class, because
   for a personal tool fetching one page, "paste it" is a perfectly good answer
   and it never breaks.

## Decisions

- **Do not vendor Indeed's mobile API key.** Indeed's GraphQL endpoint is
  reachable with a hardcoded `indeed-api-key` lifted from its iOS app, along
  with an app user-agent and app-info headers. That is impersonating a
  first-party mobile client, a different posture from reading a page a browser
  would serve, and it rests on one credential Indeed can rotate. A user who
  wants that path can configure it, and owns that choice.
- **Do not ship credential-based LinkedIn login.** A browser profile the user
  logged into themselves is a different thing from cvme holding their password.
- **Do not build search.** One URL at a time is the whole requirement, and it
  keeps the tool on the right side of the volume question.
- **Impersonate the browser TLS profile, do not drive one.** For a
  Cloudflare-challenged aggregator the retry is `curl_cffi`'s fingerprint
  rather than Playwright: one request, no browser install, and it returns the
  page a browser would be served. The browser tier stays for sites that need a
  signed-in session.
