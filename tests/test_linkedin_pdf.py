"""Reading the profile PDF, and what a partial source may be compared against."""

from __future__ import annotations

from pathlib import Path

import pytest

from cvme.linkedin import export, live, pdfprofile
from cvme.linkedin.audit import audit, recordable
from cvme.linkedin.live import Source, SourceError
from cvme.linkedin.model import Education, MonthYear, Position, Profile, Skill
from cvme.linkedin.project import to_profile
from cvme.models import Document
from tests.test_linkedin_audit import write_export


class TestProfilePdf:
    """The round trip: markdown -> PDF -> markdown -> Profile.

    Uses the project's own renderer for the PDF, which is the closest thing to
    a LinkedIn profile PDF that can be produced offline: both are a resume laid
    out as sections, roles with dates, and bulleted descriptions, and both are
    read back by the same geometry-driven ``convert``.
    """

    def test_a_resume_pdf_reads_back_as_the_profile_it_came_from(
        self, resume_pdf: Path, resume_doc: Document
    ) -> None:
        source = pdfprofile.read(resume_pdf)
        wanted, _ = to_profile(resume_doc)
        result = audit(wanted, source)
        assert result.findings == [], result.lines()

    def test_the_headline_and_about_survive_the_round_trip(
        self, resume_pdf: Path
    ) -> None:
        profile = pdfprofile.read(resume_pdf).profile
        assert profile.headline == "Staff Data Engineer at Northwind Analytics"
        assert profile.summary.startswith("Careful handling of operational data")

    def test_every_position_survives_with_its_bullets(self, resume_pdf: Path) -> None:
        positions = pdfprofile.read(resume_pdf).profile.positions
        assert [p.company for p in positions] == [
            "Northwind Analytics",
            "GreyHarbor Health",
            "Cascade Public Health",
            "Ridgeway Institute",
        ]
        assert positions[0].description.count("•") == 5
        assert positions[0].start == MonthYear(year=2023, month=7)

    def test_the_degree_is_recovered_from_the_layout(self, resume_pdf: Path) -> None:
        """A PDF has no paragraphs, so the degree line arrives as loose prose."""
        first = pdfprofile.read(resume_pdf).profile.educations[0]
        assert first.school == "Ridgeway University"
        assert first.degree == "Master of Science"
        assert first.field_of_study == "Epidemiology"
        assert first.end == MonthYear(year=2020, month=5)
        assert first.description == "Certificate: Data Science"

    def test_a_pdf_never_vouches_for_skills(self, resume_pdf: Path) -> None:
        """LinkedIn prints about three "Top Skills", not the whole list."""
        source = pdfprofile.read(resume_pdf)
        assert "skills" not in source.covers
        assert "skills" in source.unchecked

    def test_a_pdf_that_is_not_a_profile_says_so(self, tmp_path: Path) -> None:
        empty = tmp_path / "notes.pdf"
        empty.write_bytes(b"%PDF-1.4\n%%EOF\n")
        with pytest.raises(SourceError):
            pdfprofile.read(empty)


class TestDegreeRecovery:
    @pytest.mark.parametrize(
        ("description", "degree", "field", "rest"),
        [
            (
                "Bachelor of Science - Major in Public Health May 2018",
                "Bachelor of Science",
                "Public Health",
                "",
            ),
            (
                "Master of Science in Epidemiology May 2020 Certificate: X",
                "Master of Science",
                "Epidemiology",
                "Certificate: X",
            ),
            # No month here: "Science" must not be read as one.
            ("Master of Science 2020", "Master of Science", "", ""),
        ],
    )
    def test_the_line_splits_at_the_award_date(
        self, description: str, degree: str, field: str, rest: str
    ) -> None:
        recovered = pdfprofile._recover_degrees(
            Profile(educations=[_education(description)])
        ).educations[0]
        assert (recovered.degree, recovered.field_of_study) == (degree, field)
        assert recovered.description == rest

    def test_prose_with_no_date_is_left_alone(self) -> None:
        recovered = pdfprofile._recover_degrees(
            Profile(educations=[_education("Some note with no date in it")])
        ).educations[0]
        assert recovered.degree == ""
        assert recovered.description == "Some note with no date in it"

    def test_education_is_not_vouched_for_when_a_degree_is_unrecoverable(self) -> None:
        """One bare school name would audit as a degree missing from a profile."""
        profile = Profile(educations=[_education("no date here")])
        assert pdfprofile._unrecovered(profile) == {"educations"}


class TestSourceLadder:
    def test_a_pdf_is_read_as_a_pdf(self, resume_pdf: Path) -> None:
        assert "profile PDF" in live.read(resume_pdf).label

    def test_a_directory_is_read_as_an_export(self, tmp_path: Path) -> None:
        assert "data export" in live.read(write_export(tmp_path / "e")).label

    def test_an_unknown_file_explains_both_routes(self, tmp_path: Path) -> None:
        odd = tmp_path / "profile.txt"
        odd.write_text("not a profile", encoding="utf-8")
        with pytest.raises(SourceError) as caught:
            live.read(odd)
        assert "Save to PDF" in str(caught.value)
        assert "Get a copy of your data" in str(caught.value)

    def test_a_missing_path_explains_them_too(self, tmp_path: Path) -> None:
        with pytest.raises(SourceError, match="Save to PDF"):
            live.read(tmp_path / "nowhere.pdf")


class TestCoverage:
    """A source is only compared against what it actually reports."""

    def test_a_part_the_source_does_not_report_is_not_drift(self) -> None:
        wanted = Profile(headline="Staff DE", skills=[Skill(name="Python")])
        partial = Source(profile=Profile(headline="Staff DE"), covers={"headline"})
        assert audit(wanted, partial).findings == [], (
            "a source that never looked at skills has not found them missing"
        )

    def test_a_skills_only_export_checks_skills_only(self, tmp_path: Path) -> None:
        root = tmp_path / "e"
        write_export(root)
        for name in ("Profile", "Positions", "Education"):
            (root / f"{name}.csv").unlink()
        source = export.read(root)
        assert source.covers == {"skills"}
        wanted = Profile(
            positions=[Position(title="A", company="B", start=MonthYear(year=2020))],
            skills=[Skill(name="Python"), Skill(name="SQL")],
        )
        assert audit(wanted, source).findings == []

    def test_an_empty_table_still_counts_as_reported(self, tmp_path: Path) -> None:
        """A Skills.csv with only a header says you have no skills."""
        root = tmp_path / "e"
        write_export(root, Skills=[["Name"]])
        for name in ("Profile", "Positions", "Education"):
            (root / f"{name}.csv").unlink()
        source = export.read(root)
        assert "skills" in source.covers, (
            "present but empty is LinkedIn saying none, not cvme failing to look"
        )
        wanted = Profile(skills=[Skill(name="Python")])
        assert [f.severity for f in audit(wanted, source).findings] == ["missing"]

    def test_recording_keeps_what_the_source_could_not_see(self) -> None:
        """Otherwise a PDF would blank the skills the last export established."""
        already = Profile(skills=[Skill(name="Python"), Skill(name="SQL")])
        wanted = Profile(headline="Staff DE", skills=[Skill(name="Python")])
        pdf = Source(profile=Profile(headline="Staff DE"), covers={"headline"})
        kept = recordable(wanted, pdf, already, strict=False)
        assert kept.headline == "Staff DE"
        assert [s.name for s in kept.skills] == ["Python", "SQL"]


def _education(description: str) -> Education:
    return Education(school="Ridgeway University", description=description)
