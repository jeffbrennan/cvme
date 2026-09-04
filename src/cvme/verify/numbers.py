"""Extract and normalise quantitative claims.

The unit of comparison retains value, semantic unit, and approximation, so that
``100k``, ``100,000`` and ``$100K`` compare as intended while ``$98k`` and
``$100k`` do not. ``14 facilities`` is distinct from ``14 engineers``, and
``100k`` is distinct from ``~100k`` or ``100k+``. Matching is deliberately
exact: changing the meaning of a corpus figure is precisely the failure this
is here to catch.
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
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
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
    (?P<prefix>~|≈|about\s+|approximately\s+|over\s+|more\s+than\s+|at\s+least\s+|up\s+to\s+)?
    (?P<currency>[$£€])?
    (?P<value>\d{1,3}(?:,\d{3})+ | \d+(?:\.\d+)?)
    (?P<scale>[kKmMbB]|bn|BN|Bn)?
    (?P<percent>%)?
    (?P<plus>\+)?
    \s*
    (?P<unit>[A-Za-z]{1,20})?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_WORD_NUMBER = re.compile(
    r"\b(?P<prefix>about\s+|approximately\s+|over\s+|more\s+than\s+|"
    r"at\s+least\s+|up\s+to\s+)?(?P<word>"
    + "|".join(WORDS)
    + r")\s+(?P<unit>[A-Za-z]{1,20})\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"^(19|20)\d{2}$")
_CONNECTORS = {"and", "in", "of", "or", "other", "per", "to"}
_NON_MEASUREMENT_UNITS = {
    "claim",
    "item",
    "paragraph",
    "requirement",
    "role",
    "section",
    "sentence",
    "thing",
    "way",
}
_PRONOUN_UNITS = {"it", "them", "these", "those"}


def _inside_identifier(text: str, start: int) -> bool:
    """Whether the digits at ``start`` are part of a name rather than a count.

    ``AZ-900``, ``SOC2`` and ``ISO-27001`` are certificates and standards, and
    a resume's skills section is full of them. A digit welded to a letter, or
    hyphenated straight onto one, is part of that token. A numeric range keeps
    working: the hyphen in ``10-15`` follows a digit, not a letter.
    """
    before = text[:start]
    if not before:
        return False
    if before[-1].isalpha():
        return True
    return before[-1] == "-" and len(before) > 1 and before[-2].isalpha()


ClaimKey = tuple[float, str | None, str]


@dataclass(frozen=True)
class Claim:
    """One quantitative claim, as written and as normalised."""

    raw: str
    value: float
    unit: str | None
    column: int
    qualifier: str = ""

    @property
    def key(self) -> ClaimKey:
        return (self.value, self.unit, self.qualifier)

    def __str__(self) -> str:
        return self.raw


def _canonical_unit(token: str | None) -> str | None:
    if not token:
        return None
    lowered = token.lower()
    if lowered in _CONNECTORS:
        return None
    if lowered in UNIT_ALIASES:
        return UNIT_ALIASES[lowered]
    if lowered.endswith("ies") and len(lowered) > 3:
        return f"{lowered[:-3]}y"
    if lowered.endswith("s") and not lowered.endswith("ss"):
        return lowered[:-1]
    return lowered


def _unit_after(match: re.Match[str], text: str) -> str | None:
    """Return the measured noun, skipping connectors such as ``in``."""
    token = match.group("unit")
    if token and token.lower() in _CONNECTORS:
        following = re.match(r"\s*([A-Za-z]{1,20})", text[match.end() :])
        token = following.group(1) if following else None
    if token and token.lower() in _PRONOUN_UNITS:
        return None
    return _canonical_unit(token)


def _qualifier(match: re.Match[str]) -> str:
    prefix = re.sub(r"\s+", " ", (match.group("prefix") or "").strip().lower())
    suffix = "+" if match.groupdict().get("plus") else ""
    return " ".join(part for part in (prefix, suffix) if part)


def extract(text: str) -> list[Claim]:
    """Every quantitative claim in a run of prose.

    Bare four-digit years are skipped: they are dates, not claims, and a
    resume is full of them. So are digits inside an identifier such as
    ``AZ-900``, which is a certificate rather than a quantity of anything.
    """
    claims: list[Claim] = []

    for match in _NUMBER.finditer(text):
        digits = match.group("value")
        if _YEAR.match(digits) and not match.group("scale"):
            continue
        if _inside_identifier(text, match.start("value")):
            continue
        value = float(digits.replace(",", ""))
        if scale := match.group("scale"):
            value *= SCALES[scale.lower()]

        subject = _unit_after(match, text)
        unit: str | None
        if match.group("percent"):
            unit = f"%:{subject}" if subject else "%"
        elif match.group("currency"):
            unit = f"currency:{subject}" if subject else "currency"
        else:
            unit = subject

        # Rebuild the display form from the parts that matched: group(0) can
        # trail an unrecognised word ("9 other", "$100k per") because the unit
        # group is optional and greedy.
        raw = match.group(0).strip()
        claims.append(
            Claim(
                raw=raw,
                value=value,
                unit=unit,
                qualifier=_qualifier(match),
                column=match.start(),
            )
        )

    for match in _WORD_NUMBER.finditer(text):
        unit = _canonical_unit(match.group("unit"))
        if unit is None or unit in _NON_MEASUREMENT_UNITS:
            continue
        claims.append(
            Claim(
                raw=match.group(0).strip(),
                value=WORDS[match.group("word").lower()],
                unit=unit,
                qualifier=_qualifier(match),
                column=match.start(),
            )
        )

    return sorted(claims, key=lambda c: c.column)
