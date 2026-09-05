"""The date gutter, and the bullet balancing that comes with it.

Body text wraps at the same right margin the dates are set against, so without
an inset a bullet's first line runs the full measure and passes under the
column the dates occupy. `date_gutter` holds the body clear of it, measured
from the widest date actually on the page rather than a constant that goes
stale when the fit ladder resizes the dates.

Setting a width on a block is also what balances a wrapped bullet, so the two
features share a mechanism and are tested together.

These assertions read columns rather than rhythm, so they extract words instead
of using `tests.geometry.measure`: that helper merges rows within a point,
which folds an entry's role and its right-aligned date into a single line. That
merge is what makes baseline assertions readable, and it is exactly wrong here
-- a merged header runs from the left margin to the right one and would look
like a body line overhanging the gutter.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber
import pytest

from cvme.models import Document
from cvme.render.engine import compile_document
from cvme.style.schema import Style


def _rows(pdf: Path) -> list[tuple[float, float, str]]:
    """Every visual line as (x0, x1, text), without merging across the page."""
    with pdfplumber.open(pdf) as doc:
        page = doc.pages[0]
        grouped: dict[float, list[dict]] = {}
        for word in page.extract_words(use_text_flow=True):
            grouped.setdefault(round(word["top"], 1), []).append(word)
    return [
        (
            min(w["x0"] for w in ws),
            max(w["x1"] for w in ws),
            " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])),
        )
        for _, ws in sorted(grouped.items())
    ]


#: `Mon YYYY`, the form an entry's right-hand side takes. Matched on text
#: rather than position because the contact line also sits hard against the
#: right margin and is not a date.
_DATE = re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}")


def _date_left(pdf: Path) -> float:
    """The left edge of the leftmost date, which is the gutter's inner wall."""
    dates = [r for r in _rows(pdf) if _DATE.search(r[2])]
    assert dates, "the reference document should carry dates"
    return min(r[0] for r in dates)


def _bullets(pdf: Path) -> list[tuple[float, float, str]]:
    """Rows of bullet text, found by their shared left edge.

    The indent is not `margin_x + marker_indent + body_indent`: the fit ladder
    moves the margins, so the edge is read off the page instead. Bullet text is
    the most common left edge on a resume, which is what makes the mode the
    right way to find it. Bullets are also the only rows guaranteed to be body
    text -- an entry's role and its date can share a `top`, so a header row
    spans both margins without any body text overhanging anything.
    """
    rows = _rows(pdf)
    edges = Counter(round(r[0], 1) for r in rows)
    left = edges.most_common(1)[0][0]
    return [r for r in rows if abs(r[0] - left) < 2.0]


def _render(doc: Document, style: Style, out: Path) -> Path:
    return compile_document(doc, style, output=out)


@pytest.fixture(scope="module")
def gutter(standard: Style) -> Style:
    return standard.model_copy(update={"date_gutter": 12.0})


def test_off_by_default(standard: Style) -> None:
    """An existing document renders exactly as it did before this existed."""
    assert standard.date_gutter < 0
    assert standard.balance_bullets is False


def test_body_stops_clear_of_the_date_column(
    resume_doc: Document, gutter: Style, tmp_path: Path
) -> None:
    pdf = _render(resume_doc, gutter, tmp_path / "gutter.pdf")
    assert max(r[1] for r in _bullets(pdf)) < _date_left(pdf)


def test_the_gutter_is_at_least_as_wide_as_asked(
    resume_doc: Document, gutter: Style, tmp_path: Path
) -> None:
    pdf = _render(resume_doc, gutter, tmp_path / "width.pdf")
    clearance = _date_left(pdf) - max(r[1] for r in _bullets(pdf))
    assert clearance >= gutter.date_gutter - 0.5


def test_without_a_gutter_the_body_keeps_the_whole_measure(
    resume_doc: Document, standard: Style, gutter: Style, tmp_path: Path
) -> None:
    wide = _render(resume_doc, standard, tmp_path / "wide.pdf")
    narrow = _render(resume_doc, gutter, tmp_path / "narrow.pdf")
    assert max(r[1] for r in _bullets(wide)) > max(r[1] for r in _bullets(narrow))


def test_balancing_leaves_no_stub_lines(
    resume_doc: Document, standard: Style, tmp_path: Path
) -> None:
    """A wrapped bullet's shortest line is a fair share of its longest.

    Greedy breaking fills the first line and drops the remainder, which is how
    a two-word line ends up under a full one.
    """
    even = standard.model_copy(update={"balance_bullets": True})
    pdf = _render(resume_doc, even, tmp_path / "balanced.pdf")
    widths = [r[1] - r[0] for r in _bullets(pdf)]
    assert min(widths) > max(widths) * 0.2


def test_balancing_costs_no_height(
    resume_doc: Document, standard: Style, tmp_path: Path
) -> None:
    """Balancing keeps each paragraph's line count, so the page cannot grow.

    This is what makes it safe under the fit ladder: it never spends a line,
    and so never spends type size.
    """
    even = standard.model_copy(update={"balance_bullets": True})
    plain = _render(resume_doc, standard, tmp_path / "plain.pdf")
    balanced = _render(resume_doc, even, tmp_path / "even.pdf")
    assert len(_rows(balanced)) == len(_rows(plain))
