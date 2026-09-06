"""Capture salary text using the same reader as application pay comparisons."""

from cvme.hunt.pay import read


def from_description(description: str) -> str:
    """Keep the stated amount and period; never store an inferred annual rate."""
    pay = read(description)
    if not pay:
        return ""
    return f"{pay.stated} per {pay.period}" if pay.period else pay.stated
