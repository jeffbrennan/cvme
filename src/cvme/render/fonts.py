"""Font resolution.

cvme renders with system fonts disabled, so the only faces available are the
ones vendored in ``render/fonts``. That makes output reproducible: the same
source produces the same PDF regardless of what the machine has installed.
"""

from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).parent / "fonts"

#: Body families, each vendored in the three faces a document needs. The name
#: tables are rewritten at fetch time so that one family holds all three, which
#: is what lets ``body_font`` name a family and nothing else.
BODY_FAMILIES: tuple[str, ...] = (
    "Carlito",
    "IBMPlexSans",
    "SourceSans3",
    "SourceSerif4",
    "EBGaramond",
    "Inter",
)
FACES: tuple[str, ...] = ("Regular", "SemiBold", "Italic")

#: Display faces for the letterhead. One weight each.
DISPLAY: dict[str, str] = {
    "Fira Code": "FiraCode-SemiBold.ttf",
    "IBM Plex Mono": "IBMPlexMono-SemiBold.ttf",
    "JetBrains Mono": "JetBrainsMono-SemiBold.ttf",
}

#: Files that must be present for the bundled presets to render as designed.
REQUIRED: dict[str, str] = {
    **{
        f"{family} {face}": f"{family}-{face}.ttf"
        for family in BODY_FAMILIES
        for face in FACES
    },
    **DISPLAY,
}


def font_paths() -> list[str]:
    """Directories to hand to the Typst compiler."""
    return [str(FONT_DIR)]


def font_report() -> list[tuple[str, bool, str]]:
    """Report presence of each vendored face, for ``cvme doctor``."""
    report: list[tuple[str, bool, str]] = []
    for name, filename in REQUIRED.items():
        path = FONT_DIR / filename
        if path.exists():
            report.append((name, True, f"{filename} ({path.stat().st_size // 1024}kB)"))
        else:
            report.append((name, False, f"{filename} not found in {FONT_DIR}"))
    return report
