"""Version comparison, and the index that carries it."""

from __future__ import annotations

from pathlib import Path

from cvme.hunt.index import BEGIN, END, summarise, write
from cvme.hunt.store import Round
from tests.conftest import FIXTURES

BASE = (FIXTURES / "resume.md").read_text()


def _round(number: int, changes: str) -> Round:
    return Round(
        slug="01_acme_engineer_2026-01-04",
        number=number,
        created_at="2026-01-04T10:00:00+00:00",
        documents=f"cv{number}",
        pages="cv 1p",
        fit=62,
        changes=changes,
        note="",
    )


def test_the_first_version_says_so(tmp_path: Path) -> None:
    current = tmp_path / "cv1.md"
    current.write_text(BASE)
    assert summarise(None, current) == "first version"


def test_an_identical_rewrite_reports_no_structural_change(tmp_path: Path) -> None:
    one, two = tmp_path / "cv1.md", tmp_path / "cv2.md"
    one.write_text(BASE)
    two.write_text(BASE)
    assert summarise(one, two) == "no structural change"


def test_a_dropped_bullet_is_counted_and_quoted(tmp_path: Path) -> None:
    one, two = tmp_path / "cv1.md", tmp_path / "cv2.md"
    one.write_text(BASE)
    kept = [
        line for line in BASE.splitlines() if "Cut dashboard load times" not in line
    ]
    two.write_text("\n".join(kept))
    summary = summarise(one, two)
    assert "-1 lines" in summary
    assert "Cut dashboard load" in summary


def test_a_dropped_section_is_named(tmp_path: Path) -> None:
    one, two = tmp_path / "cv1.md", tmp_path / "cv2.md"
    one.write_text(BASE)
    two.write_text(BASE.split("## Education")[0])
    assert "dropped section Education" in summarise(one, two)


def test_an_unparsable_version_says_so_rather_than_failing(tmp_path: Path) -> None:
    one, two = tmp_path / "cv1.md", tmp_path / "cv2.md"
    one.write_text(BASE)
    two.write_text("###### not a document\n")
    assert summarise(one, two) == "unparsed; compare by hand"


def test_the_index_regenerates_its_block_and_keeps_your_notes(tmp_path: Path) -> None:
    path = tmp_path / "index.md"
    write(path, "01_acme", "Engineer at Acme", [_round(1, "first version")])
    path.write_text(path.read_text() + "\n## My notes\n\nCalled the recruiter.\n")

    write(path, "01_acme", "Engineer at Acme", [_round(1, "x"), _round(2, "+2 lines")])
    text = path.read_text()
    assert text.count(BEGIN) == 1 and text.count(END) == 1
    assert "Called the recruiter." in text
    assert "+2 lines" in text
    assert "first version" not in text


def test_an_index_with_no_versions_still_renders(tmp_path: Path) -> None:
    path = tmp_path / "index.md"
    write(path, "01_acme", "Engineer at Acme", [])
    assert "_none yet_" in path.read_text()
