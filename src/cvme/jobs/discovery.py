"""Bulk discovery from public LinkedIn and Indeed search result pages.

Discovery deliberately captures only the small amount of metadata present in
a result card.  The existing :class:`Fetcher` remains responsible for parsing
the full posting, so saved responses and all of its fallbacks keep working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from selectolax.parser import HTMLParser, Node

from cvme.config import SearchSourceConfig
from cvme.jobs.sources import REQUEST_TIMEOUT, USER_AGENT, FetchError

_LINKEDIN_ID = re.compile(r"/jobs/view/(?:[^/?#]*-)?(\d+)")


@dataclass(frozen=True)
class DiscoveredJob:
    url: str
    source: str
    title: str = ""
    company: str = ""
    location: str = ""

    @property
    def key(self) -> str:
        return identity(self.url, self.source)


def identity(url: str, source: str = "") -> str:
    """Return the board's stable job identity, stripping tracking parameters."""
    parts = urlsplit(url)
    site = source or ("linkedin" if "linkedin." in parts.netloc else "indeed")
    if site == "linkedin" and (match := _LINKEDIN_ID.search(parts.path)):
        return f"linkedin:{match.group(1)}"
    if site == "indeed" and (job_key := parse_qs(parts.query).get("jk")):
        return f"indeed:{job_key[0]}"
    clean = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
    return f"url:{clean.rstrip('/')}"


def search_url(source: SearchSourceConfig, page: int) -> str:
    offset = page * (25 if source.site == "linkedin" else 10)
    if source.site == "linkedin":
        parameters: dict[str, str | int] = {
            "keywords": source.query,
            "location": source.location,
            "start": offset,
        }
        if source.remote:
            parameters["f_WT"] = "2"
        if source.posted_within_days is not None:
            parameters["f_TPR"] = f"r{source.posted_within_days * 86400}"
        query = urlencode(parameters)
        return (
            "https://www.linkedin.com/jobs-guest/jobs/api/"
            f"seeMoreJobPostings/search?{query}"
        )
    if source.site == "indeed":
        parameters = {
            "q": source.query,
            "l": source.location,
            "start": offset,
        }
        if source.remote:
            parameters["sc"] = "0kf:attr(DSQF7);"
        if source.posted_within_days is not None:
            parameters["fromage"] = source.posted_within_days
        query = urlencode(parameters)
        return f"https://www.indeed.com/jobs?{query}"
    raise FetchError(f"unsupported search site '{source.site}'; use linkedin or indeed")


def discover(
    source: SearchSourceConfig, client: httpx.Client | None = None
) -> list[DiscoveredJob]:
    """Fetch and parse all configured result pages for one search."""
    owned = client is None
    active = client or httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT,
    )
    found: dict[str, DiscoveredJob] = {}
    try:
        for page in range(source.pages):
            url = search_url(source, page)
            try:
                response = active.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise FetchError(f"could not search {source.site}: {exc}") from exc
            for job in parse_results(response.text, source.site, base_url=url):
                found.setdefault(job.key, job)
    finally:
        if owned:
            active.close()
    return list(found.values())


def parse_results(html: str, site: str, *, base_url: str = "") -> list[DiscoveredJob]:
    """Parse result cards without depending on one exact page layout."""
    if site not in {"linkedin", "indeed"}:
        raise FetchError(f"unsupported search site '{site}'")
    tree = HTMLParser(html)
    selectors = (
        ("a.base-card__full-link, a[href*='/jobs/view/']")
        if site == "linkedin"
        else ("a[data-jk], a[href*='/viewjob'], a[href*='jk=']")
    )
    jobs: dict[str, DiscoveredJob] = {}
    for link in tree.css(selectors):
        href = link.attributes.get("href", "")
        url = _canonical_url(urljoin(base_url, href), site)
        if not url:
            continue
        card = _card(link, site)
        title = _attribute_or_text(link, "title")
        if site == "linkedin":
            title = _first_text(card, ".base-search-card__title") or title
            company = _first_text(card, ".base-search-card__subtitle")
            location = _first_text(card, ".job-search-card__location")
        else:
            title = _first_text(card, "[data-testid='jobTitle']") or title
            company = _first_text(card, "[data-testid='company-name'], .companyName")
            location = _first_text(
                card, "[data-testid='text-location'], .companyLocation"
            )
        job = DiscoveredJob(url, site, title, company, location)
        jobs.setdefault(job.key, job)
    return list(jobs.values())


def _canonical_url(url: str, site: str) -> str:
    parts = urlsplit(url)
    if site == "linkedin":
        match = _LINKEDIN_ID.search(parts.path)
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}" if match else ""
    job_key = parse_qs(parts.query).get("jk")
    if not job_key:
        return ""
    return f"https://www.indeed.com/viewjob?{urlencode({'jk': job_key[0]})}"


def _card(link: Node, site: str) -> Node:
    current: Node | None = link
    while current is not None:
        classes = set((current.attributes.get("class") or "").split())
        wanted_class = "base-card" if site == "linkedin" else "job_seen_beacon"
        if wanted_class in classes or current.tag == "li":
            return current
        current = current.parent
    return link


def _first_text(node: Node, selectors: str) -> str:
    found = node.css_first(selectors)
    return found.text(separator=" ", strip=True) if found else ""


def _attribute_or_text(node: Node, attribute: str) -> str:
    return (
        node.attributes.get(attribute) or node.text(separator=" ", strip=True)
    ).strip()
