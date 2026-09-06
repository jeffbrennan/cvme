"""Reading profile sections out of a rendered page.

Every LinkedIn-specific string in cvme lives in ``SELECTORS`` below. When the
markup changes -- and it will -- this table is the only thing to edit, and
``cvme linkedin capture --show`` prints what the current one recovers.

Two rules shape everything here.

**Nothing is inferred that was not read.** The projection in ``project`` may
invent a headline from your current role, because a resume that does not state
one still implies one. A capture is evidence, so it may not: an About section
that failed to expand is a failed read, not an empty About.

**Absence is only believed when the rest of the page was understood.** A
section anchor that is not on the page means either "this member has no
Education" or "LinkedIn renamed the anchor". The two are told apart by
corroboration: if other sections parsed, the page is a profile cvme
understands and the gap is real; if none did, the layout is the problem and
every section becomes ``unavailable``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cvme.linkedin.capture import Capture, Section
from cvme.linkedin.dates import parse_point
from cvme.linkedin.model import Education, MonthYear, Position, Profile, Skill

#: How long to wait for one interaction, in milliseconds. Generous, because
#: the cost of being wrong is a false "missing from LinkedIn"; bounded,
#: because a capture that hangs is worse than one that reports what it could
#: not read.
SETTLE_MS = 4000

#: How many times to scroll for more of a lazily-loaded list before calling
#: the section partial rather than complete.
SCROLL_ROUNDS = 12


@dataclass(frozen=True)
class SectionSelectors:
    """Where one section lives, and how to open everything inside it."""

    #: The section's anchor. LinkedIn puts a stable ``#id`` on each profile
    #: section, which the reader then walks up to the enclosing ``<section>``.
    root: str
    #: One entry within it.
    entry: str = "li.artdeco-list__item"
    #: Buttons that reveal collapsed text inside the section.
    expand: str = "button.inline-show-more-text__button"
    #: Roles nested under a single employer.
    nested: str = "li.pvs-list__paged-list-item"


#: The one place LinkedIn's markup is named. Everything below reads from here.
SELECTORS: dict[str, SectionSelectors] = {
    "about": SectionSelectors(root="#about", entry="div.display-flex.full-width"),
    "experience": SectionSelectors(root="#experience"),
    "education": SectionSelectors(root="#education"),
    "skills": SectionSelectors(root="#skills"),
}

#: The headline sits in the top card rather than a numbered section.
HEADLINE = "div.text-body-medium.break-words"

#: Only rendered on your own profile, so it doubles as the check that the page
#: belongs to the signed-in member.
OWN_PROFILE_MARK = "button[aria-label*='Add profile section'], a[href*='/edit/forms/']"

#: LinkedIn prints each entry's text twice: once visible, once in an
#: aria-hidden span for screen readers. Reading both doubles every string.
VISIBLE_TEXT = "span[aria-hidden='true']"

#: The container a long description sits in, and the reason the reader does
#: not simply take an entry's spans in order: the header lines and the body
#: are different things, and telling them apart by position means guessing
#: whether the fourth line is a location or the first sentence of the body.
BODY = "[class*='inline-show-more-text']"

#: An entry's own header lines: not the description, and not the roles nested
#: inside it. Without the second exclusion an employer card's first line is
#: followed by every nested role's text.
ENTRY_HEADER = (
    "xpath=.//span[@aria-hidden='true']"
    "[not(ancestor::*[contains(@class,'inline-show-more-text')])]"
    "[not(ancestor::li[contains(@class,'pvs-list__paged-list-item')])]"
)

#: The same, scoped to one nested role, where the enclosing list item is the
#: scope rather than something to exclude.
NESTED_HEADER = (
    "xpath=.//span[@aria-hidden='true']"
    "[not(ancestor::*[contains(@class,'inline-show-more-text')])]"
)

#: "Jan 2020 - Present · 5 yrs 2 mos" -- the duration after the separator is
#: computed by LinkedIn rather than entered, so it is not profile content.
_AFTER_SEPARATOR = re.compile(r"\s*·.*$")
_RANGE = re.compile(r"\s*[-–—]\s*")


@dataclass
class Reader:
    """Extracts one profile from one rendered page.

    ``page`` is a Playwright ``Page``, but it is typed loosely and only ever
    used through ``locator``/``wait_for_timeout``, so the extractor can be
    driven against a fixture without importing Playwright here.
    """

    page: Any
    settle_ms: int = SETTLE_MS
    scroll_rounds: int = SCROLL_ROUNDS
    sections: dict[str, Section] = field(default_factory=dict)

    def capture(self, profile_url: str = "") -> Capture:
        """Read every section, then decide how much of it to believe."""
        profile = Profile(
            headline=self._headline(),
            summary=self._about(),
            positions=self._experience(),
            educations=self._education(),
            skills=self._skills(),
        )
        self._corroborate()
        return Capture(profile=profile, sections=self.sections, profile_url=profile_url)

    def _corroborate(self) -> None:
        """An absent section is only absent if the page was understood at all.

        Without this, a rewritten layout reports every section as empty, and
        an audit against that says the whole profile is missing -- the most
        confidently wrong output the tool could produce.
        """
        if any(s.status in ("complete", "partial") for s in self.sections.values()):
            return
        self.sections = {
            name: Section(
                status="unavailable",
                found=section.found,
                note="no section of this page was recognised",
            )
            for name, section in self.sections.items()
        }

    # -- sections ---------------------------------------------------------

    def _headline(self) -> str:
        found = self._texts(self.page, HEADLINE)
        if not found:
            self.sections["headline"] = Section(
                status="unavailable", note="no headline element on the page"
            )
            return ""
        self.sections["headline"] = Section(status="complete", found=1)
        return found[0]

    def _about(self) -> str:
        root = self._root("about")
        if root is None:
            return ""
        opened = self._expand(root, "about")
        paragraphs = [t for t in self._texts(root, VISIBLE_TEXT) if t]
        text = "\n\n".join(dict.fromkeys(paragraphs))
        if not text:
            self._unreadable("about")
            return ""
        self.sections["about"] = (
            Section(status="complete", found=1)
            if opened
            else Section(status="partial", found=1, note="a 'see more' would not open")
        )
        return text

    def _experience(self) -> list[Position]:
        entries, whole = self._entries("experience")
        positions = [role for entry in entries for role in self._roles(entry)]
        self._record("experience", positions, whole)
        return positions

    def _education(self) -> list[Education]:
        entries, whole = self._entries("education")
        found = [e for entry in entries if (e := self._one_education(entry))]
        self._record("education", found, whole)
        return found

    def _skills(self) -> list[Skill]:
        entries, whole = self._entries("skills")
        names = [lines[0] for entry in entries if (lines := self._lines(entry))]
        skills = [Skill(name=name) for name in dict.fromkeys(names) if name]
        self._record("skills", skills, whole)
        return skills

    # -- entries ----------------------------------------------------------

    def _roles(self, entry: Any) -> list[Position]:
        """One entry, which may hold one role or several under one employer.

        LinkedIn nests promotions and internal moves inside a single employer
        card, with the company on the outer heading and the roles listed
        beneath. Flattening that is the difference between four positions and
        one position whose description is three other jobs.
        """
        lines = self._texts(entry, ENTRY_HEADER)
        nested = entry.locator(SELECTORS["experience"].nested)
        if (count := _count(nested)) == 0:
            return [_position(lines, self._body(entry))] if lines else []

        # The employer heads the card and the roles sit under it, so each
        # nested role is read with the company handed in rather than parsed
        # out of a line it does not have.
        company = lines[0] if lines else ""
        roles = []
        for index in range(count):
            role = nested.nth(index)
            if inner := self._texts(role, NESTED_HEADER):
                roles.append(_position(inner, self._body(role), company=company))
        return roles or ([_position(lines, self._body(entry))] if lines else [])

    def _body(self, scope: Any) -> str:
        """An entry's description, read from its own container."""
        return "\n".join(dict.fromkeys(self._texts(scope, f"{BODY} {VISIBLE_TEXT}")))

    def _one_education(self, entry: Any) -> Education | None:
        lines = self._lines(entry)
        if not lines:
            return None
        degree, subject = _degree_line(lines[1] if len(lines) > 1 else "")
        start, end = _dates(lines[2]) if len(lines) > 2 else (None, None)
        return Education(
            school=lines[0],
            degree=degree,
            field_of_study=subject,
            description="\n".join(lines[3:]),
            start=start,
            end=end,
        )

    def _entries(self, name: str) -> tuple[list[Any], bool]:
        """The section's entries, and whether all of them were seen."""
        root = self._root(name)
        if root is None:
            return [], False
        settled = self._load_all(root)
        opened = self._expand(root, name)
        located = root.locator(SELECTORS[name].entry)
        entries = [located.nth(i) for i in range(_count(located))]
        return entries, settled and opened

    def _root(self, name: str) -> Any | None:
        """The section container, or ``None`` with the reason recorded."""
        anchor = self.page.locator(SELECTORS[name].root)
        if _count(anchor) == 0:
            self.sections[name] = Section(
                status="empty", note="no such section on the page"
            )
            return None
        return anchor.first.locator("xpath=ancestor-or-self::section[1]")

    # -- page mechanics ---------------------------------------------------

    def _load_all(self, root: Any) -> bool:
        """Scroll a lazily-loaded list until it stops growing.

        Returns whether it settled. A list still growing when the rounds run
        out leaves the section partial, because the entries below the fold are
        exactly the ones an audit would otherwise call missing.
        """
        entries = root.locator("li")
        seen = _count(entries)
        for _ in range(self.scroll_rounds):
            try:
                entries.last.scroll_into_view_if_needed(timeout=self.settle_ms)
            except Exception:
                return True  # nothing to scroll is a settled list
            self.page.wait_for_timeout(150)
            if (now := _count(entries)) == seen:
                return True
            seen = now
        return False

    def _expand(self, root: Any, name: str) -> bool:
        """Click every "see more" in the section. Returns whether all opened."""
        buttons = root.locator(SELECTORS[name].expand)
        opened = True
        for index in range(_count(buttons)):
            try:
                buttons.nth(index).click(timeout=self.settle_ms)
            except Exception:
                opened = False
        self.page.wait_for_timeout(100)
        return opened

    def _lines(self, scope: Any) -> list[str]:
        return [t for t in self._texts(scope, VISIBLE_TEXT) if t]

    def _texts(self, scope: Any, selector: str) -> list[str]:
        located = scope.locator(selector)
        out: list[str] = []
        for index in range(_count(located)):
            try:
                out.append(_clean(located.nth(index).inner_text()))
            except Exception:
                continue  # a node that went away mid-read is one we did not get
        return out

    # -- status -----------------------------------------------------------

    def _record(self, name: str, found: list[Any], whole: bool) -> None:
        if self.sections.get(name, Section()).status == "empty":
            return  # the section is not on the page; _root already said so
        if not found:
            self._unreadable(name)
        elif whole:
            self.sections[name] = Section(status="complete", found=len(found))
        else:
            self.sections[name] = Section(
                status="partial",
                found=len(found),
                note="the section was still loading or would not fully expand",
            )

    def _unreadable(self, name: str) -> None:
        """The section is on the page but nothing came out of it.

        Reported as unavailable rather than empty: LinkedIn does not render a
        section you have no entries in, so a section that exists and yields
        nothing is cvme failing to read it.
        """
        self.sections[name] = Section(
            status="unavailable",
            note="the section is on the page but nothing could be read from it",
        )


# -- parsing ---------------------------------------------------------------


def _position(lines: list[str], body: str, *, company: str = "") -> Position:
    """One role's header lines, plus the description read from its own box.

    The date range is *found* rather than indexed. Its position moves: a role
    with an employment type has one more line before it than a role without,
    and a nested role has one fewer because its employer is on the card above.
    Anchoring on the one line that parses as a date makes all three the same
    shape, and makes the line after it the location rather than a guess.
    """
    if not lines:
        return Position(title="", company=company, description=body)
    rest = lines[1:]
    if not company:
        company = _before_separator(rest[0]) if rest else ""
        rest = rest[1:]

    at = next((i for i, line in enumerate(rest) if _is_date(line)), None)
    start, end = _dates(rest[at]) if at is not None else (None, None)
    after = rest[at + 1 :] if at is not None else []
    return Position(
        title=lines[0],
        company=company,
        location=after[0] if after else "",
        description=body,
        start=start,
        end=end,
    )


def _degree_line(text: str) -> tuple[str, str]:
    """``Master of Science, Epidemiology`` -- degree, then field of study."""
    degree, _, subject = text.partition(",")
    return degree.strip(), subject.strip()


def _dates(text: str) -> tuple[MonthYear | None, MonthYear | None]:
    cleaned = _before_separator(text)
    if not cleaned:
        return None, None
    parts = _RANGE.split(cleaned, maxsplit=1)
    start = parse_point(parts[0])
    end = parse_point(parts[1]) if len(parts) > 1 else None
    return start, end


def _is_date(text: str) -> bool:
    return any(_dates(text))


def _before_separator(text: str) -> str:
    """``Acme · Full-time`` -- what follows the dot is not the field's value."""
    return _AFTER_SEPARATOR.sub("", text).strip()


def _clean(text: str) -> str:
    return " ".join(text.split())


def _count(locator: Any) -> int:
    try:
        return locator.count()
    except Exception:
        return 0  # a detached locator counts as none
