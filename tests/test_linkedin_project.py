"""Projecting a document onto the LinkedIn profile model."""

from __future__ import annotations

import pytest

from cvme.linkedin.dates import is_open_ended, parse_range
from cvme.linkedin.model import MAX_SKILLS, MonthYear, Profile, Skill, flatten
from cvme.linkedin.project import to_profile
from cvme.md.parse import parse
from cvme.models import Document

SOURCE = """\
---
name: Morgan Avery
headline: Staff Data Engineer | Streaming platforms
---

## Summary

Six years across the data lifecycle.

## Experience

### Staff Data Engineer @ Northwind Analytics | Jul 2023 – Present

- Own ingestion for several hundred tenants
- Built a **CLI** that generates workflows

### Data Engineer @ GreyHarbor Health | Dec 2020 – Jul 2023

- Managed quality measures across 14 facilities

## Education

### Ridgeway University
#### Master of Science - Major in Epidemiology, Minor in Biostatistics | May 2020

Certificate: Data Science

## Skills

- **Languages**: Python (advanced), SQL (advanced), Go (learning)
- **Data Stack**: Transformation (spark, dbt); Validation (pytest, pydantic)
"""


@pytest.fixture
def profile() -> Profile:
    return to_profile(parse(SOURCE))[0]


def test_headline_comes_from_frontmatter(profile: Profile) -> None:
    assert profile.headline == "Staff Data Engineer | Streaming platforms"


def test_headline_falls_back_to_the_current_role() -> None:
    without = SOURCE.replace(
        "headline: Staff Data Engineer | Streaming platforms\n", ""
    )
    assert to_profile(parse(without))[0].headline == (
        "Staff Data Engineer at Northwind Analytics"
    )


def test_summary_is_the_about_text(profile: Profile) -> None:
    assert profile.summary == "Six years across the data lifecycle."


def test_untitled_lead_section_is_the_summary() -> None:
    lead = "---\nname: A\n---\n\nProse before any heading.\n\n## Skills\n\n- Python\n"
    assert to_profile(parse(lead))[0].summary == "Prose before any heading."


def test_positions_carry_dates_and_bulleted_descriptions(profile: Profile) -> None:
    current = profile.positions[0]
    assert (current.title, current.company) == (
        "Staff Data Engineer",
        "Northwind Analytics",
    )
    assert current.start == MonthYear(year=2023, month=7)
    assert current.end is None, "an open-ended role has no end date"
    assert current.description.splitlines() == [
        "• Own ingestion for several hundred tenants",
        "• Built a CLI that generates workflows",
    ]


def test_markup_does_not_survive_into_a_profile_field(profile: Profile) -> None:
    """LinkedIn renders no markup, so asterisks would be shown literally."""
    assert "**" not in profile.positions[0].description
    assert "#strong" not in profile.positions[0].description


def test_education_splits_the_degree_from_the_field(profile: Profile) -> None:
    education = profile.educations[0]
    assert education.school == "Ridgeway University"
    assert education.degree == "Master of Science"
    assert education.field_of_study == "Epidemiology", "the minor is a second clause"
    assert education.description == "Certificate: Data Science"


def test_skills_are_flattened_and_qualifiers_dropped(profile: Profile) -> None:
    names = [skill.name for skill in profile.skills]
    assert names[:3] == ["Python", "SQL", "Go"], "'(advanced)' is not part of a skill"
    assert "spark" in names and "pydantic" in names
    assert "Transformation" not in names, "a category that lists skills is not one"
    assert "Languages" not in names, "the group label is not a skill"


def test_skills_are_deduplicated_across_groups() -> None:
    source = "## Skills\n\n- **A**: Python, spark\n- **B**: Spark, dbt\n"
    names = [skill.name for skill in to_profile(parse(source))[0].skills]
    assert names == ["Python", "spark", "dbt"], "first spelling wins"


def test_unrecognised_sections_are_reported_not_dropped() -> None:
    source = SOURCE + "\n## Projects\n\n- cvme\n"
    profile, unmapped = to_profile(parse(source))
    assert unmapped == ["Projects"]
    assert not any("cvme" in p.description for p in profile.positions)


def test_a_gaps_section_never_reaches_the_profile() -> None:
    """`## Gaps` is addressed to the author. A public profile is the worst place."""
    source = SOURCE + "\n## Gaps\n\n- No Kubernetes in production\n"
    profile, unmapped = to_profile(parse(source))
    assert "Kubernetes" not in profile.model_dump_json()
    assert unmapped == [], "a drafting section is dropped, not reported as unmapped"


class TestLimits:
    def test_a_long_field_is_reported_rather_than_truncated(self) -> None:
        profile = Profile(headline="x" * 300)
        (violation,) = profile.violations()
        assert violation.actual == 300
        assert violation.limit == 220
        assert "80 over" in str(violation)

    def test_a_field_at_the_limit_passes(self) -> None:
        assert Profile(headline="x" * 220).violations() == []

    def test_too_many_skills_is_a_violation(self) -> None:
        profile = Profile(skills=[Skill(name=f"s{i}") for i in range(MAX_SKILLS + 1)])
        assert [v.unit for v in profile.violations()] == ["skills"]


class TestFlatten:
    def test_a_link_keeps_its_target(self) -> None:
        assert flatten(_markup("see [the docs](https://x.test/d)")) == (
            "see the docs (https://x.test/d)"
        )

    def test_a_link_whose_text_is_its_url_is_not_doubled(self) -> None:
        assert (
            flatten(_markup("[site.example](https://site.example)")) == "site.example"
        )

    def test_a_bolded_link_body_does_not_confuse_the_scan(self) -> None:
        assert flatten(_markup("[**bold**](https://a.test)")) == "bold (https://a.test)"


class TestDates:
    @pytest.mark.parametrize(
        ("text", "start", "end"),
        [
            ("Jul 2023 – Present", MonthYear(year=2023, month=7), None),
            ("Jul 2023 - Present", MonthYear(year=2023, month=7), None),
            (
                "September 2018 to May 2020",
                MonthYear(year=2018, month=9),
                MonthYear(year=2020, month=5),
            ),
            ("2019 – 2021", MonthYear(year=2019), MonthYear(year=2021)),
            ("2019-2021", MonthYear(year=2019), MonthYear(year=2021)),
            (
                "Sept. 2018 – Dec. 2019",
                MonthYear(year=2018, month=9),
                MonthYear(year=2019, month=12),
            ),
            ("May 2020", MonthYear(year=2020, month=5), None),
        ],
    )
    def test_ranges_people_actually_write(
        self, text: str, start: MonthYear | None, end: MonthYear | None
    ) -> None:
        assert parse_range(text) == (start, end)

    def test_a_hyphen_inside_a_date_is_not_a_range_separator(self) -> None:
        assert parse_range("2023-07 – 2024-01") == (
            MonthYear(year=2023, month=7),
            MonthYear(year=2024, month=1),
        )

    def test_an_unreadable_date_is_left_unset_rather_than_guessed(self) -> None:
        assert parse_range("sometime last spring") == (None, None)

    def test_present_is_distinguished_from_an_unparseable_end(self) -> None:
        assert is_open_ended("Jul 2023 – Present")
        assert not is_open_ended("Jul 2023 – whenever")


def _markup(source: str) -> str:
    """The document IR's form of one line of markdown."""
    document: Document = parse(f"---\nname: X\n---\n\n{source}\n")
    block = document.sections[0].blocks[0]
    return getattr(block, "text", "")
