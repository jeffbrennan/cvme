"""Small, site-specific fallbacks for public job posting HTML.

These extractors intentionally only parse HTML that the normal HTTP request
already returned.  They do not log in, imitate a private API, or attempt to
bypass a challenge page.
"""

from __future__ import annotations

from dataclasses import dataclass

from selectolax.parser import HTMLParser, Node

from cvme.jobs.htmltext import to_markdown
from cvme.jobs.models import JobPosting


@dataclass(frozen=True)
class Selectors:
    description: tuple[str, ...]
    title: tuple[str, ...]
    company: tuple[str, ...]
    location: tuple[str, ...]


_SITES = {
    "linkedin": Selectors(
        description=(
            ".show-more-less-html__markup",
            ".jobs-description__content",
            ".jobs-box__html-content",
        ),
        title=(
            ".top-card-layout__title",
            ".job-details-jobs-unified-top-card__job-title",
        ),
        company=(
            ".topcard__org-name-link",
            ".topcard__flavor:first-of-type",
            ".job-details-jobs-unified-top-card__company-name",
        ),
        location=(
            ".topcard__flavor--bullet",
            ".job-details-jobs-unified-top-card__primary-description-container",
        ),
    ),
    "indeed": Selectors(
        description=("#jobDescriptionText", "[data-testid='jobDescriptionText']"),
        title=(
            "h1.jobsearch-JobInfoHeader-title",
            "h1[data-testid='jobsearch-JobInfoHeader-title']",
        ),
        company=(
            "[data-company-name='true']",
            "[data-testid='inlineHeader-companyName']",
        ),
        location=(
            "[data-testid='job-location']",
            ".jobsearch-JobInfoHeader-subtitle > div",
        ),
    ),
}


def _first(tree: HTMLParser, selectors: tuple[str, ...]) -> Node | None:
    for selector in selectors:
        if node := tree.css_first(selector):
            return node
    return None


def _text(tree: HTMLParser, selectors: tuple[str, ...]) -> str:
    node = _first(tree, selectors)
    return (node.text(separator=" ", strip=True) or "") if node else ""


def extract(html: str, url: str, site: str) -> JobPosting | None:
    """Extract a posting from known LinkedIn or Indeed page markup."""
    selectors = _SITES.get(site)
    if selectors is None:
        return None

    tree = HTMLParser(html)
    description = _first(tree, selectors.description)
    if description is None:
        return None
    markdown = to_markdown(description.html or "")
    if not markdown.strip():
        return None

    return JobPosting(
        url=url,
        title=_text(tree, selectors.title),
        company=_text(tree, selectors.company),
        location=_text(tree, selectors.location),
        description=markdown,
        source=site,
        tier="site:html",
    )
