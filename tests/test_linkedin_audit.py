"""Reading a LinkedIn data export, and auditing the profile against it."""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import pytest

from cvme.linkedin import audit as audit_module
from cvme.linkedin import export
from cvme.linkedin.audit import audit, recordable
from cvme.linkedin.live import Source
from cvme.linkedin.model import MonthYear, Position, Profile, Skill
from cvme.linkedin.project import to_profile
from cvme.md.parse import parse

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

### Data Engineer @ GreyHarbor Health | Dec 2020 – Jul 2023

- Managed quality measures across 14 facilities

## Education

### Ridgeway University
#### Master of Science in Epidemiology | May 2020

## Skills

- **Languages**: Python, SQL
"""

PROFILE_ROWS = [
    ["First Name", "Last Name", "Headline", "Summary"],
    [
        "Morgan",
        "Avery",
        "Staff Data Engineer | Streaming platforms",
        "Six years across the data lifecycle.",
    ],
]

POSITION_ROWS = [
    ["Company Name", "Title", "Description", "Location", "Started On", "Finished On"],
    [
        "Northwind Analytics",
        "Staff Data Engineer",
        "• Own ingestion for several hundred tenants",
        "",
        "Jul 2023",
        "",
    ],
    [
        "GreyHarbor Health",
        "Data Engineer",
        "• Managed quality measures across 14 facilities",
        "",
        "Dec 2020",
        "Jul 2023",
    ],
]

EDUCATION_ROWS = [
    ["School Name", "Degree Name", "Field Of Study", "Notes", "Start Date", "End Date"],
    ["Ridgeway University", "Master of Science", "Epidemiology", "", "", "May 2020"],
]

SKILL_ROWS = [["Name"], ["Python"], ["SQL"]]


def write_export(root: Path, **override: list[list[str]]) -> Path:
    """A directory of export CSVs that matches ``SOURCE`` unless overridden."""
    tables = {
        "Profile": PROFILE_ROWS,
        "Positions": POSITION_ROWS,
        "Education": EDUCATION_ROWS,
        "Skills": SKILL_ROWS,
    }
    tables.update(override)
    root.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with (root / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
    return root


def _source(profile: Profile) -> Source:
    """A source that vouches for the whole profile."""
    return Source(profile=profile, covers=set(Profile.PARTS), label="test")


@pytest.fixture
def projected() -> Profile:
    return to_profile(parse(SOURCE))[0]


class TestExport:
    def test_a_directory_of_csvs_reads_as_a_profile(self, tmp_path: Path) -> None:
        live = export.read(write_export(tmp_path / "e")).profile
        assert live.headline == "Staff Data Engineer | Streaming platforms"
        assert [p.company for p in live.positions] == [
            "Northwind Analytics",
            "GreyHarbor Health",
        ]
        assert live.positions[0].start == MonthYear(year=2023, month=7)
        assert live.positions[0].end is None, "a current role has no finish date"
        assert [s.name for s in live.skills] == ["Python", "SQL"]

    def test_a_zip_reads_the_same_as_a_directory(self, tmp_path: Path) -> None:
        source = write_export(tmp_path / "e")
        archive = tmp_path / "Basic_LinkedInDataExport_2026.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for csv_file in source.glob("*.csv"):
                zipped.write(csv_file, csv_file.name)
        assert export.read(archive).profile == export.read(source).profile

    def test_headers_are_matched_by_name_not_position(self, tmp_path: Path) -> None:
        shuffled = [
            ["Finished On", "Title", "Started On", "Company Name", "Description"],
            ["", "Staff Data Engineer", "Jul 2023", "Northwind Analytics", "• x"],
        ]
        live = export.read(write_export(tmp_path / "e", Positions=shuffled)).profile
        assert live.positions[0].title == "Staff Data Engineer"
        assert live.positions[0].start == MonthYear(year=2023, month=7)

    def test_an_alternative_spelling_is_accepted(self, tmp_path: Path) -> None:
        """LinkedIn publishes no schema for the archive and does rename these."""
        renamed = [
            ["Company", "Position", "Description", "Start Date", "End Date"],
            ["Northwind Analytics", "Staff Data Engineer", "• x", "Jul 2023", ""],
        ]
        live = export.read(write_export(tmp_path / "e", Positions=renamed)).profile
        assert live.positions[0].company == "Northwind Analytics"

    def test_an_unreadable_schema_names_the_headers_it_found(
        self, tmp_path: Path
    ) -> None:
        broken = [["Employer", "Role"], ["Northwind", "Staff DE"]]
        with pytest.raises(export.ExportError) as caught:
            export.read(write_export(tmp_path / "e", Positions=broken))
        message = str(caught.value)
        assert "no column for company, title" in message
        assert "Employer, Role" in message, "the real headers, so it is diagnosable"

    def test_a_bom_does_not_swallow_the_first_column(self, tmp_path: Path) -> None:
        root = tmp_path / "e"
        write_export(root)
        (root / "Skills.csv").write_text("﻿Name\nPython\n", encoding="utf-8")
        assert [s.name for s in export.read(root).profile.skills] == ["Python"]

    def test_blank_rows_are_skipped(self, tmp_path: Path) -> None:
        padded = [*SKILL_ROWS, [""], ["Rust"]]
        live = export.read(write_export(tmp_path / "e", Skills=padded)).profile
        assert [s.name for s in live.skills] == ["Python", "SQL", "Rust"]

    def test_a_directory_with_nothing_recognisable_is_an_error(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "Connections.csv").write_text("First Name\nA\n", encoding="utf-8")
        with pytest.raises(export.ExportError, match="no LinkedIn export data"):
            export.read(tmp_path)

    def test_a_missing_path_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(export.ExportError, match="no such file"):
            export.read(tmp_path / "nowhere.zip")

    def test_a_partial_export_reads_what_is_there(self, tmp_path: Path) -> None:
        """Skills alone is a valid download; it should audit skills only."""
        root = tmp_path / "e"
        root.mkdir()
        with (root / "Skills.csv").open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(SKILL_ROWS)
        source = export.read(root)
        assert [s.name for s in source.profile.skills] == ["Python", "SQL"]
        assert source.covers == {"skills"}, (
            "a skills-only download must not make every position look lost"
        )


class TestAudit:
    def test_a_matching_profile_passes(
        self, tmp_path: Path, projected: Profile
    ) -> None:
        result = audit(projected, export.read(write_export(tmp_path / "e")))
        assert result.findings == []
        assert not result.failed(strict=True)
        assert result.summary() == "the profile matches your documents"

    def test_an_out_of_date_field_is_stale(
        self, tmp_path: Path, projected: Profile
    ) -> None:
        behind = [PROFILE_ROWS[0], ["Morgan", "Avery", "Data Engineer", "Six years."]]
        result = audit(
            projected, export.read(write_export(tmp_path / "e", Profile=behind))
        )
        assert {f.severity for f in result.findings} == {"stale"}
        assert result.failed(strict=False)

    def test_an_absent_field_is_missing_rather_than_stale(
        self, tmp_path: Path, projected: Profile
    ) -> None:
        """'Your headline is out of date' reads badly when there is no headline."""
        blank = [PROFILE_ROWS[0], ["Morgan", "Avery", "", ""]]
        result = audit(
            projected, export.read(write_export(tmp_path / "e", Profile=blank))
        )
        assert {f.severity for f in result.findings} == {"missing"}

    def test_a_position_linkedin_lacks_is_missing(
        self, tmp_path: Path, projected: Profile
    ) -> None:
        only_one = POSITION_ROWS[:2]
        result = audit(
            projected, export.read(write_export(tmp_path / "e", Positions=only_one))
        )
        (finding,) = result.of("missing")
        assert finding.change.label == "Data Engineer @ GreyHarbor Health"

    def test_an_entry_only_linkedin_has_is_extra_and_does_not_fail(
        self, tmp_path: Path, projected: Profile
    ) -> None:
        """A resume drops an old job for space; the profile keeping it is fine."""
        with_extra = [
            *POSITION_ROWS,
            ["Harbor Coffee", "Barista", "Pulled shots", "", "Sep 2016", "May 2018"],
        ]
        result = audit(
            projected, export.read(write_export(tmp_path / "e", Positions=with_extra))
        )
        assert [f.severity for f in result.findings] == ["extra"]
        assert not result.failed(strict=False)
        assert result.failed(strict=True), "--strict is for an exact profile"

    def test_cosmetic_whitespace_is_not_drift(
        self, tmp_path: Path, projected: Profile
    ) -> None:
        """The text has been through someone else's storage on the way back."""
        respaced = [
            POSITION_ROWS[0],
            [
                "Northwind Analytics",
                "Staff  Data Engineer ",
                "• Own ingestion for several hundred tenants   \n\n\n",
                "",
                "Jul 2023",
                "",
            ],
            POSITION_ROWS[2],
        ]
        result = audit(
            projected, export.read(write_export(tmp_path / "e", Positions=respaced))
        )
        assert result.findings == []

    def test_skills_are_rolled_up_in_the_output(
        self, tmp_path: Path, projected: Profile
    ) -> None:
        result = audit(
            projected, export.read(write_export(tmp_path / "e", Skills=[["Name"]]))
        )
        lines = result.lines()
        assert len(lines) == 1, "one line for all the skills, not one line each"
        assert lines[0] == "missing skills: Python, SQL"

    def test_the_summary_counts_by_severity(
        self, tmp_path: Path, projected: Profile
    ) -> None:
        result = audit(
            projected, export.read(write_export(tmp_path / "e", Skills=[["Name"]]))
        )
        assert result.summary() == "2 missing"


class TestRecordable:
    def test_an_entry_cvme_does_not_manage_is_left_out_of_the_state(self) -> None:
        """Otherwise every later changeset would nag you to delete it."""
        mine = Position(title="A", company="B", start=MonthYear(year=2020))
        theirs = Position(title="Barista", company="Cafe", start=MonthYear(year=2016))
        kept = recordable(
            Profile(positions=[mine]),
            _source(Profile(positions=[mine, theirs], skills=[Skill(name="Excel")])),
            Profile(),
            strict=False,
        )
        assert [p.title for p in kept.positions] == ["A"]
        assert kept.skills == []

    def test_strict_keeps_them_so_the_changeset_says_to_remove_them(self) -> None:
        mine = Position(title="A", company="B", start=MonthYear(year=2020))
        theirs = Position(title="Barista", company="Cafe", start=MonthYear(year=2016))
        live = Profile(positions=[mine, theirs])
        assert (
            recordable(Profile(positions=[mine]), _source(live), Profile(), strict=True)
            == live
        )

    def test_scalars_are_taken_from_the_export_either_way(self) -> None:
        live = Profile(headline="What LinkedIn says", summary="Also what it says")
        kept = recordable(
            Profile(headline="What I wrote"), _source(live), Profile(), strict=False
        )
        assert kept.headline == "What LinkedIn says"
        assert kept.summary == "Also what it says"


def test_severities_are_explained() -> None:
    for severity in ("missing", "stale", "extra"):
        assert audit_module.explain(severity)
