"""Measure a rendered PDF against the reference and report the deltas.

This is the germ of the golden-file test in docs/implementation-plan.md §9:
comparing PDF *geometry* (positions, sizes, alignment) rather than PDF bytes
gives a diff a human can read.

    uv run --with pdfplumber python compare.py ref.pdf match.pdf
"""

from __future__ import annotations

import collections
import sys

import pdfplumber


def probe(path: str) -> dict[str, object]:
    pdf = pdfplumber.open(path)
    page = pdf.pages[0]
    words = page.extract_words(extra_attrs=["size"], use_text_flow=True)
    tops = sorted({round(w["top"], 1) for w in words})
    deltas = [round(b - a, 1) for a, b in zip(tops, tops[1:]) if 2 < b - a < 18]
    headers = {
        w["text"]: round(w["top"], 1)
        for w in words
        if w["text"].isupper() and len(w["text"]) > 4
    }
    return {
        "pages": len(pdf.pages),
        "headers": headers,
        "line_delta": collections.Counter(deltas).most_common(2),
        "right_edge": round(max(w["x1"] for w in words), 1),
        "last_y": round(max(w["top"] for w in words), 1),
    }


def main() -> None:
    for path in sys.argv[1:] or ["ref.pdf", "match.pdf"]:
        print(path)
        for key, value in probe(path).items():
            print(f"  {key:12} {value}")


if __name__ == "__main__":
    main()
