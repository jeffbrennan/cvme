from pathlib import Path

import pytest

from cvme.config import SearchConfig, load_config
from cvme.errors import ConfigError
from cvme.hunt.report import fit_block
from cvme.hunt.score import evaluate as fit
from cvme.hunt.wants import Profile, evaluate, load
from cvme.jobs.models import JobPosting


def profile(**changes) -> Profile:
    rule = dict(
        name="platform", weight=8, reason="my preference", any_of=["Databricks"]
    )
    rule.update(changes)
    return Profile(rules=[rule])


def posting(text: str, company: str = "") -> JobPosting:
    return JobPosting(
        url="https://example.test/job",
        title="Data Engineer",
        company=company,
        description=text,
    )


def test_repetition_and_aliases_count_once():
    p = profile(any_of=["CI/CD", "cicd", "continuous integration"])
    assert (
        evaluate(posting("CI/CD, CI/CD and continuous integration"), p).adjustment == 8
    )
    assert not evaluate(posting("Sassy"), profile(any_of=["SAS"])).signals


def test_missing_platform_is_one_penalty_and_blank_capture_is_unknown():
    p = profile(any_of=["Databricks", "Snowflake"], when="absent", weight=-8)
    assert evaluate(posting("Python SQL"), p).adjustment == -8
    assert evaluate(posting("Snowflake"), p).adjustment == 0
    assert evaluate(posting(""), p).adjustment == 0


def test_scope_and_context_guards():
    p = profile(any_of=["Northwind Health"], scope="company")
    assert (
        evaluate(posting("Our customer is Northwind Health", "Startup"), p).adjustment
        == 0
    )
    assert evaluate(posting("Python", "Northwind Health"), p).adjustment == 8
    p = profile(
        any_of=["AI platform"], requires_any=["startup"], unless_any=["migration"]
    )
    assert evaluate(posting("Hospital AI platform"), p).adjustment == 0
    assert evaluate(posting("Startup AI platform"), p).adjustment == 8
    assert evaluate(posting("Startup AI platform migration"), p).adjustment == 0


def test_axis_preferences_move_their_axis_and_filters_still_win():
    p = Profile(
        rules=[
            dict(name="one", weight=30, any_of=["Python"], reason="one", axis="skills"),
            dict(name="two", weight=-30, any_of=["SQL"], reason="two", axis="domain"),
        ]
    )
    job = posting("Python SQL")
    base = fit(job, "Python SQL", SearchConfig())
    adjusted = fit(job, "Python SQL", SearchConfig(), wants=p)
    assert adjusted.preferences is not None
    assert adjusted.preferences.by_axis["skills"] == 30
    assert adjusted.preferences.by_axis["domain"] == -30
    assert adjusted.axis("skills") >= base.axis("skills")
    assert adjusted.axis("domain") < base.axis("domain")
    # A domain below its gate caps the composite, whatever the other axes say.
    assert adjusted.axis("domain") < 30
    assert adjusted.score <= adjusted.axis("domain")
    blocked = fit(
        job, "Python SQL", SearchConfig(excluded_titles=["engineer"]), wants=p
    )
    assert blocked.score == 0 and blocked.band == "blocked"
    text = fit_block(job, adjusted)
    assert "Personal preferences" in text and "posting: Python" in text
    assert "| axis | signal |" in text
    assert "skills" in text and "domain" in text


def test_config_resolves_profile_and_prose_is_not_a_rule(tmp_path: Path):
    (tmp_path / "cvme.toml").write_text('[fit]\nwants = "WANTS.md"\n')
    path = tmp_path / "WANTS.md"
    path.write_text("---\nversion: 1\nrules: []\n---\nPrefer Databricks.\n")
    config = load_config(tmp_path / "cvme.toml")
    assert config.fit.wants == path
    loaded = load(path)
    assert loaded is not None and loaded.rules == []
    assert load(None) is None


@pytest.mark.parametrize(
    "contents",
    [
        "No frontmatter",
        "---\nrules: []",
        "---\nunknown: true\n---",
        "---\nrules: [{name: x, weight: 5, reason: x, any_of: ['!']}]\n---",
        "---\nrules: [{name: x, weight: 0, reason: x, any_of: [SQL]}]\n---",
    ],
)
def test_invalid_profile_is_an_actionable_error(tmp_path: Path, contents: str):
    path = tmp_path / "WANTS.md"
    path.write_text(contents)
    with pytest.raises(ConfigError, match="WANTS"):
        load(path)
    with pytest.raises(ConfigError, match="WANTS"):
        load(tmp_path / "missing.md")
