"""The fit score, which has to be defensible before it is useful."""

from __future__ import annotations

from cvme.config import SearchConfig
from cvme.hunt.score import (
    Fit,
    evaluate,
    load_lexicon,
    mentions,
    normalise,
    years_required,
)
from cvme.jobs.models import JobPosting

CORPUS = """
# Skills
- Python: advanced. Production pipelines and CLIs.
- SQL: advanced, against Databricks and Postgres.
- Spark and PySpark: batch and streaming transformation.
- Seven years across the healthcare data lifecycle.
"""


def posting(description: str, **fields: str) -> JobPosting:
    base = {"url": "https://example.com/1", "title": "Data Engineer"}
    return JobPosting.model_validate({**base, **fields, "description": description})


def test_terms_are_matched_on_whole_tokens_not_substrings() -> None:
    found = mentions("we use rust and golang", load_lexicon())
    assert found.get("rust") == 1
    assert found.get("go") == 1
    assert "r" not in found, "'r' must not match inside another word"


def test_mentions_are_counted_so_repetition_carries_weight() -> None:
    found = mentions("spark, spark and more spark, plus dbt", load_lexicon())
    assert found["spark"] == 3
    assert found["dbt"] == 1


def test_aliases_collapse_to_one_canonical_term() -> None:
    found = mentions("postgres and postgresql and psql", load_lexicon())
    assert found["postgresql"] == 3


def test_a_covered_posting_scores_higher_than_an_uncovered_one() -> None:
    search = SearchConfig()
    covered = evaluate(posting("python, sql, spark, databricks"), CORPUS, search)
    uncovered = evaluate(posting("rust, kafka, terraform, neo4j"), CORPUS, search)
    assert covered.score > uncovered.score
    assert {r.term for r in covered.missing} == set()
    assert {r.term for r in uncovered.matched} == set()


def test_the_score_reports_which_terms_are_not_answered() -> None:
    fit = evaluate(posting("we need python and rust"), CORPUS, SearchConfig())
    assert [r.term for r in fit.matched] == ["python"]
    assert [r.term for r in fit.missing] == ["rust"]


def test_years_are_read_from_either_form() -> None:
    assert years_required("6+ years of experience") == 6
    assert years_required("three years minimum") == 3
    # The low end of a range is the bar you have to clear, not the high end.
    assert years_required("5-7 years") == 5
    assert years_required("no requirement stated") is None


def test_experience_is_prorated_when_the_corpus_falls_short() -> None:
    search = SearchConfig()
    short = evaluate(posting("20+ years of experience with python"), CORPUS, search)
    met = evaluate(posting("5+ years of experience with python"), CORPUS, search)
    experience = {c.name: c for c in short.components}["experience"]
    assert experience.earned < 15
    assert {c.name: c for c in met.components}["experience"].earned == 15


def test_a_preferred_title_earns_the_title_component() -> None:
    search = SearchConfig(preferred_titles=["data engineer"])
    hit = evaluate(posting("python", title="Senior Data Engineer"), CORPUS, search)
    miss = evaluate(posting("python", title="Product Manager"), CORPUS, search)
    assert {c.name: c.earned for c in hit.components}["title"] == 15
    assert {c.name: c.earned for c in miss.components}["title"] == 0


def test_an_excluded_posting_is_blocked_rather_than_scored() -> None:
    search = SearchConfig(exclude_keywords=["security clearance"])
    fit = evaluate(
        posting("python, sql, spark. Requires an active security clearance."),
        CORPUS,
        search,
    )
    assert fit.score == 0
    assert fit.band == "blocked"
    assert "security clearance" in fit.blockers[0]


def test_a_posting_outside_the_vocabulary_is_not_scored_as_a_bad_match() -> None:
    """Zero would be a claim about the fit; this is a claim about the lexicon."""
    fit = evaluate(posting("We need a skilled glassblower."), CORPUS, SearchConfig())
    skills = {c.name: c for c in fit.components}["skills"]
    assert skills.earned == 30
    assert "no known terms" in skills.detail


def test_extra_terms_extend_the_vocabulary() -> None:
    search = SearchConfig()
    plain = evaluate(posting("we live and die by HEDIS measures"), CORPUS, search)
    extended = evaluate(
        posting("we live and die by HEDIS measures"),
        CORPUS,
        search,
        extra_terms={"quality measures": ["hedis"]},
    )
    assert "quality measures" not in {r.term for r in plain.requirements}
    assert "quality measures" in {r.term for r in extended.requirements}


def test_bands_follow_the_score() -> None:
    assert Fit(80).band == "strong"
    assert Fit(60).band == "fair"
    assert Fit(40).band == "thin"
    assert Fit(10).band == "weak"


def test_normalise_keeps_the_characters_that_name_things() -> None:
    assert normalise("C#, C++ and .NET!") == ["c#", "c++", "and", "net"]
