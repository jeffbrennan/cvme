"""Claim sourcing and prose rules.

A prompt telling a model not to invent numbers fails silently. These are the
checks that actually hold, so they are tested against a deliberately
adversarial document rather than only a clean one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cvme.verify.check import verify_file, verify_text
from cvme.verify.corpus import Corpus, load
from cvme.verify.numbers import extract
from cvme.verify.prose import load_rules
from tests.conftest import FIXTURES

FACTS = [FIXTURES / "facts" / "skills.md", FIXTURES / "facts" / "metrics.md"]


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    return load(FACTS)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("8B+ events", (8e9, None)),
        ("8,000,000,000 events", (8e9, None)),
        ("$20M+ in savings", (2e7, "currency")),
        ("35%", (35.0, "%")),
        ("six years", (6.0, "year")),
        ("6 yrs", (6.0, "year")),
        ("40 minutes", (40.0, "minute")),
        ("120TB", (120.0, "tb")),
    ],
)
def test_equivalent_spellings_normalise_together(
    text: str, expected: tuple[float, str | None]
) -> None:
    assert extract(text)[0].key == expected


def test_bare_years_are_not_claims() -> None:
    """A resume is full of dates; treating them as claims would be useless."""
    assert extract("Jan 2019 – Dec 2020") == []


def test_rounding_a_corpus_figure_up_is_not_allowed() -> None:
    """The exact case this exists to catch."""
    corpus = Corpus()
    corpus.keys = {(98000.0, "currency")}
    corpus.sources = [Path("x")]
    report = verify_text("- Managed $100k per month\n", Path("d.md"), corpus)
    assert [f.rule for f in report.errors] == ["fact:unsourced"]


def test_the_clean_fixtures_verify(corpus: Corpus) -> None:
    for name in ("resume.md", "cover_letter.md", "resume_long.md"):
        report = verify_file(FIXTURES / name, corpus)
        assert report.ok, report.format()


def test_the_adversarial_fixture_is_caught(corpus: Corpus) -> None:
    report = verify_file(FIXTURES / "resume_bad.md", corpus)
    rules = {f.rule for f in report.findings}
    for expected in (
        "em-dash",
        "not-x-but-y",
        "fact:unsourced",
        "fact:unknown",
        "fact:mismatch",
        "weak-opener",
        "triad",
        "phrase:leverage",
    ):
        assert expected in rules, f"{expected} not caught: {sorted(rules)}"
    assert not report.ok


def test_an_invented_metric_is_reported_with_its_line(corpus: Corpus) -> None:
    report = verify_file(FIXTURES / "resume_bad.md", corpus)
    unsourced = [f for f in report.findings if f.rule == "fact:unsourced"]
    assert {f.message.split("'")[1] for f in unsourced} == {"11B", "$4M"}
    assert all(f.line > 0 for f in unsourced)


def test_a_tagged_claim_must_match_the_fact_it_cites(corpus: Corpus) -> None:
    """Citing a real fact that does not carry the number is still wrong."""
    report = verify_text(
        "- Cut the window to 40 minutes <!-- fact: m-analysts -->\n",
        Path("d.md"),
        corpus,
    )
    assert [f.rule for f in report.errors] == ["fact:mismatch"]


def test_untagged_claims_may_come_from_anywhere_in_the_corpus(corpus: Corpus) -> None:
    report = verify_text("- Reported across 14 facilities\n", Path("d.md"), corpus)
    assert report.ok


def test_labelled_list_lines_are_exempt_from_rhetoric_rules(corpus: Corpus) -> None:
    """'a, b, and c' in a skills list is an enumeration, not cadence."""
    line = "- **Data Stack**: extracting, loading, and transforming\n"
    report = verify_text(line, Path("d.md"), corpus, check_facts=False)
    assert "triad" not in {f.rule for f in report.findings}


def test_frontmatter_is_not_checked(corpus: Corpus) -> None:
    text = "---\ntitle: leveraging synergy\n---\n\n- A clean bullet\n"
    report = verify_text(text, Path("d.md"), corpus, check_facts=False)
    assert report.findings == []


def test_prose_only_mode_ignores_sourcing(corpus: Corpus) -> None:
    report = verify_text("- Delivered $4M\n", Path("d.md"), corpus, check_facts=False)
    assert report.ok


def test_corpus_derives_ids_when_untagged(tmp_path: Path) -> None:
    path = tmp_path / "facts.md"
    path.write_text("- Managed a team of 4 engineers.\n")
    loaded = load([path])
    assert len(loaded.facts) == 1
    assert (4.0, None) in loaded.keys


def test_every_rule_has_a_usable_message() -> None:
    for rule in load_rules():
        assert rule.message
        assert rule.severity in {"error", "warning"}


def test_json_output_is_machine_readable(corpus: Corpus) -> None:
    import json

    report = verify_file(FIXTURES / "resume_bad.md", corpus)
    payload = json.loads(report.to_json())
    assert payload["findings"]
    assert {"rule", "severity", "message", "line"} <= set(payload["findings"][0])
