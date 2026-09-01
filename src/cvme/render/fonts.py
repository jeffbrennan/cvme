"""Font resolution.

cvme renders with system fonts disabled, so the only faces available are the
ones vendored in ``render/fonts``. That makes output reproducible: the same
source produces the same PDF regardless of what the machine has installed.
"""

from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).parent / "fonts"

#: Files that must be present for the bundled presets to render as designed.
REQUIRED: dict[str, str] = {
    "Carlito": "Carlito-Regular.ttf",
    "Carlito Bold": "Carlito-Bold.ttf",
    "Carlito Italic": "Carlito-Italic.ttf",
    "Fira Code": "FiraCode-SemiBold.ttf",
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
