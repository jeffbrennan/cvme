"""What a browser capture recovered, and how much of it to believe.

A capture is not a download. It is an inference from a page that lazy-loads,
collapses long text behind "see more", paginates, and changes layout without
notice. So every section carries a status, and only two of the four licence a
definitive statement about what is *not* on the profile:

===============  ==========================================================
Status           Meaning
===============  ==========================================================
``complete``     Every entry and every expanded body was recovered.
``empty``        The page positively established that the section has none.
``partial``      Something was recovered; whether it was all of it is not known.
``unavailable``  Navigation or parsing failed. Nothing was learned.
===============  ==========================================================

That distinction is the whole point of the type. A timeout that reported
"missing from LinkedIn" would send you to paste in a role that is already
there, and the second time it did that you would stop believing the tool. So
``partial`` and ``unavailable`` narrow the audit's coverage instead: cvme says
it could not check, which is a smaller and true statement.

Provenance travels with the snapshot -- when it was taken, which profile URL,
and which extractor version -- because a capture read six months from now,
against selectors that have since been rewritten, is evidence of very little
unless it says what produced it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from cvme.linkedin.live import Source
from cvme.linkedin.model import Profile

Status = Literal["complete", "empty", "partial", "unavailable"]

#: Bump when extraction changes in a way that makes older snapshots
#: incomparable, so a stale capture is recognisable rather than merely old.
EXTRACTOR_VERSION = 1

#: The statuses that support saying "this is not on your profile". The other
#: two mean cvme did not find out.
TRUSTED: frozenset[str] = frozenset({"complete", "empty"})

#: Section as LinkedIn names it -> the profile part it fills. The two
#: vocabularies differ ("About" is the summary), and keeping the mapping here
#: means the extractor can speak LinkedIn's language and the audit its own.
PART_FOR_SECTION: dict[str, str] = {
    "headline": "headline",
    "about": "summary",
    "experience": "positions",
    "education": "educations",
    "skills": "skills",
}


class Section(BaseModel):
    """One profile section, and how the read went."""

    status: Status = "unavailable"
    #: How many entries were recovered, for a person sanity-checking the run
    #: against the page in front of them.
    found: int = 0
    #: Why it is not ``complete``, in one line.
    note: str = ""

    @property
    def trusted(self) -> bool:
        return self.status in TRUSTED

    def __str__(self) -> str:
        detail = f" ({self.note})" if self.note else ""
        return f"{self.status:<12} {self.found} found{detail}"


class Capture(BaseModel):
    """A profile read from the browser, with its provenance."""

    profile: Profile = Field(default_factory=Profile)
    sections: dict[str, Section] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    profile_url: str = ""
    extractor_version: int = EXTRACTOR_VERSION

    def section(self, name: str) -> Section:
        return self.sections.get(name, Section())

    @property
    def covers(self) -> set[str]:
        """The profile parts this capture may be compared against.

        A section that came back ``partial`` reports nothing here even though
        it recovered entries, because the audit's question is symmetric: to say
        an entry is missing from LinkedIn you have to know you saw all of them.
        """
        return {
            part
            for section, part in PART_FOR_SECTION.items()
            if self.section(section).trusted
        }

    @property
    def complete(self) -> bool:
        return all(section.trusted for section in self.sections.values())

    def as_source(self) -> Source:
        """The capture as the audit's kind of thing."""
        when = self.captured_at.strftime("%Y-%m-%d %H:%M UTC")
        return Source(
            profile=self.profile,
            covers=self.covers,
            label=f"browser capture ({when})",
        )

    def lines(self) -> list[str]:
        """Section statuses, for a person checking the run against the page."""
        return [
            f"  {name:<11} {self.sections[name]}"
            for name in PART_FOR_SECTION
            if name in self.sections
        ]
