"""Reading the profile PDF LinkedIn hands you in one click.

*Your profile > More > Save to PDF*. It downloads immediately, which is the
whole reason this path exists: the data export is more complete but arrives by
email, and a check you have to wait for is a check you stop running.

There is almost no new code here. ``cvme convert`` already turns a PDF resume
into the markdown grammar by recovering structure from geometry, and a profile
PDF is resume-shaped -- section headings, roles with dates, bulleted
descriptions. So the path is the existing pipeline pointed at a different
document::

    PDF --convert--> markdown --parse--> document IR --project--> Profile

What the PDF cannot vouch for is skills. LinkedIn prints a "Top Skills"
section holding about three of them, so a profile with thirty skills yields a
document that appears to have three. Auditing that would report twenty-seven
skills as missing from a profile that has them all, so skills are declared
uncovered and the audit skips them. Use the data export when the skills list
is what you want checked.
"""

from __future__ import annotations

import re
from pathlib import Path

from cvme.convert import pdf_to_markdown
from cvme.errors import ConvertError
from cvme.linkedin.dates import MONTH_PATTERN, parse_point
from cvme.linkedin.live import Source, SourceError
from cvme.linkedin.model import Education, Profile
from cvme.linkedin.project import degree_and_field, to_profile
from cvme.md.parse import parse

#: What a profile PDF can report faithfully. Skills are excluded on purpose
#: -- see the module docstring. The rest is claimed only once the read has
#: shown it actually recovered them.
COVERS = frozenset({"headline", "summary", "positions", "educations"})

#: The award date that ends a degree line. Found rather than anchored,
#: because the line above a note like "Certificate: Data Science" can arrive
#: with that note run onto the end of it: a PDF has no paragraphs, so two
#: lines set close together come back as one.
_AWARD_DATE = re.compile(
    rf"((?:(?:{MONTH_PATTERN})\.?\s+)?(?:19|20)\d{{2}})", re.IGNORECASE
)


def read(path: Path) -> Source:
    """A profile PDF as a :class:`Source`."""
    try:
        markdown = pdf_to_markdown(path)
    except ConvertError as exc:
        raise SourceError(
            f"{path}: could not read this PDF ({exc}).\n"
            "  If it is a LinkedIn profile PDF, `cvme convert` on the same file "
            "shows what cvme sees."
        ) from exc

    profile, _ = to_profile(parse(markdown, path=str(path)))
    profile = _recover_degrees(profile)
    if not _says_anything(profile):
        raise SourceError(
            f"{path}: no profile content recovered from this PDF.\n"
            "  A PDF records layout, not intent, so a profile laid out in a way "
            "cvme does not recognise reads as empty.\n"
            "  Run `cvme convert` on it to see what was recovered, or use the "
            "data export instead."
        )
    covers = set(COVERS) - _empty(profile) - _unrecovered(profile)
    return Source(
        profile=profile,
        covers=covers,
        label=f"profile PDF ({path.name})",
    )


def _recover_degrees(profile: Profile) -> Profile:
    """Put the degree back where the page break-up lost it.

    A PDF records layout, not intent, so ``convert`` sees a school as an entry
    heading and the degree beneath it as ordinary prose rather than the
    entry's second line. The degree is still there and still ends with the
    award date, so it is recovered here rather than by teaching the shared
    projection a rule that only a PDF needs.
    """
    recovered: list[Education] = []
    for education in profile.educations:
        if education.degree or not education.description:
            recovered.append(education)
            continue
        text = education.description
        match = _AWARD_DATE.search(text)
        if match is None or not (line := text[: match.start()].strip(" |,")):
            recovered.append(education)
            continue
        degree, field = degree_and_field(line)
        recovered.append(
            education.model_copy(
                update={
                    "degree": degree,
                    "field_of_study": field,
                    "description": text[match.end() :].strip(" |,\n"),
                    "end": education.end or parse_point(match.group(1)),
                }
            )
        )
    return profile.model_copy(update={"educations": recovered}, deep=True)


def _unrecovered(profile: Profile) -> set[str]:
    """Parts the read could not put back together, so cannot be compared.

    Education is all or nothing: one entry left as a bare school name would
    audit as a degree missing from a profile that has it.
    """
    if any(not education.degree for education in profile.educations):
        return {"educations"}
    return set()


def _says_anything(profile: Profile) -> bool:
    return bool(profile.positions or profile.educations or profile.summary)


def _empty(profile: Profile) -> set[str]:
    """Parts the PDF held nothing for, which it therefore cannot vouch for.

    A profile PDF with no Education section is a PDF that does not mention
    education, not a profile that has none.
    """
    return {part for part in COVERS if not getattr(profile, part)}
