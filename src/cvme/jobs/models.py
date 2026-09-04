"""The normalised shape of a job posting.

Every source, however it was reached, produces one of these. The description
is markdown, so a posting is reviewable and diffable in the same way as the
documents it will be used to tailor.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import blake2b

from pydantic import BaseModel, Field

_SLUG = re.compile(r"[^a-z0-9]+")

#: Arrangement -> the phrases that state it outright in prose. Hybrid is
#: checked first, because "hybrid/remote" is a hybrid role.
_ARRANGEMENT = (
    ("hybrid", ("hybrid",)),
    (
        "remote",
        (
            "fully remote",
            "100% remote",
            "remote first",
            "remote position",
            "remote role",
            "work from home",
            "telecommute",
        ),
    ),
)


class JobPosting(BaseModel):
    """One posting, normalised."""

    url: str
    title: str = ""
    company: str = ""
    location: str = ""
    employment_type: str = ""
    remote: bool | None = None
    salary: str = ""
    posted: str = ""
    apply_url: str = ""
    description: str = ""

    #: Which site the posting came from, and which strategy produced it. Kept
    #: because a posting read from an ATS is better evidence than the same job
    #: mirrored on an aggregator, and it should be obvious which one you have.
    source: str = "unknown"
    tier: str = "unknown"
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def slug(self) -> str:
        """A stable, readable filename stem."""
        parts = [p for p in (self.company, self.title) if p]
        base = _SLUG.sub("-", " ".join(parts).lower()).strip("-")[:60] or "posting"
        digest = blake2b(self.url.encode(), digest_size=2).hexdigest()
        return f"{base}-{digest}"

    @property
    def arrangement(self) -> str:
        """Remote, hybrid, or onsite, from whichever part of the posting says so.

        ``remote`` is only set by sources that emit ``jobLocationType``. Most
        postings say it in the location line, and plenty say it only in the
        first paragraph -- "this position is hybrid/remote" over an address in
        Manhattan -- so the prose is read too, but only for phrases that state
        an arrangement outright. Where nothing says, an address is taken to
        mean onsite and silence is left as silence.
        """
        if self.remote is True:
            return "remote"
        stated = f"{self.location} {self.employment_type}".casefold()
        body = self.description.casefold()
        for name, phrases in _ARRANGEMENT:
            if name in stated or any(phrase in body for phrase in phrases):
                return name
        return "onsite" if self.remote is False or self.location.strip() else ""

    def missing(self) -> list[str]:
        """Fields a tailoring prompt really wants, that this posting lacks."""
        return [
            name
            for name in ("title", "company", "description")
            if not getattr(self, name).strip()
        ]
