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


def _rows(pdf: Path) -> list[tuple[float, float, str, float]]:
    """Every visual line as (x0, x1, text, top), without merging across pages."""
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
            top,
        )
        for top, ws in sorted(grouped.items())
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


def _bullets(pdf: Path) -> list[tuple[float, float, str, float]]:
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


def test_without_balancing_the_first_line_fills_the_measure(
    resume_doc: Document, gutter: Style, tmp_path: Path
) -> None:
    """The default is greedy: fill to the gutter, then finish the sentence.

    Balancing evens the lines at the cost of leaving the first one short, which
    is the wrong trade where the measure was cut to stop at something.
    """
    pdf = _render(resume_doc, gutter, tmp_path / "greedy.pdf")
    rows = _bullets(pdf)
    widest = max(r[1] for r in rows)
    wrapped = [r for r in rows if r[1] > widest - 12.0]
    assert len(wrapped) >= 3, "the reference document should wrap several bullets"


def test_bullet_gap_opens_the_list_without_opening_the_lines(
    resume_doc: Document, standard: Style, tmp_path: Path
) -> None:
    """Space lands between items, not between the lines inside one.

    Rendered with the page budget raised so the fit ladder stays out of it: at
    one page the ladder would tighten something else to absorb the gap.

    A tight list spaces items by the same leading it puts between the lines of
    one item, so every gap in the tight render is the same. Adding a bullet gap
    should split them in two: the within-item gap unchanged, and a between-item
    gap that much larger.
    """
    unbudgeted = standard.model_copy(update={"max_pages": 3})
    loose_style = unbudgeted.model_copy(update={"bullet_gap": 3.0})
    tight = _render(resume_doc, unbudgeted, tmp_path / "tight.pdf")
    loose = _render(resume_doc, loose_style, tmp_path / "loose.pdf")

    def common_gaps(pdf: Path) -> list[float]:
        """The gaps a run of bullet lines repeats, commonest first.

        Measured on bullet rows, not every word on the page: an entry heading
        beside its date and a section rule contribute gaps of their own. Taken
        by frequency rather than by range, so no cutoff has to assume the
        answer.
        """
        tops = sorted(r[3] for r in _bullets(pdf))
        seen = Counter(round(b - a, 1) for a, b in zip(tops, tops[1:], strict=False))
        return [gap for gap, _ in seen.most_common(2)]

    within = common_gaps(tight)[0]
    loose_gaps = common_gaps(loose)
    # One gap holds the lines of a bullet together, unchanged.
    assert min(loose_gaps) == pytest.approx(within, abs=0.2)
    # The other separates one bullet from the next, and is wider by the gap.
    assert max(loose_gaps) == pytest.approx(within + 3.0, abs=0.4)
