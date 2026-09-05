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


def test_bullet_markers_sit_at_the_configured_indent(geo, standard: Style) -> None:
    marked = [ln for ln in geo.lines if ln.text.startswith(standard.marker_glyph)]
    assert len(marked) > 10
    for line in marked:
        assert line.x0 == pytest.approx(
            standard.margin_x + standard.marker_indent, abs=0.5
        )


def test_bullet_bodies_share_one_hanging_indent(geo, standard: Style) -> None:
    """Wrapped lines must align to the body edge, not the marker edge.

    Asserted by measurement rather than by summing style values: the marker is
    a glyph, and its advance width is not its font size.
    """
    indented = [ln for ln in geo.lines if ln.x0 > standard.margin_x + 10]
    wrapped = [ln for ln in indented if not ln.text.startswith(standard.marker_glyph)]
    assert len(wrapped) > 5
    edges = {round(ln.x0, 1) for ln in wrapped}
    assert len(edges) == 1
    assert edges.pop() > standard.margin_x + standard.marker_indent


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


def test_every_section_opens_at_the_same_distance_from_its_heading(geo) -> None:
    """Whether a section leads with an entry or with bullets is not visible.

    Experience opens with an entry heading and Skills with a bullet list, which
    reach the page by different routes: a heading is boxed, and a list is a
    block with spacing of its own. They land at the same distance because both
    routes end in one paragraph gap, and that is worth holding -- suppressing
    either one is what makes a section look mis-set.
    """
    opens: list[float] = []
    for i, line in enumerate(geo.lines[:-1]):
        if line.text in {"EXPERIENCE", "EDUCATION", "SKILLS"}:
            opens.append(round(line.baseline - geo.lines[i + 1].baseline, 1))
    assert len(opens) == 3
    assert max(opens) - min(opens) < 0.5
