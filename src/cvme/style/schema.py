"""Resolved style: every length a plain number of points.

Points rather than CSS-ish strings because the template does arithmetic on
these values and the geometry tests assert against them. A string like
``"0.8in"`` would have to be evaluated inside Typst, which puts the one
quantity the tests care about behind an ``eval``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

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
    ink: str = "#000000"

    # body text
    body_font: str = "Carlito"
    body_size: float = 11.0
    leading: float = 6.4

    # name and contact line
    name_font: str = "Fira Code"
    name_size: float = 19.5
    name_weight: int = 600
    contact_size: float = 11.0
    contact_sep: str = " | "
    header_gap: float = 10.0

    # section headers
    section_size: float = 12.0
    section_uppercase: bool = True
    section_gap_before: float = 7.0
    section_gap_after: float = 11.3

    # entries
    entry_gap_before: float = 6.7
    date_size: float = 10.0
    role_sep: str = " – "  # en dash, as in the reference layout

    # bullets. marker_glyph is a real character so that it survives text
    # extraction; set it to "" to draw a filled square instead.
    marker_glyph: str = "\u2022"
    marker_size: float = 7.0
    # Zero for a glyph marker: U+2022 is already optically centred, and any
    # shift puts the marker on its own baseline, which splits the line in
    # extracted text. The drawn-box marker wants about -0.5.
    marker_baseline: float = 0.0
    marker_indent: float = 18.0
    body_indent: float = 10.9

    # output
    pdf_standard: str = ""
    lang: str = "en"

    # fitting
    max_pages: int = 1
    autofit: bool = True

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
