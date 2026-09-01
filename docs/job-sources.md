# Getting a job description: what already exists

Research done before writing any scraper, to avoid rebuilding what is already
solved and to avoid rebuilding something that has already stopped working.

Verified from this environment where marked. LinkedIn, Indeed and both
companies' developer docs are blocked by the egress proxy here, so anything
about their live behaviour is inferred from library source rather than
observed, and is marked accordingly.

## Official APIs

Neither company offers what this tool needs.

- **LinkedIn.** The Talent Solutions job APIs are partner-gated, and they exist
  for *writing* postings into LinkedIn, not for reading arbitrary public ones.
  There is no public "fetch this job by URL" endpoint. *(From prior knowledge;
  the docs are blocked here, so treat as unverified.)*
- **Indeed.** The old Publisher Job Search API was retired. What remains is
  partner-oriented (Job Sync for ATS vendors, Indeed Apply). *(Same caveat.)*

So every option below is scraping, with the licence and durability questions
that implies.

## Libraries

Versions and dates verified against PyPI on 2026-09-01.

| Package | Version | Last release | Approach | Fetch one job by URL? |
|---|---|---|---|---|
| `python-jobspy` | 1.1.82 | 2025-07-28 | HTTP; LinkedIn anonymous, Indeed GraphQL | No, search only |
| `linkedin-jobs-scraper` | 7.0.10 | 2026-08-22 | Selenium, authenticated | **Yes** (`scrape_job`) |
| `linkedin-scraper` | 3.1.2 | 2026-04-10 | Async, profiles/companies/jobs | Partial |
| `linkedin-api` | 2.3.1 | 2024-11-07 | Unofficial Voyager API, your credentials | Yes |
| `extruct` | 0.18.0 | 2024-11-08 | schema.org extraction from HTML | N/A (a parser) |

### The finding that matters

`linkedin-jobs-scraper` shipped 6.x and 7.x within the last month and **has no
anonymous strategy at all** — only `authenticated_strategy.py`. Its source says
of a single job fetch:

> A standalone `/jobs/view/<id>` page is fully obfuscated in the scraper's
> variant, so the job is opened inside a search context:
> `/jobs/search/?currentJobId=<id>` renders the full semantic detail panel.

It also masks the headless user-agent before any authenticated request, and
expects a persistent Chrome profile that a human has logged into once.

`python-jobspy`, by contrast, fetches `https://www.linkedin.com/jobs/view/{id}`
anonymously with browser headers and parses `div.show-more-less-html__markup`.
That is the approach the original plan proposed as its LinkedIn HTTP tier. It
has not had a release in thirteen months, and the actively maintained library
has dropped exactly that approach.

**Conclusion: the anonymous LinkedIn HTTP tier in the plan is probably dead.**
Do not build it as a primary path. LinkedIn now realistically requires a
logged-in browser session, which means it requires the user's own browser
profile.

### Indeed

`python-jobspy` reaches Indeed through `https://apis.indeed.com/graphql` and
reports no rate limiting, which makes it by far the most robust of the two.
The mechanism deserves stating plainly, because it is not "fetching a public
page": it sends a hardcoded `indeed-api-key` lifted from Indeed's iOS app,
along with an iOS app user-agent and an `indeed-app-info` header naming the app
version. It is impersonating a first-party mobile client.

That is a different posture from reading a page a browser would serve you, and
it is worth deciding deliberately rather than adopting because a library made
it easy. It is also fragile in a specific way: the whole thing rests on one
credential that Indeed can rotate, and when they do there is no fallback.

## The reframe

Every library above is built for **search**: a query and a location, returning
many jobs, at volume, needing proxies. cvme needs something else entirely — one
URL, typed by a person, for a page they already have open in another tab.

That difference is why taking a dependency on JobSpy would be a poor trade: we
would import a search framework, use perhaps five percent of it, inherit its
staleness, and still not have the by-URL path we actually need.

Take its *knowledge* instead — endpoints, headers, selectors — and write the
narrow thing.

## Two better sources than either site

- **schema.org JSON-LD.** LinkedIn, Indeed and every major ATS emit
  `<script type="application/ld+json">` with `@type: JobPosting`. It is a
  documented standard with named fields, not a CSS selector that rots on the
  next redesign. This should be the primary extractor everywhere, tried before
  any site-specific parsing. `extruct` does it, though thirty lines of stdlib
  does it too.
- **The ATS underneath.** A large share of postings on LinkedIn and Indeed are
  mirrors of a posting hosted on Greenhouse, Lever, Ashby or Workday, and the
  first three have documented, public, no-auth JSON APIs
  (`boards-api.greenhouse.io/v1/boards/<org>/jobs`,
  `api.lever.co/v0/postings/<org>`, `api.ashbyhq.com/posting-api/job-board/<org>`).
  Following the "apply on company site" link and reading the canonical posting
  gives better text than the aggregator's copy, and does so through a front
  door. *(Endpoints from prior knowledge; blocked from here, so unverified.)*

## Revised tier ladder

Replaces §6 of the implementation plan.

0. **ATS API**, when the URL is or resolves to Greenhouse, Lever or Ashby.
1. **JSON-LD** from whatever HTML we hold.
2. **Site-specific HTML parse**, selectors in `selectors.toml` as data.
3. **Browser**, driving the user's own persistent Chromium profile so a
   one-time login is remembered. For LinkedIn this is now the only tier likely
   to work; for Indeed it is the alternative to impersonating the mobile app.
4. **Manual**: paste, a saved `.html`, or the clipboard. First-class, because
   for a personal tool fetching one page, "paste it" is a perfectly good answer
   and it never breaks.

## Decisions

- **Do not vendor Indeed's mobile API key.** Ship tier 3 for Indeed instead. A
  user who wants the GraphQL path can configure it, and owns that choice.
- **Do not ship credential-based LinkedIn login.** `linkedin-api` warns in its
  own README that it may violate LinkedIn's terms and risks the account. A
  browser profile the user logged into themselves is a different thing from
  cvme holding their password.
- **Do not build search.** One URL at a time is the whole requirement, and it
  keeps the tool on the right side of the volume question.

## A constraint on building this here

LinkedIn and Indeed are blocked by this environment's egress proxy, so no tier
above 1 can be exercised from this session. Anything built here can only be
tested against recorded HTML fixtures. That is fine for the JSON-LD extractor,
the `JobPosting` model, the markdown writer, the ATS clients and the manual
path, all of which are pure functions over saved input. The live browser tiers
need to be finished and verified on a machine that can reach the sites.
