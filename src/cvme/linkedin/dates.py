"""Reading the date range out of an entry header.

The grammar puts dates on the right of the pipe and says nothing about their
shape, because a PDF only ever had to render them. LinkedIn stores a month and
a year per endpoint, so the free text has to be read back.

What is accepted is what people actually write in these documents. What is not
accepted is guessed at: an unparseable range leaves both endpoints unset and
the sync reports the field as unknown rather than inventing a January.
"""

from __future__ import annotations

import re

from cvme.linkedin.model import MonthYear

#: Both dashes plus the ASCII hyphen and the word, because all four appear in
#: real documents and ``convert`` emits whichever the source PDF used.
#:
#: The alternatives are ordered and deliberately fussy about spacing: a bare
#: hyphen also joins a year to a month in ``2023-07``, so it only separates a
#: range when it is spaced or when it sits between two four-digit years.
_SEPARATOR = re.compile(
    r"(?:\s+[-–—]\s+|\s*[–—]\s*|\s+to\s+|(?<=\d{4})-(?=\d{4}))",
    re.IGNORECASE,
)

#: Anything meaning "this one is still going".
_OPEN = frozenset({"present", "current", "now", "today", "ongoing", ""})

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}  # fmt: skip

#: The month spellings above, as an alternation, longest first so "sept"
#: cannot be matched as "sep" with a stray "t" left over. Exported because
#: a caller hunting a date in running text must not treat any word before a
#: year as a month: "Master of Science 2020" names no month.
MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))

_MONTH_YEAR = re.compile(r"^([A-Za-z]+)\.?\s+(\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})[/-](\d{1,2})$")
_YEAR = re.compile(r"^(\d{4})$")


def parse_range(text: str) -> tuple[MonthYear | None, MonthYear | None]:
    """Split ``Jul 2023 - Present`` into its endpoints.

    An open-ended range gives ``(start, None)``, which is also what an
    unreadable end gives. They are the same to LinkedIn, which stores the
    absence of an end date as "current".
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        return None, None
    parts = _SEPARATOR.split(cleaned, maxsplit=1)
    start = parse_point(parts[0])
    end = parse_point(parts[1]) if len(parts) > 1 else None
    return start, end


def parse_point(text: str) -> MonthYear | None:
    """One endpoint. ``None`` for "Present" and for anything unrecognised."""
    cleaned = " ".join(text.split()).strip(".,")
    if cleaned.casefold() in _OPEN:
        return None
    if match := _MONTH_YEAR.match(cleaned):
        if (month := _MONTHS.get(match.group(1).casefold())) is not None:
            return MonthYear(year=int(match.group(2)), month=month)
        return None
    if match := _YEAR_MONTH.match(cleaned):
        month = int(match.group(2))
        if 1 <= month <= 12:
            return MonthYear(year=int(match.group(1)), month=month)
        return None
    if match := _YEAR.match(cleaned):
        return MonthYear(year=int(match.group(1)))
    return None


def is_open_ended(text: str) -> bool:
    """Whether the range says the role is still held, rather than failing to parse.

    Worth distinguishing from ``end is None``: "Present" is a statement and a
    date cvme could not read is a gap, and only the second one is worth a
    warning.
    """
    parts = _SEPARATOR.split(" ".join(text.split()), maxsplit=1)
    return len(parts) > 1 and parts[1].casefold().strip(".,") in _OPEN
