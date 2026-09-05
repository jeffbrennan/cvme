"""Accent colours: parsing, the contrast floor, and where they reach.

An accent is the one colour decision a document makes, so the two things worth
holding are that it is refused when it would be unreadable, and that setting it
once reaches every surface that should follow it.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest

from cvme.config import AccentConfig
from cvme.errors import ConfigError
from cvme.models import Document
from cvme.render.engine import compile_document
from cvme.style.color import MIN_CONTRAST, NAMED, contrast, parse
from cvme.style.schema import resolve
from tests.geometry import measure


@pytest.mark.parametrize("name", sorted(NAMED))
def test_every_named_accent_clears_the_contrast_floor(name: str) -> None:
    assert contrast(NAMED[name]) >= MIN_CONTRAST


def test_names_and_hex_both_parse() -> None:
    assert parse("navy") == NAMED["navy"]
    assert parse("NAVY") == NAMED["navy"]
    assert parse("#8A1538") == "#8a1538"
    assert parse("8a1538") == "#8a1538"
    assert parse("#134") == "#113344"  # shorthand expands


def test_a_colour_too_pale_to_read_is_refused() -> None:
    with pytest.raises(ConfigError, match="contrasts"):
        parse("#7fd4c1")


def test_a_non_colour_names_the_alternatives() -> None:
    with pytest.raises(ConfigError, match="navy"):
        parse("corporate blue")
    with pytest.raises(ConfigError, match="needs a colour"):
        parse("  ")


def test_a_company_accent_is_matched_without_regard_to_case() -> None:
    accents = AccentConfig(default="graphite", companies={"Northwind": "navy"})
    assert accents.among("northwind") == "navy"
    assert accents.among("  NORTHWIND ") == "navy"
    assert accents.among("Someone Else") == "graphite"


def _colours(pdf: Path, needle: str) -> set[tuple[float, ...]]:
    line = measure(pdf).find(needle)
    with pdfplumber.open(pdf) as opened:
        return {
            tuple(round(v, 2) for v in c["non_stroking_color"])
            for c in opened.pages[0].chars
            if c["text"].strip()
            and abs((792 - c["matrix"][5]) - line.baseline) < 1
            and c["size"] > line.size - 0.5
        }


@pytest.mark.parametrize("preset", ["sans", "serif"])
def test_one_accent_reaches_the_name_and_the_headings(
    resume_doc: Document, tmp_path: Path, preset: str
) -> None:
    """`--accent` is a single argument because the presets leave it one."""
    style = resolve(preset, {"accent": parse("maroon")})
    pdf = compile_document(resume_doc, style, output=tmp_path / f"{preset}.pdf")
    maroon = {(0.48, 0.12, 0.17)}
    assert _colours(pdf, "Morgan Avery") == maroon
    assert _colours(pdf, "EXPERIENCE") == maroon
    # The body is ink, not the accent: an accent that reached the bullets would
    # be a tint, not an accent.
    assert _colours(pdf, "Own the ingestion") != maroon


@pytest.mark.parametrize("preset", ["sans", "serif"])
def test_the_presets_are_monochrome_until_asked(
    resume_doc: Document, tmp_path: Path, preset: str
) -> None:
    style = resolve(preset)
    pdf = compile_document(resume_doc, style, output=tmp_path / f"{preset}.pdf")
    assert _colours(pdf, "Morgan Avery") == _colours(pdf, "Own the ingestion")


def test_organisations_are_italic_where_the_role_is_not(
    resume_doc: Document, tmp_path: Path
) -> None:
    """What separates the organisation from the bullet directly beneath it."""
    style = resolve("sans")
    pdf = compile_document(resume_doc, style, output=tmp_path / "sans.pdf")
    line = measure(pdf).find("Northwind Analytics")
    with pdfplumber.open(pdf) as opened:
        faces = {
            c["fontname"].rpartition("+")[2]
            for c in opened.pages[0].chars
            if c["text"].strip() and abs((792 - c["matrix"][5]) - line.baseline) < 1
        }
    assert any(f.endswith("Italic") for f in faces)
    assert any(f.endswith("SemiBold") for f in faces)
