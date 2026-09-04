"""Page-budget enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from cvme.errors import FitError
from cvme.md.parse import parse
from cvme.render.fit import LADDER, fit, page_count
from cvme.style.schema import Style, resolve
from tests.conftest import FIXTURES


@pytest.fixture(scope="session")
def long_source() -> str:
    return (FIXTURES / "resume_long.md").read_text()


def test_the_long_fixture_really_does_overflow(
    long_source: str, tmp_path: Path
) -> None:
    """Guards the other tests: if this ever fits, they stop proving anything."""
    style = resolve("standard", {"on_overflow": "warn"})
    result = fit(parse(long_source), style, output=tmp_path / "o.pdf")
    assert result.pages > 1
    assert result.applied == []


def test_autofit_meets_the_budget(long_source: str, tmp_path: Path) -> None:
    result = fit(parse(long_source), resolve("standard"), output=tmp_path / "o.pdf")
    assert result.pages == 1
    assert result.applied, "expected the ladder to report what it tightened"
    assert page_count(tmp_path / "o.pdf") == 1


def test_a_document_already_within_budget_is_left_alone(
    resume_doc, standard: Style, tmp_path: Path
) -> None:
    result = fit(resume_doc, standard, output=tmp_path / "o.pdf")
    assert result.applied == []
    assert result.style == standard


def test_impossible_budget_fails_with_a_diagnostic(
    long_source: str, tmp_path: Path
) -> None:
    experience = long_source.split("## Experience")[1].split("## Education")[0]
    head, _, tail = long_source.partition("## Education")
    doubled = parse(head + experience * 2 + "## Education" + tail)

    with pytest.raises(FitError) as excinfo:
        fit(doubled, resolve("standard"), output=tmp_path / "o.pdf")

    message = str(excinfo.value)
    assert "budget is 1" in message
    assert "largest sections" in message
    assert "Experience" in message
    assert "#strong[" not in message, "diagnostics should not leak Typst markup"


def test_failure_removes_every_rejected_attempt(
    long_source: str, tmp_path: Path
) -> None:
    experience = long_source.split("## Experience")[1].split("## Education")[0]
    head, _, tail = long_source.partition("## Education")
    doubled = parse(head + experience * 2 + "## Education" + tail)
    out = tmp_path / "o.pdf"
    with pytest.raises(FitError):
        fit(doubled, resolve("standard"), output=out)
    assert not out.exists()


@pytest.mark.parametrize("step", LADDER, ids=lambda s: s.name)
def test_every_ladder_step_stops_at_its_floor(step) -> None:
    """Applied repeatedly, a step must eventually refuse rather than run away."""
    style = resolve("standard")
    for _ in range(500):
        tightened = step.apply(style)
        if tightened is None:
            break
        assert tightened != style
        style = tightened
    else:
        pytest.fail(f"{step.name} never reached a floor")
    assert style.body_size >= 9.0
    assert style.leading > 0
    assert style.margin_x > 0


@pytest.mark.parametrize("preset", ["standard", "compact", "airy"])
def test_every_preset_renders(resume_doc, preset: str, tmp_path: Path) -> None:
    result = fit(resume_doc, resolve(preset), output=tmp_path / f"{preset}.pdf")
    assert result.pages >= 1


def test_a_gaps_section_never_reaches_the_pdf(tmp_path: Path) -> None:
    """It lists what the corpus could not answer, addressed to the author.

    The tailoring prompt asks for it by name, so it arrives in every generated
    draft. Rendering it would hand the reader a list of your weaknesses.
    """
    import pdfplumber

    doc = parse(
        "---\nname: Morgan Avery\n---\n\n"
        "## Summary\n\nBuilt the ingestion platform.\n\n"
        "## Gaps\n\n- No Kafka experience is evidenced.\n"
    )
    output = tmp_path / "letter.pdf"
    fit(doc, resolve("standard"), output=output)
    with pdfplumber.open(output) as pdf:
        text = pdf.pages[0].extract_text()
    assert "Built the ingestion platform" in text
    assert "Kafka" not in text
    # Upper-cased, because that is how the template sets a section header, and
    # a case-sensitive check here would pass on an unfixed renderer.
    assert "GAPS" not in text.upper()
