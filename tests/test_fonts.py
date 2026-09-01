from __future__ import annotations

from cvme.render.fonts import REQUIRED, font_paths, font_report


def test_every_required_face_is_vendored() -> None:
    missing = [name for name, found, _ in font_report() if not found]
    assert missing == []


def test_report_covers_all_required_faces() -> None:
    assert {name for name, _, _ in font_report()} == set(REQUIRED)


def test_font_paths_point_at_an_existing_directory() -> None:
    from pathlib import Path

    assert [p for p in font_paths() if Path(p).is_dir()] == font_paths()
