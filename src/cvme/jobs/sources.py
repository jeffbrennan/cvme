"""The tier ladder: how a URL becomes a posting.

Ordered by how good the result is and how likely it is to keep working, not by
convenience. See docs/job-sources.md for the research behind the order, in
particular why there is no anonymous LinkedIn HTTP tier.

Public LinkedIn and Indeed HTML is parsed when it is available. A browser
driving the user's logged-in profile is still needed when either site returns
a login or challenge page; cvme reports that honestly rather than bypassing it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from cvme.errors import CvmeError
from cvme.jobs import ats, jsonld, sitehtml
from cvme.jobs.cache import Cache
from cvme.jobs.htmltext import main_text
from cvme.jobs.models import JobPosting

USER_AGENT = "cvme/0.1 (+https://github.com/jeffbrennan/cvme) single-posting fetch"
#: A personal tool fetching one page a person is already looking at. The delay
#: and the honest user-agent are the whole of the politeness story, because
#: there is no crawling here to be polite about.
REQUEST_TIMEOUT = 20.0


class FetchError(CvmeError):
    exit_code = 4


@dataclass
class Fetcher:
    """Walks the ladder for one URL."""

    root: Path
    client: httpx.Client | None = None
    use_cache: bool = True

    def __post_init__(self) -> None:
        self.cache = Cache(self.root)

    def _get(self, url: str, *, suffix: str) -> str:
        if self.use_cache and (body := self.cache.read(url, suffix)) is not None:
            return body
        client = self.client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        )
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise FetchError(f"could not fetch {url}: {exc}") from exc
        finally:
            if self.client is None:
                client.close()
        self.cache.write(url, response.text, suffix)
        return response.text

    def fetch(self, url: str) -> JobPosting:
        if match := ats.detect(url):
            body = self._get(match.api_url, suffix=".json")
            try:
                data = json.loads(body)
            except json.JSONDecodeError as exc:
                raise FetchError(f"{match.provider} returned invalid JSON") from exc
            try:
                return ats.parse(data, match, url)
            except ats.AtsParseError as exc:
                raise FetchError(str(exc)) from exc

        html = self._get(url, suffix=".html")
        site = _site(url)
        if posting := jsonld.extract(html, url, source=site):
            return posting
        if posting := sitehtml.extract(html, url, site):
            return posting

        raise FetchError(
            f"no job description found at {url}.\n"
            "  The site may require a logged-in browser or may have changed "
            "its markup.\n"
            "  Open the posting, save the page, and use:\n"
            f"    cvme job add --html saved.html --url {url}\n"
            "  or paste the description:\n"
            f"    pbpaste | cvme job add --stdin --url {url}"
        )


def from_html(html: str, url: str) -> JobPosting:
    """Parse a saved page: JSON-LD if it is there, densest text block if not."""
    if posting := jsonld.extract(html, url, source=_site(url)):
        posting.tier = "manual:jsonld"
        return posting
    return JobPosting(
        url=url, description=main_text(html), source=_site(url), tier="manual:html"
    )


def from_text(text: str, url: str) -> JobPosting:
    """Take a pasted description at face value."""
    return JobPosting(
        url=url, description=text.strip(), source=_site(url), tier="manual:text"
    )


def _site(url: str) -> str:
    for name in ("linkedin", "indeed", "greenhouse", "lever", "ashby", "workday"):
        if name in url:
            return name
    return "generic"
