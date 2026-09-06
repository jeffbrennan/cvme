"""Extraction, driven through a real browser against sanitised fixtures.

These are the tests that can be honest. cvme cannot reach LinkedIn from CI, so
nothing here proves the selectors match today's markup -- ``SELECTORS`` is a
reconstruction, and `cvme linkedin capture` is how you check it against the
real page. What these do prove is the part that survives a selector rewrite:
that duplicated text is read once, that nested roles are flattened, that a
list still growing is reported as partial rather than complete, and that a
layout cvme does not understand yields "could not check" rather than "your
profile is empty".

Real Playwright, real Chromium, local files. No network.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from cvme.linkedin.capture import Capture
from cvme.linkedin.dom import Reader
from cvme.linkedin.model import MonthYear

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="the browser extra is not installed"
)


def _chromium_path() -> str | None:
    """An explicit binary, when the environment pins one.

    Set ``CVME_CHROMIUM`` where the installed Playwright and the available
    Chromium build do not match versions, which is the normal state of a
    prepared container.
    """
    if pinned := os.environ.get("CVME_CHROMIUM"):
        return pinned
    root = Path("/opt/pw-browsers")
    if not root.is_dir():
        return None
    found = sorted(root.glob("chromium-*/chrome-linux/chrome"))
    return str(found[-1]) if found else None


@pytest.fixture(scope="session")
def browser() -> Iterator[object]:
    """A Chromium, or a skip that says how to get one.

    Skipped rather than failed when no browser is installed: the extra is
    optional, and a contributor who has not run `playwright install` has not
    broken anything.
    """
    with playwright_api.sync_playwright() as driver:
        try:
            launched = driver.chromium.launch(executable_path=_chromium_path())
        except Exception as exc:
            pytest.skip(f"no Chromium available ({exc}); run `playwright install`")
        yield launched
        launched.close()


@pytest.fixture
def page(browser) -> Iterator[object]:
    opened = browser.new_page()
    yield opened
    opened.close()


def read(page, name: str, **kwargs) -> Capture:
    page.goto((FIXTURES / name).as_uri())
    return Reader(page, settle_ms=1000, **kwargs).capture(profile_url="https://x/in/me")


class TestWholeProfile:
    @pytest.fixture
    def captured(self, page) -> Capture:
        return read(page, "profile.html")

    def test_every_section_reads_as_complete(self, captured: Capture) -> None:
        assert {n: s.status for n, s in captured.sections.items()} == {
            "headline": "complete",
            "about": "complete",
            "experience": "complete",
            "education": "complete",
            "skills": "complete",
        }
        assert captured.complete

    def test_a_complete_capture_vouches_for_the_whole_profile(
        self, captured: Capture
    ) -> None:
        assert captured.as_source().unchecked == []

    def test_the_headline_is_read_from_the_top_card(self, captured: Capture) -> None:
        assert captured.profile.headline == "Staff Data Engineer | Streaming platforms"

    def test_duplicated_text_is_read_once(self, captured: Capture) -> None:
        """Each string is also in a hidden span for screen readers."""
        assert captured.profile.summary == (
            "Six years across the data lifecycle.\n\n"
            "I care about pipelines a team can reason about at 3am."
        )

    def test_roles_nested_under_one_employer_are_flattened(
        self, captured: Capture
    ) -> None:
        """Otherwise one position's description is three other jobs."""
        positions = captured.profile.positions
        assert [(p.title, p.company) for p in positions[:2]] == [
            ("Staff Data Engineer", "Northwind Analytics"),
            ("Senior Data Engineer", "Northwind Analytics"),
        ]
        assert positions[0].start == MonthYear(year=2023, month=7)
        assert positions[0].end is None, "'Present' is an open end"
        assert positions[0].location == "New York, NY"
        assert positions[0].description == "Own ingestion for several hundred tenants"

    def test_the_date_line_is_found_not_counted_to(self, captured: Capture) -> None:
        """The second nested role has no employment type, so its lines shift."""
        senior = captured.profile.positions[1]
        assert senior.start == MonthYear(year=2022, month=1)
        assert senior.end == MonthYear(year=2023, month=7)
        assert senior.location == "New York, NY"
        assert senior.description == "Built the streaming backbone"

    def test_the_computed_duration_is_not_profile_content(
        self, captured: Capture
    ) -> None:
        """ "Jul 2023 - Present · 3 yrs 2 mos" -- LinkedIn computes the tail."""
        assert "yrs" not in captured.profile.model_dump_json()
        assert captured.profile.positions[1].company == "Northwind Analytics"

    def test_the_employment_type_is_not_part_of_the_company_name(
        self, captured: Capture
    ) -> None:
        grey = captured.profile.positions[2]
        assert grey.company == "GreyHarbor Health", (
            "not 'GreyHarbor Health · Full-time'"
        )
        assert grey.location == "Remote"

    def test_a_collapsed_body_is_expanded_before_it_is_read(
        self, captured: Capture
    ) -> None:
        """The 'see more' button hides the description until it is clicked."""
        assert "Managed quality measures" in captured.profile.positions[2].description

    def test_education_splits_the_degree_from_the_field(
        self, captured: Capture
    ) -> None:
        education = captured.profile.educations[0]
        assert education.school == "Ridgeway University"
        assert education.degree == "Master of Science"
        assert education.field_of_study == "Epidemiology"
        assert education.start == MonthYear(year=2018)
        assert education.end == MonthYear(year=2020)
        assert education.description == "Certificate: Data Science"

    def test_skills_are_read_in_order(self, captured: Capture) -> None:
        assert [s.name for s in captured.profile.skills] == [
            "Python",
            "SQL",
            "Apache Spark",
        ]

    def test_the_capture_carries_its_provenance(self, captured: Capture) -> None:
        assert captured.profile_url == "https://x/in/me"
        assert captured.extractor_version >= 1
        assert captured.captured_at is not None


class TestIncompleteReads:
    def test_a_list_that_keeps_growing_is_partial_not_complete(self, page) -> None:
        """The unseen entries are exactly the ones an audit would call missing."""
        captured = read(page, "lazy.html", scroll_rounds=3)
        skills = captured.section("skills")
        assert skills.status == "partial"
        assert skills.found > 1, "it did read some of them"
        assert "skills" not in captured.covers

    def test_a_partial_section_still_reports_what_it_saw(self, page) -> None:
        captured = read(page, "lazy.html", scroll_rounds=3)
        assert captured.profile.skills, "the entries are kept, just not vouched for"

    def test_an_unrecognised_layout_says_so_rather_than_empty(self, page) -> None:
        captured = read(page, "foreign.html")
        assert {s.status for s in captured.sections.values()} == {"unavailable"}
        assert captured.covers == set(), "nothing may be compared against this"

    def test_an_unrecognised_layout_never_reports_drift(self, page) -> None:
        """The corroboration rule, stated as the outcome it exists to prevent."""
        from cvme.linkedin.audit import audit
        from cvme.linkedin.model import Position, Profile, Skill

        wanted = Profile(
            headline="Staff DE",
            positions=[Position(title="A", company="B", start=MonthYear(year=2020))],
            skills=[Skill(name="Python")],
        )
        captured = read(page, "foreign.html")
        assert audit(wanted, captured.as_source()).findings == []

    def test_a_missing_section_on_an_understood_page_is_empty(
        self, page, tmp_path: Path
    ) -> None:
        """A profile with no Education renders no Education section."""
        trimmed = (FIXTURES / "profile.html").read_text(encoding="utf-8")
        start = trimmed.index('<section>\n    <div id="education">')
        end = trimmed.index('<section>\n    <div id="skills">')
        page.goto(_write(tmp_path, trimmed[:start] + trimmed[end:]))
        captured = Reader(page, settle_ms=1000).capture()
        assert captured.section("education").status == "empty"
        assert "educations" in captured.covers, (
            "an established absence is comparable; a failed read is not"
        )


def _write(tmp_path: Path, html: str) -> str:
    target = tmp_path / "page.html"
    target.write_text(html, encoding="utf-8")
    # Fixtures are loaded by URI, so relative assets resolve the same way.
    shutil.copystat(FIXTURES / "profile.html", target)
    return target.as_uri()
