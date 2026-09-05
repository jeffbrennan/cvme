"""Resolved style: every length a plain number of points.

Points rather than CSS-ish strings because the template does arithmetic on
these values and the geometry tests assert against them. A string like
``"0.8in"`` would have to be evaluated inside Typst, which puts the one
quantity the tests care about behind an ``eval``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from cvme.errors import ConfigError

PRESET_DIR = Path(__file__).parent / "presets"


class Style(BaseModel):
    """Every knob the resume template reads."""

    model_config = {"extra": "forbid"}

    # page
    paper: str = "us-letter"
    margin_x: float = 57.6
    margin_y: float = 36.0

    # Ink is the body colour and the fallback for every other colour here: a
    # style sets only the ones it wants to differ, and an empty string means
    # "whatever this element inherits". That keeps a preset readable as the
    # short list of decisions it actually makes.
    ink: str = "#000000"
    # The accent surfaces -- the name, the section headings, the rule under
    # the letterhead, the links -- all take their colour from here unless they
    # override it, so matching a company's branding is one value. Unset means
    # ink, and a monochrome document.
    accent: str = ""
    muted: str = ""  # dates, organisations, contact line; falls back to ink

    # body text
    body_font: str = "Carlito"
    body_size: float = 11.0
    leading: float = 6.4
    # How small the fit ladder may scale body text before it gives up. The
    # default is the floor from when it was fixed, so a document that says
    # nothing tightens as it always did; raise it to protect reading comfort
    # and make the ladder spend margins or content instead.
    body_size_min: float = 9.0

    # Inline `**bold**`. A resume carries a lot of it -- every skill label,
    # every role -- and turning it down in one place is how a page stops
    # reading as shouted without editing the markdown.
    strong_weight: str = "bold"
    strong_color: str = ""

    # links. Underlining every URL is the browser's convention, not print's,
    # and on a resume it draws the eye to the least important line on the page.
    link_underline: bool = True
    link_color: str = ""  # falls back to accent, then ink

    # name and contact line
    name_font: str = "Fira Code"
    name_size: float = 19.5
    name_weight: int = 600
    name_tracking: float = 0.0
    name_color: str = ""  # falls back to accent, then ink
    contact_size: float = 11.0
    contact_sep: str = " | "
    contact_color: str = ""  # falls back to muted, then ink
    header_gap: float = 10.0
    # A rule under the letterhead. Zero weight draws nothing.
    header_rule: float = 0.0
    header_rule_gap: float = 5.0
    header_rule_color: str = ""  # falls back to accent

    # section headers
    section_font: str = ""  # falls back to body_font
    section_size: float = 12.0
    section_weight: str = "bold"
    section_uppercase: bool = True
    section_tracking: float = 0.0
    section_gap_before: float = 7.0
    section_gap_after: float = 11.3
    # A rule under each section heading: the separator that tells a reader
    # where one part of the document ends. Zero weight draws nothing.
    section_rule: float = 0.0
    section_rule_gap: float = 3.0
    section_rule_color: str = ""  # falls back to accent

    # entries
    entry_gap_before: float = 6.7
    entry_weight: str = "bold"  # a `### Left | Right` with no ` @ ` split
    role_weight: str = "bold"
    org_weight: str = "regular"
    # Italic is what separates the organisation from the bullet under it when
    # both are regular weight in the same colour. Weight cannot do it: the
    # role has already spent bold, and a second grade of it flattens the pair.
    org_style: str = "normal"
    org_color: str = ""
    sub_weight: str = "bold"
    sub_color: str = ""
    date_size: float = 10.0
    date_weight: str = "bold"
    date_color: str = ""  # falls back to muted, then ink
    role_sep: str = " – "  # en dash, as in the reference layout

    # bullets. marker_glyph is a real character so that it survives text
    # extraction; set it to "" to draw a filled square instead.
    marker_glyph: str = "\u2022"
    marker_size: float = 7.0
    # Zero for a glyph marker: U+2022 is already optically centred, and any
    # shift puts the marker on its own baseline, which splits the line in
    # extracted text. The drawn-box marker wants about -0.5.
    marker_baseline: float = 0.0
    # How far the fit ladder may cut into the margins before it gives up. The
    # defaults are the floors from when they were fixed, so a document that
    # says nothing tightens as it always did; raise them to keep white space at
    # the edges and make the ladder spend its other steps instead.
    margin_x_min: float = 43.2
    margin_y_min: float = 21.6

    marker_indent: float = 18.0
    body_indent: float = 10.9
    # Extra space between one bullet and the next, on top of the leading a
    # tight list already puts there. Zero is a tight list, which is the
    # default: a resume that is not short wants the space back.
    bullet_gap: float = 0.0
    # Space between the end of a body line and the column the dates occupy.
    # Body text is held clear of that column so the page has a right edge to
    # follow, instead of bullets running the full width under the dates.
    # Negative turns the inset off, which is the default: holding the body
    # clear costs the width of the date column, and whether a page can afford
    # that depends on how much is on it. Set it per document to switch on.
    date_gutter: float = -1.0
    # Even out the lines of a bullet that wraps, rather than filling the first
    # and letting the rest run short. Off by default, and worth leaving off
    # where date_gutter is set: the first line then runs to the gutter, which
    # is the edge it was cut to, and the second finishes the sentence. Turn it
    # on for a page with no column to stop short of, where a first line that
    # fills the whole measure leaves a stub under it.
    balance_bullets: bool = False

    # letters
    letter_gap: float = 24.0  # letterhead to the date line
    letter_block_gap: float = 20.0  # between date, recipient and salutation
    paragraph_gap: float = 13.4  # between body paragraphs
    signature_gap: float = 26.0  # room to sign between closing and name

    # output
    pdf_standard: str = ""
    lang: str = "en"

    # What to do when the document exceeds max_pages.
    #   fit   -- tighten along the density ladder until it fits (resumes)
    #   warn  -- render as authored and report the overage
    #   error -- refuse, with a diagnostic (letters: prose cannot be squeezed
    #            without making it worse, and only the author can decide which
    #            paragraph goes)
    max_pages: int = 1
    on_overflow: Literal["fit", "warn", "error"] = "fit"

    def dump(self) -> dict[str, Any]:
        return self.model_dump()


def load_preset(name: str) -> Style:
    """Load a bundled preset by name."""
    path = PRESET_DIR / f"{name}.toml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in PRESET_DIR.glob("*.toml")))
        raise ConfigError(f"unknown style preset '{name}'; available: {available}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Style(**data.get("style", {}))


def resolve(preset: str = "standard", overrides: dict[str, Any] | None = None) -> Style:
    """Layer preset then explicit overrides."""
    base = load_preset(preset).model_dump()
    base.update({k: v for k, v in (overrides or {}).items() if v is not None})
    try:
        return Style(**base)
    except Exception as exc:
        raise ConfigError(f"invalid style: {exc}") from exc
