"""Geometry regressions for the standard preset.

These are the tests that hold the layout: every constant asserted here was
derived by measuring the reference document, so a change in vertical rhythm or
alignment fails loudly rather than drifting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cvme.style.schema import Style
from tests.geometry import measure


@pytest.fixture(scope="session")
def geo(resume_pdf: Path):
    return measure(resume_pdf)


def test_fits_the_page_budget(geo, standard: Style) -> None:
    assert geo.pages == standard.max_pages


def test_page_is_us_letter(geo) -> None:
    assert (round(geo.width), round(geo.height)) == (612, 792)


def test_section_headers_sit_at_the_left_margin(geo, standard: Style) -> None:
    headers = [ln for ln in geo.lines if ln.text.isupper() and len(ln.text) > 4]
    assert {ln.text for ln in headers} == {
        "SUMMARY",
        "EXPERIENCE",
        "EDUCATION",
        "SKILLS",
    }
    for line in headers:
        assert line.x0 == pytest.approx(standard.margin_x, abs=0.5)


def test_dates_are_flush_to_the_right_margin(geo, standard: Style) -> None:
    right_edge = geo.width - standard.margin_x
    dated = [ln for ln in geo.lines if "Present" in ln.text or "May 2020" in ln.text]
    assert dated, "expected at least one dated entry line"
    for line in dated:
        assert line.x1 == pytest.approx(right_edge, abs=1.0)


def test_bullets_hang_at_the_configured_indent(geo, standard: Style) -> None:
    expected = (
        standard.margin_x
        + standard.marker_indent
        + standard.marker_size
        + standard.body_indent
    )
    bullets = [ln for ln in geo.lines if ln.x0 > standard.margin_x + 10]
    assert len(bullets) > 10
    for line in bullets:
        assert line.x0 == pytest.approx(expected, abs=0.5)


def test_body_lines_share_one_rhythm(geo) -> None:
    """The dominant line delta is the body leading, and it does not wander."""
    deltas = [d for d in geo.deltas() if 12.0 < d < 15.0]
    assert len(deltas) > 25
    assert max(deltas) - min(deltas) < 0.5


def test_name_and_contact_share_a_line(geo) -> None:
    header = geo.lines[0]
    assert "Morgan Avery" in header.text
    assert "morgan.avery@example.com" in header.text


def test_output_is_reproducible(resume_doc, standard: Style, tmp_path: Path) -> None:
    from cvme.render.engine import compile_document

    a = compile_document(resume_doc, standard, output=tmp_path / "a.pdf")
    b = compile_document(resume_doc, standard, output=tmp_path / "b.pdf")
    assert a.read_bytes() == b.read_bytes()
