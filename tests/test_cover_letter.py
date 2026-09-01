"""The second document type.

A cover letter shares the IR, the parser and the letterhead with a resume, and
differs only in its template. These tests are as much about that seam holding
as about the letter itself.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest

from cvme.errors import FitError
from cvme.md.parse import parse, parse_file
from cvme.models import Document
from cvme.render.fit import fit
from cvme.style.schema import resolve
from tests.conftest import FIXTURES
from tests.geometry import measure


@pytest.fixture(scope="session")
def letter_doc() -> Document:
    return parse_file(FIXTURES / "cover_letter.md")


@pytest.fixture(scope="session")
def letter_pdf(letter_doc: Document, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("letter") / "cover_letter.pdf"
    fit(letter_doc, resolve("letter"), output=out, template="cover_letter")
    return out


def test_body_parses_as_one_untitled_section(letter_doc: Document) -> None:
    assert [s.title for s in letter_doc.sections] == [""]
    assert len(letter_doc.sections[0].blocks) == 4


def test_frontmatter_reaches_meta(letter_doc: Document) -> None:
    assert letter_doc.meta["date"] == "12 March 2026"
    assert letter_doc.meta["salutation"] == "Dear Hiring Team,"
    assert letter_doc.meta["recipient"].splitlines() == [
        "Hiring Team",
        "Northwind Analytics",
        "Boston, MA",
    ]


def test_letter_fits_one_page(letter_pdf: Path) -> None:
    assert measure(letter_pdf).pages == 1


def test_letter_reads_in_order(letter_pdf: Path) -> None:
    with pdfplumber.open(letter_pdf) as pdf:
        text = pdf.pages[0].extract_text()
    order = [
        text.index(s)
        for s in ("Morgan Avery", "12 March 2026", "Dear Hiring Team,", "Sincerely,")
    ]
    assert order == sorted(order)


def test_letterhead_matches_the_resume(letter_pdf: Path, resume_pdf: Path) -> None:
    """Both documents must present the same letterhead, or they read as two
    applications rather than one."""
    letter, resume = measure(letter_pdf).lines[0], measure(resume_pdf).lines[0]
    assert letter.text == resume.text


def test_a_multiline_recipient_stays_on_separate_lines(letter_pdf: Path) -> None:
    geo = measure(letter_pdf)
    for part in ("Hiring Team", "Northwind Analytics", "Boston, MA"):
        assert geo.find(part).text.strip() == part


def test_an_overlong_letter_refuses_rather_than_shrinking(
    letter_doc: Document, tmp_path: Path
) -> None:
    """Prose cannot tighten invisibly; only the author can choose what goes."""
    body = (FIXTURES / "cover_letter.md").read_text()
    head, _, prose = body.partition("---\n\nI am applying")
    long_letter = parse(head + "---\n\nI am applying" + prose * 4)

    with pytest.raises(FitError) as excinfo:
        fit(
            long_letter,
            resolve("letter"),
            output=tmp_path / "o.pdf",
            template="cover_letter",
        )

    message = str(excinfo.value)
    assert "does not tighten to fit" in message
    assert "words" in message


def test_unknown_template_names_the_available_ones() -> None:
    from cvme.render.engine import build_sources

    with pytest.raises(Exception, match="cover_letter"):
        build_sources(Document(), resolve("standard"), "nope")
