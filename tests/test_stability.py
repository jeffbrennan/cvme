"""Employer stability, researched into a dossier and scored from it."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cvme.config import SearchConfig
from cvme.hunt import stability
from cvme.hunt.report import stability_block
from cvme.hunt.score import evaluate
from cvme.hunt.stability import StabilityError
from cvme.jobs.models import JobPosting

DOSSIER = """---
company: Northwind Health
researched: 2026-09-15
signals:
  - type: layoff
    date: 2025-06
    count: 78
    source: https://example.com/layoffs
  - type: not_profitable
    source: https://example.com/profile
  - type: ownership_venture
    source: https://example.com/funding
  - type: headcount_decline
    period: 2023-2026
    change_pct: -6
    source: https://example.com/headcount
notes: |
  Roughly 750 to 1000 people.
---
"""


def dossier(*signals: str) -> str:
    return (
        "---\ncompany: Example\nresearched: 2026-09-15\nsignals:\n"
        + "".join(signals)
        + "---\n"
    )


def signal(kind: str, source: str = "https://example.com/s", **fields: object) -> str:
    lines = [f"  - type: {kind}\n"]
    for key, value in fields.items():
        lines.append(f"    {key}: {value}\n")
    lines.append(f"    source: {source}\n")
    return "".join(lines)


def posting(description: str = "python, sql", **fields: str) -> JobPosting:
    base = {"url": "https://example.com/1", "title": "Data Engineer"}
    return JobPosting.model_validate({**base, **fields, "description": description})


def test_a_dossier_scores_from_its_signals_and_cites_each_one() -> None:
    parsed = stability.parse(DOSSIER)
    result = stability.score(parsed, today=date(2026, 9, 15))
    # 50 baseline; layoff -10 and headcount -8 are company-scoped at 0.6,
    # not_profitable -5, venture -6.
    assert result.score == 28
    assert result.band == "brittle"
    assert result.known
    assert {signal.type for signal in result.signals} == {
        "layoff",
        "not_profitable",
        "ownership_venture",
        "headcount_decline",
    }
    assert len(result.sources) == 4


def test_an_old_signal_counts_at_half_weight() -> None:
    old = DOSSIER.replace("date: 2025-06", "date: 2015-01")
    recent = stability.score(stability.parse(DOSSIER), today=date(2026, 9, 15))
    stale = stability.score(stability.parse(old), today=date(2026, 9, 15))
    assert stale.score > recent.score  # the -10 layoff decayed toward -5


def test_team_scope_weighs_more_than_company_scope() -> None:
    team = stability.score(
        stability.parse(dossier(signal("layoff", date="2025-06", scope="team"))),
        today=date(2026, 9, 15),
    )
    company = stability.score(
        stability.parse(dossier(signal("layoff", date="2025-06", scope="company"))),
        today=date(2026, 9, 15),
    )
    assert team.score == 40
    assert company.score == 44


def test_no_single_type_can_dominate() -> None:
    many = dossier(
        signal("layoff", date="2025-06", scope="team"),
        signal("layoff", date="2025-07", scope="team"),
        signal("layoff", date="2025-08", scope="team"),
    )
    result = stability.score(stability.parse(many), today=date(2026, 9, 15))
    assert result.score == 38  # capped at -12, not -30


def test_ordinary_churn_is_not_a_signal_but_a_cluster_is() -> None:
    small = dossier(signal("exec_departure", date="2026-01", count=2, scope="team"))
    cluster = dossier(signal("exec_departure", date="2026-01", count=4, scope="team"))
    assert stability.score(stability.parse(small), today=date(2026, 9, 15)).score == 50
    assert (
        stability.score(stability.parse(cluster), today=date(2026, 9, 15)).score == 42
    )


def test_departures_and_hires_are_scored_by_direction() -> None:
    out = stability.parse(
        dossier(signal("exec_departure", date="2026-01", count=4, scope="team"))
    )
    into = stability.parse(
        dossier(signal("exec_hire", date="2026-01", count=3, scope="team"))
    )
    both = stability.parse(
        dossier(
            signal("exec_departure", date="2026-01", count=4, scope="team"),
            signal("exec_hire", date="2026-01", count=3, scope="team"),
        )
    )
    assert stability.score(out, today=date(2026, 9, 15)).score == 42
    assert stability.score(into, today=date(2026, 9, 15)).score == 53
    # A departure and its replacement are separate signals: they net rather
    # than cancel, and the departure keeps its full weight.
    assert stability.score(both, today=date(2026, 9, 15)).score == 45


def test_the_old_exec_turnover_name_still_reads_as_a_departure() -> None:
    legacy = stability.parse(
        dossier(signal("exec_turnover", date="2026-01", count=4, scope="team"))
    )
    scored = stability.score(legacy, today=date(2026, 9, 15))
    assert scored.score == 42
    assert scored.signals[0].type == "exec_departure"


def test_a_leadership_reset_reads_worse_than_continuity() -> None:
    reset = stability.parse(
        dossier(signal("leadership_reset", date="2026-01", scope="team"))
    )
    continuity = stability.parse(
        dossier(signal("leadership_continuity", date="2026-01", scope="team"))
    )
    assert stability.score(reset, today=date(2026, 9, 15)).score == 42
    assert stability.score(continuity, today=date(2026, 9, 15)).score == 55


def test_profitability_is_ignored_for_a_noncommercial_employer() -> None:
    text = dossier(
        signal("ownership_government"),
        signal("not_profitable", date="2025-07"),
    )
    result = stability.score(stability.parse(text), today=date(2026, 9, 15))
    assert result.score == 60  # government +10, not_profitable dropped
    assert all(s.type != "not_profitable" for s in result.signals)


def test_durability_signals_lift_the_score() -> None:
    text = dossier(
        signal("long_history"),
        signal("stable_workforce", scope="team"),
    )
    result = stability.score(stability.parse(text), today=date(2026, 9, 15))
    assert result.score == 66
    assert result.band == "stable"


def test_a_strong_employer_scores_above_baseline() -> None:
    text = dossier(
        signal("profitable", date="2026-02"),
        signal("ownership_public"),
        signal("headcount_growth", period="2024-2026"),
    )
    result = stability.score(stability.parse(text), today=date(2026, 9, 15))
    assert result.score == 72
    assert result.band == "stable"


def test_a_yaml_int_year_is_coerced_to_text() -> None:
    text = dossier(signal("layoff", date="2023"))
    parsed = stability.parse(text)
    assert parsed.signals[0].date == "2023"


def test_an_unknown_signal_type_is_rejected() -> None:
    with pytest.raises(StabilityError):
        stability.parse(dossier(signal("vibes")))


def test_a_hand_set_verdict_is_carried_and_does_not_move_the_score() -> None:
    text = """---
company: Northwind
researched: 2026-09-15
verdict: uninterested
verdict_reason: PBM ownership and the stack
verdict_date: 2026-09-17
signals:
  - type: layoff
    date: 2025-06
    source: https://example.com/s
---
"""
    verdict_line = (
        "verdict: uninterested\n"
        "verdict_reason: PBM ownership and the stack\n"
        "verdict_date: 2026-09-17\n"
    )
    parsed = stability.parse(text)
    result = stability.score(parsed, today=date(2026, 9, 15))
    without = stability.score(
        stability.parse(text.replace(verdict_line, "")), today=date(2026, 9, 15)
    )
    assert parsed.verdict == "uninterested"
    assert result.verdict_reason == "PBM ownership and the stack"
    assert result.score == without.score
    assert stability.summary_line(result) == (
        "stability 44/100 (mixed), verdict uninterested"
    )
    assert "uninterested" in stability.summary_line(result)


def test_a_verdict_is_normalised_and_an_unknown_one_is_rejected() -> None:
    template = """---
company: Northwind
researched: 2026-09-15
verdict: {value}
---
"""
    assert stability.parse(template.format(value='"  Interested "')).verdict == (
        "interested"
    )
    with pytest.raises(StabilityError):
        stability.parse(template.format(value="probably"))


def test_a_dossier_without_a_verdict_leaves_it_empty() -> None:
    result = stability.score(stability.parse(DOSSIER), today=date(2026, 9, 15))
    assert result.verdict == ""
    assert "verdict" not in stability.summary_line(result)


def test_a_signal_without_a_source_is_rejected() -> None:
    text = """---
company: Northwind
researched: 2026-09-15
signals:
  - type: layoff
    date: 2025-01
---
"""
    with pytest.raises(StabilityError):
        stability.parse(text)


def test_load_is_none_when_no_dossier_exists(tmp_path: Path) -> None:
    assert stability.load(tmp_path, "Nobody") is None


def test_load_scores_a_missing_company_as_unknown(tmp_path: Path) -> None:
    (tmp_path / "northwind-health.md").write_text(DOSSIER, encoding="utf-8")
    result = stability.load(tmp_path, "Northwind Health", today=date(2026, 9, 15))
    assert result is not None and result.known
    assert result.company == "Northwind Health"


def test_a_malformed_dossier_is_an_error_not_a_silent_skip(tmp_path: Path) -> None:
    (tmp_path / "northwind-health.md").write_text("not a dossier", encoding="utf-8")
    with pytest.raises(StabilityError):
        stability.load(tmp_path, "Northwind Health")


def test_weights_are_overridable(tmp_path: Path) -> None:
    (tmp_path / "northwind-health.md").write_text(DOSSIER, encoding="utf-8")
    baseline = stability.load(tmp_path, "Northwind Health", today=date(2026, 9, 15))
    heavier = stability.load(
        tmp_path,
        "Northwind Health",
        weights={"layoff": -30},
        max_per_type=50,
        today=date(2026, 9, 15),
    )
    assert baseline is not None and heavier is not None
    assert heavier.score < baseline.score


def test_the_fit_carries_stability_and_a_missing_dossier_is_neutral() -> None:
    fit = evaluate(posting(), "", SearchConfig())
    assert fit.axis("stability") == stability.BASELINE
    assert fit.stability is None


def test_a_researched_employer_moves_the_stability_axis() -> None:
    researched = stability.score(stability.parse(DOSSIER), today=date(2026, 9, 15))
    fit = evaluate(posting(), "", SearchConfig(), stability=researched)
    assert fit.axis("stability") == researched.score
    assert fit.axis("stability") < stability.BASELINE


def test_the_report_block_prints_the_verdict() -> None:
    text = """---
company: Northwind
researched: 2026-09-15
verdict: uninterested
verdict_reason: PBM ownership and the stack
signals:
  - type: layoff
    date: 2025-06
    source: https://example.com/s
---
"""
    researched = stability.score(stability.parse(text), today=date(2026, 9, 15))
    block = "\n".join(
        stability_block(evaluate(posting(), "", SearchConfig(), stability=researched))
    )
    assert "**Verdict uninterested.** PBM ownership and the stack" in block
