"""Accent colours: the one colour decision a document makes.

An accent is named or given as hex, and every accent surface on the page --
the name, the section headings, the rule under the letterhead, the links --
takes it from here. That is what makes matching a company's branding a single
argument rather than five.

The one thing this refuses is an accent too light to read. A resume is printed,
photocopied and read on a projector, and a brand colour picked for a white logo
on a coloured field is routinely too pale to set type in. Rejecting it with the
measured ratio is more useful than rendering something the reader squints at.
"""

from __future__ import annotations

import re

from cvme.errors import ConfigError

#: Dark, print-safe accents, each one checked against the contrast floor below.
#: Named so that a preset or a command line can say `teal` and mean this teal.
NAMED: dict[str, str] = {
    "black": "#000000",
    "graphite": "#16191d",
    "slate": "#33414f",
    "navy": "#1d3f6e",
    "teal": "#0f5f57",
    "forest": "#1f4d2e",
    "maroon": "#7a1f2b",
    "burgundy": "#5c1a33",
    "plum": "#4f2d63",
    "rust": "#8a4014",
}

#: WCAG AA for body text against white. An accent sets headings and the name,
#: which are larger, but it also sets links inside the contact line at 10pt.
MIN_CONTRAST = 4.5

_HEX = re.compile(r"\A#?(?P<digits>[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")


def parse(value: str) -> str:
    """Normalise a named colour or hex string to ``#rrggbb``.

    Raises ``ConfigError`` for anything unrecognised, and for a colour that
    does not reach the contrast floor against white.
    """
    text = value.strip()
    if not text:
        raise ConfigError("an accent needs a colour; give a name or a hex value")
    if (named := NAMED.get(text.lower())) is not None:
        return named

    match = _HEX.match(text)
    if match is None:
        raise ConfigError(
            f"'{value}' is not a colour: give #rrggbb, or one of "
            f"{', '.join(sorted(NAMED))}"
        )
    digits = match.group("digits").lower()
    if len(digits) == 3:
        digits = "".join(d * 2 for d in digits)
    hexcolor = f"#{digits}"

    ratio = contrast(hexcolor)
    if ratio < MIN_CONTRAST:
        raise ConfigError(
            f"{hexcolor} contrasts {ratio:.1f}:1 against white, below the "
            f"{MIN_CONTRAST}:1 a reader needs. Use a darker shade of it -- a "
            f"brand's ink colour rather than the one from its logo."
        )
    return hexcolor


def contrast(hexcolor: str) -> float:
    """WCAG contrast ratio of ``hexcolor`` against white."""
    return 1.05 / (_luminance(hexcolor) + 0.05)


def _luminance(hexcolor: str) -> float:
    channels = []
    for i in (1, 3, 5):
        c = int(hexcolor[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue
