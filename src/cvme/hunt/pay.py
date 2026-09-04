"""What the posting says it pays, read as a number rather than a sentence.

A posting states pay in whatever shape its author felt like: a JSON-LD
``baseSalary``, a range in the body, an hourly rate, or nothing at all. To be
worth a column it has to become one comparable number, so everything is
annualised on the way in and the text it was read from is kept beside it.

Nothing is guessed. A figure is only believed where the posting marks it as
money -- a currency, a ``k`` suffix, or a stated period -- so "5+ years" and
"a team of 30" are not read as salaries, and an annualised figure outside
:data:`PLAUSIBLE` is discarded rather than reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Annualised bounds a believable salary falls inside. Anything outside them
#: was a headcount, a revenue figure, or a phone number.
PLAUSIBLE = (10_000, 3_000_000)

#: Hours, days, weeks and months in a working year.
PERIODS = {
    "hour": 2080,
    "day": 260,
    "week": 52,
    "month": 12,
    "year": 1,
}

_SYMBOLS = {
    "$": "$", "£": "£", "€": "€",
    "usd": "$", "gbp": "£", "eur": "€", "cad": "$", "aud": "$",
}  # fmt: skip

_CURRENCY = r"(?:US\$|A\$|C\$|\$|£|€|USD|GBP|EUR|CAD|AUD)"
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_AMOUNT = re.compile(
    rf"(?P<currency>{_CURRENCY})?\s*(?P<number>{_NUMBER})\s*(?P<scale>[kKmM])?\b"
)
_SEPARATOR = re.compile(r"^\s*(?:-|–|—|to|through|up to|and)\s*$", re.IGNORECASE)
_PERIOD = re.compile(
    r"(?:per|/|a|an|each)\s*(hour|hr|day|week|wk|month|mo|year|yr|annum)"
    r"|(hourly|daily|weekly|monthly|yearly|annually|annualized|annualised|annual)",
    re.IGNORECASE,
)
_RETIREMENT = re.compile(r"\b40[13][kb]\b", re.IGNORECASE)
_PAY_WORD = re.compile(
    r"salar|compensat|\bpay\b|\bpays\b|\bwage|\brate\b|\bbase\b|\bearn",
    re.IGNORECASE,
)

_PERIOD_NAMES = {
    "hr": "hour", "hourly": "hour",
    "daily": "day",
    "wk": "week", "weekly": "week",
    "mo": "month", "monthly": "month",
    "yr": "year", "annum": "year", "yearly": "year", "annually": "year",
    "annual": "year", "annualized": "year", "annualised": "year",
}  # fmt: skip

#: How far either side of a figure to look for the period it is stated in.
_WINDOW = 30


@dataclass(frozen=True)
class Pay:
    """A pay range, annualised, and the words it was read from."""

    low: int = 0
    high: int = 0
    #: The period the posting stated, before annualising. Empty when inferred.
    period: str = ""
    currency: str = ""
    stated: str = ""

    def __bool__(self) -> bool:
        return bool(self.low or self.high)

    @property
    def midpoint(self) -> int:
        """The number to sort and compare on; an open range is its own bound."""
        both = [n for n in (self.low, self.high) if n]
        return round(sum(both) / len(both)) if both else 0

    @property
    def short(self) -> str:
        """One cell of a table: ``$150k-190k``, ``$150k+``, or a dash."""
        if not self:
            return "-"
        symbol = self.currency
        if self.low and self.high and self.low != self.high:
            return f"{symbol}{thousands(self.low)}-{thousands(self.high)}"
        return f"{symbol}{thousands(self.midpoint)}"


#: A posting that has not been read, or that said nothing about pay.
NO_PAY = Pay()


def thousands(amount: int) -> str:
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}m".replace(".0m", "m")
    return f"{amount / 1000:.0f}k"


@dataclass(frozen=True)
class _Figure:
    value: float
    start: int
    end: int
    currency: str
    marked: bool


def _symbol(marker: str) -> str:
    """The symbol to print a figure with, from whatever marked it as money."""
    token = marker.strip().lower()
    if not token:
        return ""
    return _SYMBOLS.get(token) or _SYMBOLS.get(token[-1], "$")


def _figures(text: str) -> list[_Figure]:
    found: list[_Figure] = []
    for match in _AMOUNT.finditer(text):
        if _RETIREMENT.match(text, match.start("number")):
            continue
        value = float(match["number"].replace(",", ""))
        scale = (match["scale"] or "").lower()
        if scale == "k":
            value *= 1000
        elif scale == "m":
            value *= 1_000_000
        currency = _symbol(match["currency"] or "")
        found.append(
            _Figure(
                value,
                match.start(),
                match.end(),
                currency,
                bool(match["currency"] or scale),
            )
        )
    return found


def _period_near(text: str, start: int, end: int) -> str:
    """The period stated around a figure, or empty where none is."""
    window = text[max(0, start - _WINDOW) : end + _WINDOW]
    if (match := _PERIOD.search(window)) is None:
        return ""
    name = (match[1] or match[2] or "").lower()
    return _PERIOD_NAMES.get(name, name)


def _paid_near(text: str, start: int, end: int) -> bool:
    """Whether an unmarked figure sits in a sentence that is about pay.

    Without this, "10,000 patients per year" reads as a salary: it has a
    magnitude and a period, and nothing else distinguishes it.
    """
    window = text[max(0, start - _WINDOW * 2) : end + _WINDOW]
    return _PAY_WORD.search(window) is not None


def _annualise(value: float, period: str) -> int:
    if period:
        return round(value * PERIODS[period])
    # Unstated: an hourly rate is the only thing written in three figures.
    return round(value * PERIODS["hour"]) if value < 1000 else round(value)


def read(*texts: str) -> Pay:
    """The first believable pay range across ``texts``, in the order given.

    The order is the argument order, so a posting's own ``salary`` field wins
    over a number found in its prose.
    """
    for text in texts:
        if found := _read_one(text):
            return found
    return Pay()


def _read_one(text: str) -> Pay:
    if not text.strip():
        return Pay()
    figures = _figures(text)
    index = 0
    while index < len(figures):
        first = figures[index]
        second = None
        if index + 1 < len(figures):
            following = figures[index + 1]
            if _SEPARATOR.match(text[first.end : following.start]):
                second = following

        last = second or first
        period = _period_near(text, first.start, last.end)
        if not (
            first.marked
            or last.marked
            or (period and _paid_near(text, first.start, last.end))
        ):
            index += 1
            continue

        low = _annualise(first.value, period)
        high = _annualise(last.value, period) if second else 0
        floor, ceiling = PLAUSIBLE
        if not floor <= low <= ceiling or (high and not floor <= high <= ceiling):
            index += 1
            continue
        if high and high < low:
            low, high = high, low
        return Pay(
            low=low,
            high=high,
            period=period,
            currency=first.currency or last.currency,
            stated=text[first.start : last.end].strip(),
        )
    return Pay()
