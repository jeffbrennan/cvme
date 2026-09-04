"""Read a PDF as styled, positioned lines of text.

Extraction is deliberately low level. A PDF has no words, no lines and no
paragraphs -- only glyphs at coordinates -- so everything above this module
works from geometry, and this module's job is to recover the three facts that
geometry alone cannot express: where a space belongs, which runs are bold or
italic, and which runs carry a link.

Word processors routinely emit no space glyphs at all and position each word
instead, so spaces are reconstructed from the gap between adjacent glyphs
rather than trusted to be present.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from pdfplumber.page import Page

from cvme.errors import ConvertError

#: A gap wider than this fraction of the font size is a space. A space is
#: 0.25-0.33em in the fonts resumes use, and kerning stays under 0.1em, so the
#: two populations separate cleanly either side of it.
SPACE_RATIO = 0.2

#: Baselines within this many points are the same line. Line spacing is over
#: 13pt at resume sizes, and a header pairing a 19.5pt name with 11pt contacts
#: can leave the two a fraction of a point apart.
BASELINE_TOLERANCE = 2.5

_BOLD = re.compile(r"bold|black|heavy|semib", re.I)
_ITALIC = re.compile(r"italic|oblique", re.I)
_SYMBOL = re.compile(r"wingding|webding|dingbat|symbol", re.I)


#: A link annotation: its box in top-down page coordinates, and its target.
type Link = tuple[float, float, float, float, str]


@dataclass(frozen=True)
class Run:
    """A stretch of text sharing one style."""

    text: str
    x0: float
    x1: float
    size: float
    bold: bool = False
    italic: bool = False
    symbol: bool = False
    url: str | None = None


@dataclass(frozen=True)
class Line:
    """One visual line: its runs, ordered left to right."""

    page: int
    baseline: float
    runs: tuple[Run, ...]

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)

    @property
    def x0(self) -> float:
        return self.runs[0].x0

    @property
    def x1(self) -> float:
        return self.runs[-1].x1

    @property
    def size(self) -> float:
        """The size of the longest run, which is the line's body size."""
        return max(self.runs, key=lambda r: len(r.text)).size

    def gap_before(self, index: int) -> float:
        """Horizontal gap between run ``index`` and the run before it."""
        return self.runs[index].x0 - self.runs[index - 1].x1


@dataclass(frozen=True)
class Layout:
    """Lines of a document, with the page measurements they are read against."""

    lines: tuple[Line, ...]
    body_size: float
    left: float
    right: float
    line_height: float


def read(path: Path) -> Layout:
    """Extract every line of a PDF, in reading order."""
    if not path.is_file():
        raise ConvertError(f"no such file: {path}")
    try:
        with pdfplumber.open(path) as pdf:
            lines = [
                line
                for number, page in enumerate(pdf.pages, start=1)
                for line in _page_lines(page, number)
            ]
    except ConvertError:
        raise
    except Exception as exc:  # pdfminer raises a wide variety of its own
        raise ConvertError(f"could not read {path}: {exc}") from exc
    if not lines:
        raise ConvertError(
            f"{path} has no extractable text; it is likely a scan, which needs OCR"
        )
    return Layout(
        lines=tuple(lines),
        body_size=_body_size(lines),
        left=min(line.x0 for line in lines),
        right=max(line.x1 for line in lines),
        line_height=_line_height(lines),
    )


def _page_lines(page: Page, number: int) -> list[Line]:
    links: list[Link] = [
        (
            link["x0"],
            link["x1"],
            float(page.height) - link["y1"],
            float(page.height) - link["y0"],
            uri,
        )
        for link in page.hyperlinks
        if (uri := link.get("uri"))
    ]
    rows: list[list[dict]] = []
    for char in sorted(page.chars, key=lambda c: (-_baseline(c, page), c["x0"])):
        baseline = _baseline(char, page)
        if rows and abs(_baseline(rows[-1][0], page) - baseline) <= BASELINE_TOLERANCE:
            rows[-1].append(char)
        else:
            rows.append([char])
    return [
        Line(page=number, baseline=_baseline(row[0], page), runs=runs)
        for row in rows
        if (runs := _runs(sorted(row, key=lambda c: c["x0"]), links))
    ]


def _baseline(char: dict, page: Page) -> float:
    """Baseline measured from the page bottom.

    From the text matrix rather than the bounding box: box tops move with
    ascender height, so a bold or larger run on the same line reads as a
    different line.
    """
    matrix = char.get("matrix")
    return matrix[5] if matrix else page.height - char["bottom"]


@dataclass
class _Group:
    """Characters accumulating into one styled run."""

    style: tuple
    chars: list[str]
    x0: float
    x1: float


def _runs(chars: list[dict], links: list[Link]) -> tuple[Run, ...]:
    """Group a line's characters into styled runs, restoring spaces."""
    groups: list[_Group] = []
    previous: dict | None = None
    for char in chars:
        style = _style(char, links)
        # Measured before the style comparison, so a space falling exactly on
        # a style boundary -- between a bold role and its regular organisation,
        # say -- survives as the leading space of the next run.
        spaced = (
            previous is not None
            and char["x0"] - previous["x1"] > SPACE_RATIO * char["size"]
            and not char["text"].isspace()
        )
        if not groups or groups[-1].style != style:
            groups.append(_Group(style, [], char["x0"], char["x1"]))
        group = groups[-1]
        if spaced and not (group.chars and group.chars[-1].isspace()):
            group.chars.append(" ")
        group.chars.append(char["text"])
        group.x1 = char["x1"]
        previous = char

    return tuple(
        Run(
            text="".join(group.chars),
            x0=group.x0,
            x1=group.x1,
            bold=group.style[0],
            italic=group.style[1],
            symbol=group.style[2],
            size=group.style[3],
            url=group.style[4],
        )
        for group in groups
        if "".join(group.chars).strip()
    )


def _style(char: dict, links: list[Link]) -> tuple:
    font = char.get("fontname") or ""
    x = (char["x0"] + char["x1"]) / 2
    y = (char["top"] + char["bottom"]) / 2
    url = next(
        (
            uri
            for x0, x1, top, bottom, uri in links
            if x0 <= x <= x1 and top <= y <= bottom
        ),
        None,
    )
    return (
        bool(_BOLD.search(font)),
        bool(_ITALIC.search(font)),
        bool(_SYMBOL.search(font)),
        round(char["size"], 1),
        url,
    )


def _body_size(lines: list[Line]) -> float:
    """The size that carries the most text, which is the body size."""
    weight: dict[float, int] = {}
    for line in lines:
        for run in line.runs:
            weight[run.size] = weight.get(run.size, 0) + len(run.text.strip())
    return max(weight, key=lambda size: weight[size])


def _line_height(lines: list[Line]) -> float:
    """The median baseline-to-baseline distance, which is single spacing."""
    deltas = sorted(
        a.baseline - b.baseline
        for a, b in itertools.pairwise(lines)
        if a.page == b.page and 0 < a.baseline - b.baseline < 60
    )
    return deltas[len(deltas) // 2] if deltas else 0.0
