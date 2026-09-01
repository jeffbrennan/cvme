"""Render the reference-matching resume template.

Reproduces the layout of the existing Word-produced resume from a structured
data file, to validate that the Typst template in docs/implementation-plan.md
§12 can hit the target spec. Verified to land within ~1pt of the original on
every section header, right-aligned date, and line-spacing measurement.

    ./fetch_fonts.sh                    # one-time, populates fonts/
    uv run --with typst python render.py
"""

from __future__ import annotations

import json
import pathlib

import typst

HERE = pathlib.Path(__file__).parent

FILES: dict[str, bytes] = {
    "main.typ": (HERE / "resume.typ").read_bytes(),
    "data.json": (HERE / "resume_data.json").read_bytes(),
}
COMMON = dict(root=str(HERE), font_paths=[str(HERE / "fonts")], ignore_system_fonts=True)


def main() -> None:
    typst.compile(FILES, output=str(HERE / "match.pdf"), **COMMON)
    typst.compile(FILES, output=str(HERE / "match_{n}.png"), format="png", ppi=110, **COMMON)
    print("wrote match.pdf and match_1.png")


if __name__ == "__main__":
    main()
