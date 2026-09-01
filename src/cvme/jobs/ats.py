"""Applicant tracking systems, which publish postings through real APIs.

A large share of postings on LinkedIn and Indeed are mirrors of a posting
hosted on Greenhouse, Lever or Ashby. All three serve the canonical text over
documented, public, no-auth JSON, which is better data than the aggregator's
copy and is reached through the front door rather than around it.

The response shapes below are encoded in the fixtures under
``tests/fixtures/jobs``. They could not be verified against the live endpoints
from the environment this was written in, so if a field ever arrives empty,
compare a real response against the matching fixture first: the parsers are
pure functions over that JSON and the fixture is the assumption.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass
from typing import Any

from cvme.jobs.htmltext import to_markdown
from cvme.jobs.models import JobPosting

_PATTERNS: dict[str, re.Pattern[str]] = {
    "greenhouse": re.compile(
        r"(?:job-)?boards\.greenhouse\.io/(?P<org>[^/]+)/jobs/(?P<job>\d+)"
    ),
    "lever": re.compile(r"jobs\.lever\.co/(?P<org>[^/]+)/(?P<job>[0-9a-f-]{16,})"),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/(?P<org>[^/]+)/(?P<job>[0-9a-f-]{16,})"),
}


@dataclass(frozen=True)
class AtsMatch:
    provider: str
    org: str
    job_id: str

    @property
    def api_url(self) -> str:
        if self.provider == "greenhouse":
            return (
                "https://boards-api.greenhouse.io/v1/boards/"
                f"{self.org}/jobs/{self.job_id}"
            )
        if self.provider == "lever":
            return f"https://api.lever.co/v0/postings/{self.org}/{self.job_id}"
        return f"https://api.ashbyhq.com/posting-api/job-board/{self.org}"


class AtsParseError(ValueError):
    """An ATS response did not contain the posting named by its URL."""


def detect(url: str) -> AtsMatch | None:
    """Identify an ATS posting from its URL."""
    for provider, pattern in _PATTERNS.items():
        if match := pattern.search(url):
            return AtsMatch(provider, match.group("org"), match.group("job"))
    return None


def _title_case_org(org: str) -> str:
    return org.replace("-", " ").replace("_", " ").strip().title()


def parse_greenhouse(data: dict[str, Any], match: AtsMatch, url: str) -> JobPosting:
    # Greenhouse returns the description as an HTML-entity-escaped string.
    content = html_module.unescape(str(data.get("content") or ""))
    company = (
        str((data.get("company") or {}).get("name") or "")
        if isinstance(data.get("company"), dict)
        else ""
    )
    return JobPosting(
        url=url,
        title=str(data.get("title") or ""),
        company=company or _title_case_org(match.org),
        location=str((data.get("location") or {}).get("name") or ""),
        posted=str(data.get("updated_at") or "")[:10],
        apply_url=str(data.get("absolute_url") or url),
        description=to_markdown(content),
        source="greenhouse",
        tier="ats",
    )


def parse_lever(data: dict[str, Any], match: AtsMatch, url: str) -> JobPosting:
    categories = data.get("categories") or {}
    # Lever splits the body across `description` and a list of titled sections.
    sections = [str(data.get("description") or "")]
    for block in data.get("lists") or []:
        heading = str(block.get("text") or "").strip()
        sections.append(f"<h3>{heading}</h3>" if heading else "")
        sections.append(str(block.get("content") or ""))
    sections.append(str(data.get("additional") or ""))
    return JobPosting(
        url=url,
        title=str(data.get("text") or ""),
        company=_title_case_org(match.org),
        location=str(categories.get("location") or ""),
        employment_type=str(categories.get("commitment") or ""),
        apply_url=str(data.get("applyUrl") or data.get("hostedUrl") or url),
        description=to_markdown("".join(s for s in sections if s)),
        source="lever",
        tier="ats",
    )


def parse_ashby(data: dict[str, Any], match: AtsMatch, url: str) -> JobPosting:
    """Ashby serves a whole board, so the posting is selected by id."""
    jobs = data.get("jobs") or []
    job = next((j for j in jobs if str(j.get("id")) == match.job_id), None)
    if job is None:
        raise AtsParseError(f"Ashby board did not contain job {match.job_id}")
    remote = job.get("isRemote")
    return JobPosting(
        url=url,
        title=str(job.get("title") or ""),
        company=str(data.get("name") or "") or _title_case_org(match.org),
        location=str(job.get("location") or ""),
        employment_type=str(job.get("employmentType") or ""),
        remote=bool(remote) if remote is not None else None,
        posted=str(job.get("publishedAt") or "")[:10],
        apply_url=str(job.get("jobUrl") or url),
        description=to_markdown(str(job.get("descriptionHtml") or "")),
        source="ashby",
        tier="ats",
    )


PARSERS = {
    "greenhouse": parse_greenhouse,
    "lever": parse_lever,
    "ashby": parse_ashby,
}


def parse(data: dict[str, Any], match: AtsMatch, url: str) -> JobPosting:
    return PARSERS[match.provider](data, match, url)
