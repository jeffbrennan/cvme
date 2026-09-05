"""What the style knobs actually change on the page.

The geometry tests hold the standard preset's rhythm. These hold the knobs a
preset needs to look like a decision rather than a default: the separator
rules, the colours, and the weights a resume otherwise spends all at once.
Each asserts against the rendered PDF, because a style value the template
never reads is indistinguishable from one it ignores.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest

from cvme.models import Document
from cvme.render.engine import compile_document
from cvme.style.schema import Style, load_preset, resolve
from tests.geometry import measure

#: Every preset a resume renders with. `letter` is a cover-letter style and
#: refuses to autofit, so it is not one of them.
RESUME_PRESETS = ("standard", "compact", "airy", "sans", "serif")

#: A drawn stroke at least this wide spans the text block, which separates a
#: rule from a link underline without depending on either one's exact length.
RULE_WIDTH = 400.0


def render(doc: Document, tmp_path: Path, **overrides) -> Path:
    style = resolve("standard", overrides)
    return compile_document(doc, style, output=tmp_path / "out.pdf")


def strokes(pdf: Path) -> list[dict]:
    """Every drawn stroke on page one. Typst draws a thin line as a rectangle."""
    with pdfplumber.open(pdf) as opened:
        page = opened.pages[0]
        return [*page.rects, *page.lines]


def rules(pdf: Path) -> list[dict]:
    return [s for s in strokes(pdf) if s["x1"] - s["x0"] >= RULE_WIDTH]


def chars_on(pdf: Path, needle: str, *, min_x: float = 0.0) -> list[dict]:
    """Every inked character on the line containing ``needle``."""
    line = measure(pdf).find(needle)
    with pdfplumber.open(pdf) as opened:
        return [
            c
            for c in opened.pages[0].chars
            if c["text"].strip()
            and c["x0"] >= min_x
            and abs((792 - c["matrix"][5]) - line.baseline) < 1
        ]


@pytest.mark.parametrize("preset", RESUME_PRESETS)
def test_every_preset_resolves(preset: str) -> None:
    assert load_preset(preset).max_pages >= 1


@pytest.mark.parametrize("preset", RESUME_PRESETS)
def test_every_preset_names_a_vendored_family(preset: str) -> None:
    """A preset naming a face that is not bundled renders in a silent fallback."""
    from cvme.render.fonts import BODY_FAMILIES, DISPLAY

    style = load_preset(preset)
    assert style.body_font.replace(" ", "") in {
        f.replace(" ", "") for f in BODY_FAMILIES
    }
    assert style.name_font in DISPLAY
    assert style.section_font == "" or style.section_font in DISPLAY


def test_no_rules_are_drawn_by_default(resume_doc: Document, tmp_path: Path) -> None:
    assert rules(render(resume_doc, tmp_path)) == []


def test_a_section_rule_is_drawn_once_per_titled_section(
    resume_doc: Document, tmp_path: Path
) -> None:
    drawn = rules(render(resume_doc, tmp_path, section_rule=0.6))
    assert len(drawn) == len([s for s in resume_doc.sendable().sections if s.title])


def test_a_header_rule_is_drawn_below_the_name(
    resume_doc: Document, tmp_path: Path
) -> None:
    pdf = render(resume_doc, tmp_path, header_rule=1.0)
    drawn = rules(pdf)
    assert len(drawn) == 1
    # pdfplumber measures `top` down from the page edge, as baselines are here.
    assert drawn[0]["top"] > measure(pdf).lines[0].baseline


def test_rules_span_the_text_block(resume_doc: Document, tmp_path: Path) -> None:
    style = Style()
    for rule in rules(render(resume_doc, tmp_path, section_rule=0.6)):
        assert rule["x0"] == pytest.approx(style.margin_x, abs=0.5)
        assert rule["x1"] == pytest.approx(612 - style.margin_x, abs=0.5)


def test_link_underlines_can_be_turned_off(
    resume_doc: Document, tmp_path: Path
) -> None:
    """The letterhead's contacts are links, and an underline is a drawn stroke."""
    assert strokes(render(resume_doc, tmp_path, link_underline=True))
    assert strokes(render(resume_doc, tmp_path, link_underline=False)) == []


def test_ink_is_the_only_colour_by_default(
    resume_doc: Document, tmp_path: Path
) -> None:
    pdf = render(resume_doc, tmp_path)
    with pdfplumber.open(pdf) as opened:
        used = {tuple(c["non_stroking_color"] or ()) for c in opened.pages[0].chars}
    assert len(used) == 1


def test_accent_colours_the_section_headings_and_not_the_body(
    resume_doc: Document, tmp_path: Path
) -> None:
    pdf = render(resume_doc, tmp_path, accent="#1d3f6e")
    navy = (0.114, 0.247, 0.431)

    def colours(needle: str) -> set[tuple[float, ...]]:
        return {
            tuple(round(v, 2) for v in c["non_stroking_color"])
            for c in chars_on(pdf, needle)
        }

    assert colours("EXPERIENCE") == {tuple(round(v, 2) for v in navy)}
    assert colours("Own the ingestion") == {(0.0, 0.0, 0.0)}


def test_dates_step_back_from_bold_on_their_own(
    resume_doc: Document, tmp_path: Path
) -> None:
    """`date_weight` reaches the dates without touching the role beside them."""
    right = 612 - Style().margin_x - 80

    def face(pdf: Path, *, min_x: float) -> set[str]:
        # Subset tags differ between compilations; the family after them does not.
        return {
            c["fontname"].rpartition("+")[2]
            for c in chars_on(pdf, "Present", min_x=min_x)
        }

    bold = render(resume_doc, tmp_path / "bold", date_weight="bold")
    plain = render(resume_doc, tmp_path / "plain", date_weight="regular")
    assert face(bold, min_x=right) != face(plain, min_x=right)
    assert face(bold, min_x=0.0) & face(plain, min_x=0.0)  # the role is unchanged
