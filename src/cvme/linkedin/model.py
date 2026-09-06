"""The shape of a LinkedIn profile, as far as cvme syncs it.

This is a second intermediate representation, deliberately not the document
IR. The document IR is about typesetting -- entries, blocks, markup -- and
LinkedIn is about a fixed set of named fields with hard limits. Projecting
once, into a model that only holds what LinkedIn stores, keeps the diff and
the API payloads from re-deriving the same mapping in two places.

Every string here is **plain text**. The document IR holds Typst markup, and
LinkedIn renders none of it: bold in an About section arrives as literal
asterisks, and a markdown link arrives as a dead label. ``flatten`` is the
seam that turns one into the other.

The limits below are the LinkedIn composer's, not the API's. They are checked
rather than silently applied, because quietly truncating a resume is how a
sentence loses its verb somewhere no one is looking.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from cvme.md.inline import to_plain

#: Field -> the composer's character limit. Only limits worth failing a sync
#: over are listed; a field absent here is not length-checked.
LIMITS: dict[str, int] = {
    "headline": 220,
    "summary": 2600,
    "position.title": 100,
    "position.company": 100,
    "position.description": 2000,
    "skill.name": 100,
}

#: How many skills a profile may carry. LinkedIn keeps the first 50.
MAX_SKILLS = 50

_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

_LINK_OPEN = re.compile(r'#link\("([^"]*)"\)\[')


class MonthYear(BaseModel):
    """A LinkedIn date. The API takes a month and a year and nothing finer."""

    model_config = {"frozen": True}

    year: int
    month: int | None = None

    def __str__(self) -> str:
        if self.month is None:
            return str(self.year)
        return f"{_MONTHS[self.month - 1]} {self.year}"


class Position(BaseModel):
    """One role. LinkedIn calls these positions; the resume calls them jobs."""

    title: str
    company: str
    description: str = ""
    location: str = ""
    start: MonthYear | None = None
    end: MonthYear | None = None

    @property
    def key(self) -> str:
        """What makes this the same position across two runs of the projection.

        Company, title and start date, because those are what LinkedIn itself
        treats as the identity of a position, and because the end date is the
        field most likely to change on a role you still hold. Two stints at
        one employer differ by their start date, so it has to be in the key.
        """
        return _key(self.company, self.title, str(self.start or ""))


class Education(BaseModel):
    school: str
    degree: str = ""
    field_of_study: str = ""
    description: str = ""
    start: MonthYear | None = None
    end: MonthYear | None = None

    @property
    def key(self) -> str:
        return _key(self.school, self.degree)


class Skill(BaseModel):
    model_config = {"frozen": True}

    name: str

    @property
    def key(self) -> str:
        return _key(self.name)


class Violation(BaseModel):
    """A field LinkedIn would reject, and by how much."""

    where: str
    limit: int
    actual: int
    unit: Literal["characters", "skills"] = "characters"

    def __str__(self) -> str:
        return (
            f"{self.where}: {self.actual} {self.unit}, "
            f"{self.actual - self.limit} over the limit of {self.limit}"
        )


class Profile(BaseModel):
    """Everything the sync knows how to state about a member."""

    headline: str = ""
    summary: str = ""
    positions: list[Position] = Field(default_factory=list)
    educations: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)

    def violations(self) -> list[Violation]:
        """Every field longer than LinkedIn will accept.

        Returned rather than raised so a caller can show all of them at once.
        Fixing one over-long bullet and being told about the next one is a
        worse loop than being told about both.
        """
        found = [
            *_over("headline", "headline", self.headline),
            *_over("summary", "summary", self.summary),
        ]
        for position in self.positions:
            where = f"position '{_label(position.title)} @ {_label(position.company)}'"
            found += _over(f"{where} title", "position.title", position.title)
            found += _over(f"{where} company", "position.company", position.company)
            found += _over(
                f"{where} description", "position.description", position.description
            )
        for skill in self.skills:
            found += _over(f"skill '{_label(skill.name)}'", "skill.name", skill.name)
        if len(self.skills) > MAX_SKILLS:
            found.append(
                Violation(
                    where="skills",
                    limit=MAX_SKILLS,
                    actual=len(self.skills),
                    unit="skills",
                )
            )
        return found


def _label(value: str, width: int = 48) -> str:
    """Name a field in a message without repeating the whole over-long value."""
    return value if len(value) <= width else f"{value[:width].rstrip()}..."


def _over(where: str, field: str, value: str) -> list[Violation]:
    limit = LIMITS[field]
    if len(value) <= limit:
        return []
    return [Violation(where=where, limit=limit, actual=len(value))]


def flatten(markup: str) -> str:
    """Typst markup to the plain text LinkedIn stores.

    Links keep their target as a trailing parenthetical. ``to_plain`` drops it,
    which is right for a diagnostic and wrong here: on LinkedIn a URL is only
    reachable if it is written out.
    """
    return to_plain(_spell_links(markup)).strip()


def _spell_links(markup: str) -> str:
    """Rewrite ``#link("url")[text]`` as ``text (url)``.

    Scanned rather than substituted because a link body is markup too, and a
    bolded word inside one puts a ``]`` in the way of any regex that tries to
    find the link's own closing bracket.
    """
    out: list[str] = []
    depth: list[str | None] = []
    i = 0
    while i < len(markup):
        if markup[i] == "\\":
            out.append(markup[i : i + 2])
            i += 2
            continue
        if match := _LINK_OPEN.match(markup, i):
            depth.append(match.group(1))
            out.append("\x00")
            i = match.end()
            continue
        if markup[i] == "[":
            depth.append(None)
        elif markup[i] == "]" and depth and (url := depth.pop()) is not None:
            out.append(_close_link(out, url))
            i += 1
            continue
        out.append(markup[i])
        i += 1
    return "".join(out).replace("\x00", "")


def _close_link(out: list[str], url: str) -> str:
    """The text to emit where a link closes: its target, unless that repeats."""
    body = "".join(out[len(out) - 1 - out[::-1].index("\x00") + 1 :])
    plain = to_plain(body).strip()
    return "" if plain and (plain in url or url in plain) else f" ({url})"


def _key(*parts: str) -> str:
    return " ".join(" ".join(part.casefold().split()) for part in parts)
