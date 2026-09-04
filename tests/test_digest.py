from __future__ import annotations

import importlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import SearchConfig, SearchSourceConfig
from cvme.jobs.discovery import DiscoveredJob, identity, parse_results, search_url
from cvme.jobs.match import evaluate
from cvme.jobs.models import JobPosting
from cvme.jobs.rate import RateLimiter
from cvme.jobs.store import JobStore

runner = CliRunner()


LINKEDIN_RESULTS = """
<ul><li><div class="base-card">
  <a class="base-card__full-link"
     href="https://www.linkedin.com/jobs/view/data-engineer-12345?trk=x"></a>
  <h3 class="base-search-card__title">Data Engineer</h3>
  <h4 class="base-search-card__subtitle">Acme</h4>
  <span class="job-search-card__location">Dublin</span>
</div></li></ul>
"""

INDEED_RESULTS = """
<ul><li><div class="job_seen_beacon">
  <a data-jk="abc" href="/viewjob?jk=abc&from=search">
    <span data-testid="jobTitle">Platform Engineer</span>
  </a>
  <span data-testid="company-name">Contoso</span>
  <div data-testid="text-location">Remote</div>
</div></li></ul>
"""


def test_search_results_are_normalised_to_stable_urls() -> None:
    linkedin = parse_results(LINKEDIN_RESULTS, "linkedin")
    assert linkedin == [
        DiscoveredJob(
            "https://www.linkedin.com/jobs/view/12345",
            "linkedin",
            "Data Engineer",
            "Acme",
            "Dublin",
        )
    ]
    indeed = parse_results(
        INDEED_RESULTS, "indeed", base_url="https://www.indeed.com/jobs?q=x"
    )
    assert indeed[0].url == "https://www.indeed.com/viewjob?jk=abc"
    assert indeed[0].company == "Contoso"


def test_identity_ignores_tracking_and_linkedin_slugs() -> None:
    assert identity("https://www.linkedin.com/jobs/view/title-123?trk=x") == (
        "linkedin:123"
    )
    assert identity("https://www.indeed.com/viewjob?jk=abc&from=x") == "indeed:abc"


def test_search_urls_carry_recency_and_remote_filters() -> None:
    linkedin = SearchSourceConfig(
        site="linkedin",
        query="data engineer",
        location="New York, NY",
        remote=True,
        posted_within_days=7,
    )
    linkedin_query = parse_qs(urlsplit(search_url(linkedin, 1)).query)
    assert linkedin_query["f_WT"] == ["2"]
    assert linkedin_query["f_TPR"] == ["r604800"]
    assert linkedin_query["start"] == ["25"]

    indeed = linkedin.model_copy(update={"site": "indeed"})
    indeed_query = parse_qs(urlsplit(search_url(indeed, 1)).query)
    assert indeed_query["sc"] == ["0kf:attr(DSQF7);"]
    assert indeed_query["fromage"] == ["7"]
    assert indeed_query["start"] == ["10"]


def test_rate_limiter_spaces_request_starts_without_real_sleep() -> None:
    now = 100.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    limiter = RateLimiter(5.0, clock=clock, sleep=sleep)
    limiter.wait()
    now += 2.0
    limiter.wait()
    now += 7.0
    limiter.wait()
    assert sleeps == [3.0]


def test_company_and_other_preferences_are_hard_filters() -> None:
    config = SearchConfig(
        blocked_companies=["Raytheon", "Palantir"],
        exclude_keywords=["clearance"],
        preferred_titles=["data engineer"],
        include_keywords=["python"],
        minimum_score=4,
    )
    blocked = JobPosting(url="u", company="Raytheon Technologies")
    assert evaluate(blocked, config).reason == "blocked company: Raytheon"
    good = JobPosting(
        url="u",
        title="Senior Data Engineer",
        company="Acme",
        description="Build reliable Python systems.",
    )
    assert evaluate(good, config).accepted
    assert evaluate(good, config).score == 4
    excluded = good.model_copy(update={"description": "Clearance is required"})
    assert not evaluate(excluded, config).accepted


def test_store_deduplicates_and_never_requeues_decided_jobs(tmp_path: Path) -> None:
    job = DiscoveredJob("https://x.test/1", "generic", "Engineer", "Acme")
    with JobStore(tmp_path / "jobs.sqlite3") as store:
        assert store.add([job]) == (1, 0)
        assert store.add([job]) == (0, 1)
        assert len(store.pending()) == 1
        store.decide(
            job.key,
            status="filtered",
            title=job.title,
            company=job.company,
            reason="test",
        )
        assert store.pending() == []
        assert store.add([job]) == (0, 1)
        assert store.pending() == []


def test_digest_filters_blocks_and_writes_only_new_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    config_path = tmp_path / "cvme.toml"
    with config_path.open("a") as handle:
        handle.write('\n[[search.sources]]\nsite = "linkedin"\nquery = "engineer"\n')

    found = [
        DiscoveredJob("https://x.test/good", "linkedin", "Data Engineer", "Acme"),
        DiscoveredJob(
            "https://x.test/bad", "linkedin", "Engineer", "Palantir Technologies"
        ),
    ]
    digest_module = importlib.import_module("cvme.cli.digest")
    monkeypatch.setattr(digest_module, "discover", lambda source, limiter=None: found)

    calls: list[str] = []

    def fake_fetch(self, url: str) -> JobPosting:
        calls.append(url)
        return JobPosting(
            url=url,
            title="Data Engineer",
            company="Acme",
            description="Build Python data systems.",
        )

    monkeypatch.setattr(digest_module.Fetcher, "fetch", fake_fetch)
    first = runner.invoke(app, ["digest", "--config", str(config_path)])
    assert first.exit_code == 0, first.output
    assert "Data Engineer" in first.output
    assert calls == ["https://x.test/good"]
    assert len(list((tmp_path / "jobs").glob("*.md"))) == 1

    second = runner.invoke(app, ["digest", "--config", str(config_path)])
    assert second.exit_code == 0, second.output
    assert "0 new, 2 already seen" in second.output
    assert calls == ["https://x.test/good"]


def test_configured_detail_cap_leaves_excess_jobs_queued(
    tmp_path: Path, monkeypatch
) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    config_path = tmp_path / "cvme.toml"
    config_path.write_text(
        config_path.read_text().replace(
            "max_detail_requests_per_run = 10", "max_detail_requests_per_run = 1"
        )
        + '\n[[search.sources]]\nsite = "linkedin"\nquery = "engineer"\n'
    )
    found = [
        DiscoveredJob(f"https://x.test/{number}", "linkedin", "Engineer", "Acme")
        for number in range(2)
    ]
    digest_module = importlib.import_module("cvme.cli.digest")
    monkeypatch.setattr(digest_module, "discover", lambda source, limiter=None: found)
    calls: list[str] = []

    def fake_fetch(self, url: str) -> JobPosting:
        calls.append(url)
        return JobPosting(url=url, title="Engineer", company="Acme", description="d")

    monkeypatch.setattr(digest_module.Fetcher, "fetch", fake_fetch)
    result = runner.invoke(app, ["digest", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "detail request limit reached (1)" in result.output
    with JobStore(tmp_path / ".cvme" / "jobs.sqlite3") as store:
        assert len(store.pending()) == 1
