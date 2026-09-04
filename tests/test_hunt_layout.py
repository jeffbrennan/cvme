"""Where hunts live, how they are numbered, and what moving one does."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cvme.errors import HuntError
from cvme.hunt import layout
from cvme.hunt.layout import Hunt, make_slug, next_round, next_sequence, refile


def test_a_slug_carries_the_sequence_company_role_and_date() -> None:
    slug = make_slug(1, "Northwind Health", "Staff Data Engineer", date(2026, 1, 4))
    assert slug == "01_northwind-health_staff-data-engineer_2026-01-04"


def test_a_long_name_is_cut_at_a_word_boundary() -> None:
    slug = make_slug(
        1, "Probe Health", "Senior Data Engineer, Data Platform", date(2026, 1, 4)
    )
    assert slug == "01_probe-health_senior-data-engineer-data_2026-01-04"


def test_a_single_long_word_is_still_cut() -> None:
    assert layout.slugify("a" * 40) == "a" * 28


def test_a_slug_survives_a_company_with_no_usable_characters() -> None:
    assert make_slug(7, "***", "!!!", date(2026, 1, 4)).startswith("07_unknown_role_")


def test_an_open_hunt_sits_at_the_top_of_its_year(tmp_path: Path) -> None:
    hunt = Hunt(tmp_path, "2026", "01_acme_engineer_2026-01-04")
    assert hunt.path == tmp_path / "2026" / "01_acme_engineer_2026-01-04"
    assert hunt.refiled("applied").path.parent.name == "applied"


def test_numbering_continues_past_filed_hunts(tmp_path: Path) -> None:
    (tmp_path / "2026" / "01_acme_engineer_2026-01-01").mkdir(parents=True)
    (tmp_path / "2026" / "applied" / "02_beta_engineer_2026-01-02").mkdir(parents=True)
    assert next_sequence(tmp_path, "2026") == 3
    assert next_sequence(tmp_path, "2025") == 1


def test_the_round_number_is_shared_across_documents(tmp_path: Path) -> None:
    """A resume and the letter that went with it are one attempt."""
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "cv1.md").write_text("")
    (apps / "cover_letter1.md").write_text("")
    (apps / "cv2.md").write_text("")
    assert next_round(apps, ["cv", "cover_letter"]) == 3


def test_the_first_round_is_one(tmp_path: Path) -> None:
    assert next_round(tmp_path / "apps", ["cv"]) == 1


def test_refiling_moves_the_directory_and_finds_it_again(tmp_path: Path) -> None:
    hunt = Hunt(tmp_path, "2026", "01_acme_engineer_2026-01-04")
    hunt.apps.mkdir(parents=True)
    hunt.posting.write_text("posting")

    moved = refile(hunt, "applied")
    assert not hunt.path.exists()
    assert moved.posting.read_text() == "posting"
    assert layout.find(tmp_path, hunt.slug) == moved


def test_refiling_to_the_same_status_does_nothing(tmp_path: Path) -> None:
    hunt = Hunt(tmp_path, "2026", "01_acme_engineer_2026-01-04")
    hunt.path.mkdir(parents=True)
    assert refile(hunt, "prepared").path == hunt.path


def test_an_unknown_status_lists_the_known_ones() -> None:
    with pytest.raises(HuntError, match="interviewing"):
        layout.check_status("ghosted")


def test_refiling_onto_an_existing_directory_refuses(tmp_path: Path) -> None:
    hunt = Hunt(tmp_path, "2026", "01_acme_engineer_2026-01-04")
    hunt.path.mkdir(parents=True)
    hunt.refiled("applied").path.mkdir(parents=True)
    with pytest.raises(HuntError, match="already exists"):
        refile(hunt, "applied")
