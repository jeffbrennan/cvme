"""Reading the rendered PDF back the way a parser would.

These tests exist because the artefact is the only thing an applicant tracking
system sees. The interesting one is `test_a_drawn_marker_loses_the_bullets`: it
renders a document whose bullets look perfect and extract as one undivided
paragraph, which is exactly the failure this command is for.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvme.ats.check import _dates, _glyphs, _sections, check_pdf
from cvme.cli.app import app
from cvme.convert.pdftext import Layout, Line, Run
from cvme.md.parse import parse
from cvme.models import Document
from cvme.render.engine import compile_document
from cvme.style.schema import Style

runner = CliRunner()


def _rules(report) -> set[str]:
    return {finding.rule for finding in report.findings}


@pytest.fixture(scope="session")
def report(resume_pdf: Path, resume_doc: Document):
    return check_pdf(resume_pdf, source=resume_doc)


def test_the_rendered_fixture_reads_back_as_written(report) -> None:
    assert report.ok, report.format()
    assert "ats:structure" not in _rules(report)


def test_the_fixture_keeps_its_letterhead_and_dates(report) -> None:
    parsed = {"ats:name", "ats:email", "ats:dates", "ats:bullets"}
    assert parsed & _rules(report) == set()


def test_missing_keywords_are_reported(report) -> None:
    """The fixture sets no keywords, and metadata is read first by many parsers."""
    assert "ats:keywords" in _rules(report)


def test_a_drawn_marker_loses_the_bullets(
    resume_doc: Document, standard: Style, tmp_path: Path
) -> None:
    drawn = standard.model_copy(update={"marker_glyph": ""})
    pdf = compile_document(resume_doc, drawn, output=tmp_path / "drawn.pdf")
    report = check_pdf(pdf, source=resume_doc)
    assert "ats:structure" in _rules(report)
    assert not report.ok


def test_a_pdf_on_its_own_can_be_checked(resume_pdf: Path) -> None:
    report = check_pdf(resume_pdf)
    assert "ats:structure" not in _rules(report)
    assert report.ok


def test_a_symbol_font_marker_is_an_error() -> None:
    """A Wingdings bullet extracts as a literal section sign."""
    line = Line(
        page=1,
        baseline=700.0,
        runs=(
            Run(text="§", x0=75.6, x1=84.0, size=12.0, symbol=True),
            Run(text=" Built a pipeline", x0=90.0, x1=200.0, size=11.0),
        ),
    )
    layout = Layout(
        lines=(line,), body_size=11.0, left=57.6, right=554.4, line_height=13.4
    )
    findings = _glyphs(layout)
    assert [f.rule for f in findings] == ["ats:symbol-font"]
    assert findings[0].severity == "error"


def test_a_date_that_does_not_parse_is_flagged() -> None:
    document = parse(
        "---\nname: A\n---\n\n## Experience\n\n### Engineer @ Acme | summer 2023\n"
    )
    assert [f.rule for f in _dates(document)] == ["ats:dates"]


def test_ordinary_date_ranges_pass() -> None:
    for dates in ("Jul 2023 – Present", "May 2020 - Sep 2023", "2019 – 2020"):
        document = parse(
            f"---\nname: A\n---\n\n## Experience\n\n### Engineer @ Acme | {dates}\n"
        )
        assert _dates(document) == [], dates


def test_an_unrecognised_section_name_is_flagged() -> None:
    document = parse("---\nname: A\n---\n\n## What I Bring\n\nProse.\n")
    assert [f.rule for f in _sections(document)] == ["ats:section-name"]


def test_a_proficiency_in_parentheses_is_flagged_but_a_tool_list_is_not(
    tmp_path: Path, standard: Style
) -> None:
    source = """---
name: A
---

## Skills

- **Languages**: Python (advanced), SQL (advanced)
- **Data Stack**: Transformation (pyspark, dbt, polars)
"""
    pdf = compile_document(parse(source), standard, output=tmp_path / "skills.pdf")
    flagged = [
        f.excerpt
        for f in check_pdf(pdf).findings
        if f.rule == "ats:skill-parenthetical"
    ]
    assert len(flagged) == 1
    assert flagged[0].startswith("Languages")


def test_the_cli_checks_a_document_by_name(resume_source: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["ats", str(resume_source)])
    assert result.exit_code == 0, result.output
    assert "warning" in result.output


def test_the_cli_exits_three_when_a_project_renders_unreadable_output(
    resume_source: Path, tmp_path: Path
) -> None:
    """A project that draws its markers passes render and fails this."""
    (tmp_path / "resume.md").write_text(resume_source.read_text())
    (tmp_path / "cvme.toml").write_text(
        '[documents.resume]\npath = "resume.md"\n\n'
        '[documents.resume.overrides]\nmarker_glyph = ""\n'
    )
    result = runner.invoke(
        app, ["ats", "resume", "--config", str(tmp_path / "cvme.toml")]
    )
    assert result.exit_code == 3
    assert "ats:structure" in result.output


def test_the_cli_emits_json(resume_pdf: Path) -> None:
    result = runner.invoke(app, ["ats", str(resume_pdf), "--json"])
    assert result.exit_code == 0
    assert '"findings"' in result.stdout
