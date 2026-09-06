"""Project a parsed document onto the LinkedIn profile model.

The mapping is the whole of the feature's opinion, so it is written out here
rather than spread through the sync:

===========================  ==========================================
Document                     Profile
===========================  ==========================================
``headline:`` frontmatter    headline, falling back to ``title:``
untitled lead / ``Summary``  About
``Experience`` entries       positions
``Education`` entries        educations
``Skills`` bullets           skills, one per comma-separated term
===========================  ==========================================

Sections cvme does not recognise are left alone. A resume that grows a
``Projects`` section does not silently lose it -- the sync reports it as
unmapped, because "we ignored a third of your document" is not a thing to
find out from the profile.
"""

from __future__ import annotations

import re

from cvme.linkedin.dates import is_open_ended, parse_range
from cvme.linkedin.model import (
    Education,
    MonthYear,
    Position,
    Profile,
    Skill,
    flatten,
)
from cvme.models import (
    Block,
    Bullet,
    BulletList,
    Document,
    Entry,
    Paragraph,
    Section,
    to_plain_title,
)

#: Recognised section titles, by the profile field they feed. Matched on the
#: title's words rather than equality, so "Professional Experience" and
#: "Technical Skills" land where they obviously belong.
SECTIONS: dict[str, frozenset[str]] = {
    "summary": frozenset({"summary", "about", "profile", "objective"}),
    "experience": frozenset({"experience", "employment", "history"}),
    "education": frozenset({"education"}),
    "skills": frozenset({"skills", "expertise", "competencies"}),
}

#: The bullet glyph LinkedIn users type by hand, because the field has no list
#: markup and a hyphen reads as a dash mid-sentence.
BULLET = "• "

#: A trailing "(...)" holding one thing: a proficiency note on a resume, and
#: noise in a field LinkedIn matches against a controlled vocabulary.
_QUALIFIER = re.compile(r"\s*\(([^(),;]*)\)\s*$")
_DEGREE_SPLIT = re.compile(r"\s+-\s+|\s+\bin\b\s+")
_MAJOR_PREFIX = re.compile(
    r"^(?:major|concentration|specialisation|specialization)\s+in\s+", re.IGNORECASE
)
#: ", Minor in Biostatistics" and friends: a second clause on the degree line
#: that LinkedIn has no field for and that does not belong in "Field of study".
_SECOND_CLAUSE = re.compile(
    r"\s*[,;]\s*(?:minor|certificate|concentration)\b.*$", re.IGNORECASE
)


def to_profile(document: Document) -> tuple[Profile, list[str]]:
    """Read a document as a profile, and report what could not be mapped.

    ``sendable`` first: a ``## Gaps`` section is addressed to the author, and
    of all the places for it to end up, a public profile is the worst.
    """
    profile = Profile()
    unmapped: list[str] = []
    summary: list[str] = []

    for section in document.sendable().sections:
        match _field_for(section):
            case "summary":
                summary.append(_blocks_text(section.blocks))
            case "experience":
                profile.positions += [_position(e) for e in section.entries]
            case "education":
                profile.educations += [_education(e) for e in section.entries]
            case "skills":
                profile.skills += _skills(section)
            case _:
                unmapped.append(flatten(section.title) or "(untitled)")

    profile.summary = "\n\n".join(part for part in summary if part)
    profile.headline = _headline(document, profile)
    profile.skills = _dedupe(profile.skills)
    return profile, unmapped


def _headline(document: Document, profile: Profile) -> str:
    """``headline:`` frontmatter, then ``title:``, then the current role.

    The last fallback is what LinkedIn itself writes when you have never set a
    headline, so a profile that has not been thought about yet ends up where
    it would have anyway rather than blank.
    """
    for key in ("headline", "title"):
        if stated := flatten(document.meta.get(key, "")):
            return stated
    current = next((p for p in profile.positions if p.end is None), None)
    if current is None:
        return ""
    return f"{current.title} at {current.company}" if current.company else current.title


def _field_for(section: Section) -> str | None:
    """Which profile field a section feeds, if any.

    The untitled lead section is the summary: the grammar says prose before
    the first ``##`` is how a summary is written without a heading, and that
    is exactly LinkedIn's About.
    """
    title = to_plain_title(section.title)
    if not title:
        return "summary"
    words = set(title.split())
    for field, names in SECTIONS.items():
        if words & names:
            return field
    return None


def _position(entry: Entry) -> Position:
    role, org = entry.head.role, entry.head.org
    start, end = parse_range(flatten(entry.head.right))
    return Position(
        title=flatten(role if role is not None else entry.head.left),
        company=flatten(org or ""),
        location=flatten(entry.sub.left) if entry.sub else "",
        description=_blocks_text(entry.blocks),
        start=start,
        end=end,
    )


def _education(entry: Entry) -> Education:
    """An education entry: the school heads it, the degree line sits beneath.

    The degree line is one string on the page and two fields on LinkedIn, so
    it is split on the connectors people actually write -- " - " and " in " --
    and left whole when neither appears. Guessing further would put the wrong
    half in "Field of study" on a profile recruiters filter by.
    """
    dates = flatten(entry.head.right)
    degree = field = ""
    if entry.sub is not None:
        degree, field = _degree(flatten(entry.sub.left))
        dates = flatten(entry.sub.right) or dates
    start, end = _education_dates(dates)
    return Education(
        school=flatten(entry.head.left),
        degree=degree,
        field_of_study=field,
        description=_blocks_text(entry.blocks),
        start=start,
        end=end,
    )


def _education_dates(text: str) -> tuple[MonthYear | None, MonthYear | None]:
    """Read a degree line's dates, where a lone date is a graduation.

    The opposite of a position, and the reason this is not ``parse_range``.
    One date against a job means you started then and are there still; one
    date against a degree is when it was awarded, so it is the end. Reading it
    as a start would put "2020 - present" on a master's you finished.
    """
    start, end = parse_range(text)
    if end is None and start is not None and not is_open_ended(text):
        return None, start
    return start, end


def _degree(text: str) -> tuple[str, str]:
    parts = _DEGREE_SPLIT.split(text, maxsplit=1)
    if len(parts) != 2:
        return text, ""
    field = _MAJOR_PREFIX.sub("", parts[1]).strip()
    return parts[0].strip(), _SECOND_CLAUSE.sub("", field).strip()


def _skills(section: Section) -> list[Skill]:
    """Every skill named in the section, one per term.

    A resume groups them -- "**Languages**: Python, SQL" -- and LinkedIn has no
    groups, only a flat list it matches against its own vocabulary. So the
    label before the colon is dropped and the terms are split out one by one.
    """
    found: list[Skill] = []
    for text in _bullet_texts(section.blocks):
        _, colon, listed = text.partition(":")
        for term in _terms(listed if colon else text):
            found.append(Skill(name=term))
    return found


def _terms(text: str) -> list[str]:
    """Split a run of skills, reading a parenthetical for what it is.

    Two things wear brackets in these lists and they mean opposite things.
    "Python (advanced)" qualifies one skill, so the bracket is dropped and the
    name kept. "Orchestration (airflow, dagster)" names a category and then
    lists the skills, so the bracket is the content and the category is not a
    skill at all. Whether it holds a separator is what tells them apart.
    """
    out: list[str] = []
    for part in _split_top_level(text):
        if (match := _QUALIFIER.search(part)) is not None:
            part = part[: match.start()]
        elif part.endswith(")") and "(" in part:
            out += _terms(part[part.index("(") + 1 : -1])
            continue
        if name := part.strip(" .*"):
            out.append(name)
    return out


def _split_top_level(text: str) -> list[str]:
    """Split on separators outside brackets, so a nested list stays one part."""
    parts: list[str] = []
    depth = start = 0
    for i, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char in ",;/" and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _bullet_texts(blocks: list[Block]) -> list[str]:
    out: list[str] = []
    for block in blocks:
        if isinstance(block, BulletList):
            for item in block.items:
                out.append(flatten(item.text))
                out += [flatten(child.text) for child in item.children]
        elif isinstance(block, Paragraph):
            out.append(flatten(block.text))
    return out


def _blocks_text(blocks: list[Block]) -> str:
    """Blocks as the plain text a LinkedIn field holds.

    Bullets keep their shape, because a description written as a paragraph of
    run-together achievements is unreadable, and the glyph is the only list
    LinkedIn has.
    """
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, Paragraph):
            if text := flatten(block.text):
                parts.append(text)
        elif isinstance(block, BulletList):
            lines = [line for item in block.items for line in _bullet_lines(item)]
            if lines:
                parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _bullet_lines(item: Bullet, depth: int = 0) -> list[str]:
    indent = "  " * depth
    lines = [f"{indent}{BULLET}{flatten(item.text)}"] if item.text.strip() else []
    for child in item.children:
        lines += _bullet_lines(child, depth + 1)
    return lines


def _dedupe(skills: list[Skill]) -> list[Skill]:
    """First spelling wins, so the order the resume chose is the order kept."""
    seen: set[str] = set()
    return [s for s in skills if not (s.key in seen or seen.add(s.key))]
