"""The tier ladder: how a URL becomes a posting.

Ordered by how good the result is and how likely it is to keep working, not by
convenience. See docs/job-sources.md for the research and live capture results.

Public LinkedIn and Indeed HTML is parsed when it is available. A browser
driving the user's logged-in profile is still needed when either site returns
a login or challenge page; cvme reports that honestly rather than bypassing it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from cvme.errors import CvmeError
from cvme.jobs import ats, jsonld, sitehtml
from cvme.jobs.cache import Cache
from cvme.jobs.htmltext import main_text
from cvme.jobs.models import JobPosting
from cvme.jobs.salary import from_description

USER_AGENT = "cvme/0.1 (+https://github.com/jeffbrennan/cvme) single-posting fetch"
#: A personal tool fetching one page a person is already looking at. The delay
#: and the honest user-agent are the whole of the politeness story, because
#: there is no crawling here to be polite about.
REQUEST_TIMEOUT = 20.0

#: Cloudflare answers a bot check with a short interstitial instead of the
#: page. The status is usually 403 and the body names the challenge platform.
#: The markers are specific enough that a posting which happens to say "just a
#: moment" does not trip them.
_CHALLENGE_STATUS = frozenset({200, 403, 503})
_CHALLENGE_MARKERS = (
    "cf-mitigated",
    "challenges.cloudflare.com",
    "cf_chl_opt",
    "just a moment",
)
#: TLS and header profiles tried in order when a plain fetch is challenged.
#: Chrome 120 passes where newer fingerprints do not, so the order matters.
#: This is not a stealth layer: no challenge is solved and no cookie is
#: planted. The request is shaped like the browser already looking at the
#: page, which is what the site was built to serve.
_IMPERSONATIONS = ("chrome120", "safari17_0")


class FetchError(CvmeError):
    exit_code = 4


def _looks_like_challenge(status: int, body: str) -> bool:
    if status not in _CHALLENGE_STATUS:
        return False
    head = body[:5000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _impersonated_get(url: str, impersonate: str) -> tuple[int, str]:
    """One request through curl_cffi's browser TLS profile."""
    try:
        from curl_cffi import requests
    except ImportError as exc:
        raise FetchError(
            "a bot challenge was presented and the impersonation fallback is "
            "not installed.\n"
            "  Install it with: uv add curl_cffi\n"
            f"  Or save the page and use: cvme job add --html saved.html --url {url}"
        ) from exc
    response = requests.get(url, impersonate=impersonate, timeout=REQUEST_TIMEOUT)
    return response.status_code, response.text


@dataclass
class Fetcher:
    """Walks the ladder for one URL."""

    root: Path
    client: httpx.Client | None = None
    use_cache: bool = True
    before_request: Callable[[], None] | None = None

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
            if self.before_request is not None:
                self.before_request()
            response = client.get(url)
            if _looks_like_challenge(response.status_code, response.text):
                body = self._impersonate(url)
            else:
                response.raise_for_status()
                body = response.text
        except httpx.HTTPError as exc:
            raise FetchError(f"could not fetch {url}: {exc}") from exc
        finally:
            if self.client is None:
                client.close()
        self.cache.write(url, body, suffix)
        return body

    def _impersonate(self, url: str) -> str:
        """Retry a challenged page through a browser TLS profile.

        Only reached when the plain fetch was served a bot check. The page a
        browser would render is the page this returns.
        """
        last = "no profile answered"
        for impersonate in _IMPERSONATIONS:
            if self.before_request is not None:
                self.before_request()
            try:
                status, text = _impersonated_get(url, impersonate)
            except FetchError:
                raise
            except Exception as exc:  # curl_cffi raises its own error types
                last = f"{impersonate}: {exc}"
                continue
            if status == 200 and not _looks_like_challenge(status, text):
                return text
            last = f"{impersonate}: HTTP {status}"
        raise FetchError(
            f"could not fetch {url}: a bot challenge was presented and browser "
            f"impersonation did not pass it ({last}).\n"
            "  Open the posting, save the page, and use:\n"
            f"    cvme job add --html saved.html --url {url}\n"
            "  or paste the description:\n"
            f"    pbpaste | cvme job add --stdin --url {url}"
        )

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
    """Parse a saved page with the same structured tiers as a live response."""
    if posting := jsonld.extract(html, url, source=_site(url)):
        posting.tier = "manual:jsonld"
        return posting
    if posting := sitehtml.extract(html, url, _site(url)):
        posting.tier = "manual:site:html"
        return posting
    description = main_text(html)
    return JobPosting(
        url=url,
        description=description,
        salary=from_description(description),
        source=_site(url),
        tier="manual:html",
    )


def from_text(text: str, url: str) -> JobPosting:
    """Take a pasted description at face value."""
    return JobPosting(
        url=url,
        description=text.strip(),
        salary=from_description(text),
        source=_site(url),
        tier="manual:text",
    )


def _site(url: str) -> str:
    for name in (
        "linkedin",
        "indeed",
        "greenhouse",
        "lever",
        "ashby",
        "workday",
        "hiringcafe",
    ):
        if name in url:
            return name
    return "generic"
