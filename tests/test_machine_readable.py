"""What an automated reader sees.

Resumes are parsed by software before a person reads them, so the extracted
text and the PDF's tag tree are part of the output, not a side effect of it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pdfplumber
import pytest
from pypdf import PdfReader

from cvme.models import Document
from cvme.render.engine import compile_document
from cvme.style.schema import Style, resolve


def catalog(path: Path) -> dict[str, Any]:
    """The PDF's document catalog as a plain mapping.

    pypdf types trailer entries as the loose ``PdfObject``, so narrowing once
    here keeps the assertions below readable.
    """
    return cast(dict[str, Any], PdfReader(path).trailer["/Root"])


@pytest.fixture(scope="session")
def text(resume_pdf: Path) -> str:
    with pdfplumber.open(resume_pdf) as pdf:
        return pdf.pages[0].extract_text()


def test_bullets_survive_text_extraction(text: str, standard: Style) -> None:
    """A drawn marker leaves no character, so bullets become unsplittable prose."""
    assert text.count(standard.marker_glyph) >= 10


def test_reading_order_follows_the_document(text: str) -> None:
    order = [text.index(s) for s in ("SUMMARY", "EXPERIENCE", "EDUCATION", "SKILLS")]
    assert order == sorted(order)


def test_right_aligned_dates_stay_on_their_entry_line(text: str) -> None:
    line = next(ln for ln in text.splitlines() if "Northwind Analytics" in ln)
    assert "Jul 2023" in line


def test_no_stray_marker_characters(text: str) -> None:
    """The reference used a Wingdings glyph, which extracts as a literal '§'."""
    assert "§" not in text


def test_pdf_is_tagged(resume_pdf: Path) -> None:
    root = catalog(resume_pdf)
    # pypdf yields a BooleanObject, not the True singleton.
    assert bool(root["/MarkInfo"]["/Marked"])
    assert "/StructTreeRoot" in root


def test_language_is_declared(resume_pdf: Path, standard: Style) -> None:
    assert catalog(resume_pdf)["/Lang"] == standard.lang


def test_sections_are_real_headings_not_bold_text(resume_pdf: Path) -> None:
    """H2 tags give an outline; bold Divs give a parser nothing to work with."""
    seen: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        items = node if isinstance(node, list) else [node]
        for item in items:
            try:
                obj = item.get_object()
            except AttributeError:
                continue
            if isinstance(obj, dict):
                if "/S" in obj:
                    seen.append(str(obj["/S"]))
                if "/K" in obj:
                    walk(obj["/K"], depth + 1)

    walk(catalog(resume_pdf)["/StructTreeRoot"].get("/K"))
    assert "/H1" in seen, "the name should be the document's one H1"
    assert "/H2" in seen
    assert "/L" in seen, "bullet lists should carry a List tag"


def test_pdf_ua_1_accepts_the_document(resume_doc: Document, tmp_path: Path) -> None:
    """PDF/UA-1 refuses a document whose first heading is deeper than level 1."""
    style = resolve("standard", {"pdf_standard": "ua-1"})
    out = compile_document(resume_doc, style, output=tmp_path / "ua.pdf")
    assert out.exists()


def test_metadata_carries_title_and_author(resume_pdf: Path) -> None:
    meta = PdfReader(resume_pdf).metadata
    assert meta is not None
    assert meta.get("/Title") == "Morgan Avery"
    assert meta.get("/Author") == "Morgan Avery"
