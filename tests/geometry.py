"""Measure a rendered PDF's geometry.

Comparing PDF *geometry* rather than PDF bytes is what makes these assertions
readable when they fail: a broken layout reports "bullets indent to 93.2, not
90.0" instead of a binary diff.

Baselines come from each character's text matrix. Bounding-box tops move with
ascender height, so they shift whenever font weight or size changes and are a
noisy proxy for vertical rhythm; the matrix gives the exact baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber


@dataclass(frozen=True)
class Line:
    baseline: float
    x0: float
    x1: float
    size: float
    text: str


@dataclass(frozen=True)
class Geometry:
    pages: int
    width: float
    height: float
    lines: list[Line]

    def find(self, needle: str) -> Line:
        for line in self.lines:
            if needle in line.text:
                return line
        raise AssertionError(f"no line containing {needle!r}")

    def deltas(self) -> list[float]:
        return [
            round(b.baseline - a.baseline, 2)
            for a, b in zip(self.lines, self.lines[1:], strict=False)
        ]


def measure(path: Path) -> Geometry:
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        rows: dict[float, list[dict]] = {}
        for char in page.chars:
            rows.setdefault(round(page.height - char["matrix"][5], 1), []).append(char)

        lines: list[Line] = []
        for baseline in sorted(rows):
            group = sorted(rows[baseline], key=lambda c: c["x0"])
            # Spaces stay in the text so assertions can match readable strings,
            # but they are excluded from the bounds: a trailing space would
            # otherwise push x1 past the last glyph.
            inked = [c for c in group if c["text"].strip()]
            if not inked:
                continue
            # Merge rows within 1pt: one visual line can carry several
            # baselines when it mixes sizes, as the name/contact line does.
            if lines and baseline - lines[-1].baseline <= 1.0:
                prev = lines[-1]
                lines[-1] = Line(
                    prev.baseline,
                    min(prev.x0, inked[0]["x0"]),
                    max(prev.x1, max(c["x1"] for c in inked)),
                    max(prev.size, max(c["size"] for c in inked)),
                    prev.text + "".join(c["text"] for c in group),
                )
                continue
            lines.append(
                Line(
                    baseline,
                    inked[0]["x0"],
                    max(c["x1"] for c in inked),
                    max(c["size"] for c in inked),
                    "".join(c["text"] for c in group),
                )
            )
        return Geometry(len(pdf.pages), page.width, page.height, lines)
