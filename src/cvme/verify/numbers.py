"""Extract and normalise quantitative claims.

The unit of comparison is a normalised ``(value, unit)`` pair, so that
``100k``, ``100,000`` and ``$100K`` compare as intended while ``$98k`` and
``$100k`` do not. Matching is deliberately exact: rounding a corpus figure up
in the output is precisely the failure this is here to catch. If you want to
claim "~$100k", write that in the corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Multipliers for magnitude suffixes.
SCALES: dict[str, float] = {
    "k": 1e3,
    "m": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "t": 1e12,
}

#: Spelled-out numbers, which carry claims as readily as digits do.
WORDS: dict[str, float] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}

#: Units normalised to a singular canonical form.
UNIT_ALIASES: dict[str, str] = {
    "yrs": "year",
    "yr": "year",
    "years": "year",
    "year": "year",
    "months": "month",
    "month": "month",
    "mo": "month",
    "weeks": "week",
    "week": "week",
    "wk": "week",
    "days": "day",
    "day": "day",
    "hours": "hour",
    "hour": "hour",
    "hrs": "hour",
    "hr": "hour",
    "h": "hour",
    "minutes": "minute",
    "minute": "minute",
    "mins": "minute",
    "min": "minute",
    "tb": "tb",
    "gb": "gb",
    "pb": "pb",
    "mb": "mb",
}

_NUMBER = re.compile(
    r"""
    (?P<currency>[$£€])?
    (?P<value>\d{1,3}(?:,\d{3})+ | \d+(?:\.\d+)?)
    (?P<scale>[kKmMbB]|bn|BN|Bn)?
    \s*
    (?P<percent>%)?
    \s*
    (?P<unit>[A-Za-z]{1,7})?
    """,
    re.VERBOSE,
)
_WORD_NUMBER = re.compile(
    r"\b(?P<word>" + "|".join(WORDS) + r")\s+(?P<unit>[A-Za-z]{1,7})\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class Claim:
    """One quantitative claim, as written and as normalised."""

    raw: str
    value: float
    unit: str | None
    column: int

    @property
    def key(self) -> tuple[float, str | None]:
        return (self.value, self.unit)

    def __str__(self) -> str:
        return self.raw


def _canonical_unit(token: str | None) -> str | None:
    if not token:
        return None
    return UNIT_ALIASES.get(token.lower())


def extract(text: str) -> list[Claim]:
    """Every quantitative claim in a run of prose.

    Bare four-digit years are skipped: they are dates, not claims, and a
    resume is full of them.
    """
    claims: list[Claim] = []

    for match in _NUMBER.finditer(text):
        digits = match.group("value")
        if _YEAR.match(digits) and not match.group("scale"):
            continue
        value = float(digits.replace(",", ""))
        if scale := match.group("scale"):
            value *= SCALES[scale.lower()]

        unit: str | None = None
        if match.group("percent"):
            unit = "%"
        elif match.group("currency"):
            unit = "currency"
        else:
            unit = _canonical_unit(match.group("unit"))

        # Rebuild the display form from the parts that matched: group(0) can
        # trail an unrecognised word ("9 other", "$100k per") because the unit
        # group is optional and greedy.
        raw = "".join(
            part
            for part in (
                match.group("currency"),
                digits,
                match.group("scale"),
                match.group("percent"),
            )
            if part
        )
        if unit not in (None, "currency", "%"):
            raw = f"{raw} {match.group('unit')}"
        claims.append(Claim(raw=raw, value=value, unit=unit, column=match.start()))

    for match in _WORD_NUMBER.finditer(text):
        unit = _canonical_unit(match.group("unit"))
        if unit is None:
            continue  # "one claim per bullet" is prose, not a measurement
        claims.append(
            Claim(
                raw=match.group(0).strip(),
                value=WORDS[match.group("word").lower()],
                unit=unit,
                column=match.start(),
            )
        )

    return sorted(claims, key=lambda c: c.column)
