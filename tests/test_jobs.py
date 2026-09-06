"""Capturing job postings.

Everything here runs against recorded fixtures and a mock transport, including
job-bearing fragments from two LinkedIn postings verified live on 2026-09-05.
Keeping fetch and parse apart makes those regressions reproducible offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from cvme.jobs import ats, jsonld, sources
from cvme.jobs.cache import Cache
from cvme.jobs.models import JobPosting
from cvme.jobs.sources import Fetcher, FetchError
from cvme.jobs.writer import to_markdown, write
from tests.conftest import FIXTURES

JOBS = FIXTURES / "jobs"

GREENHOUSE_URL = "https://boards.greenhouse.io/northwind/jobs/4012345"
LEVER_URL = "https://jobs.lever.co/northwind/0d1b2c3d-4e5f-6789-abcd-ef0123456789"
ASHBY_URL = "https://jobs.ashbyhq.com/northwind/11112222333344445555666677778888"


def fixture(name: str) -> str:
    return (JOBS / name).read_text()


def payload(name: str) -> dict:
    return json.loads(fixture(name))


# --- URL detection --------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "provider", "org"),
    [
        (GREENHOUSE_URL, "greenhouse", "northwind"),
        ("https://job-boards.greenhouse.io/acme/jobs/77", "greenhouse", "acme"),
        (LEVER_URL, "lever", "northwind"),
        (ASHBY_URL, "ashby", "northwind"),
    ],
)
def test_ats_urls_are_recognised(url: str, provider: str, org: str) -> None:
    match = ats.detect(url)
    assert match is not None
    assert (match.provider, match.org) == (provider, org)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/4012345",
        "https://www.indeed.com/viewjob?jk=abc123",
        "https://example.test/careers/1",
    ],
)
def test_non_ats_urls_are_not_claimed(url: str) -> None:
    assert ats.detect(url) is None


# --- ATS parsing ----------------------------------------------------------


def test_greenhouse_unescapes_its_html_entities() -> None:
    match = ats.detect(GREENHOUSE_URL)
    assert match is not None
    posting = ats.parse(payload("greenhouse.json"), match, GREENHOUSE_URL)
    assert posting.title == "Staff Data Engineer"
    assert posting.company == "Northwind Analytics"
    assert posting.location == "Boston, MA"
    assert "**Staff Data Engineer**" in posting.description
    assert "&lt;" not in posting.description


def test_lever_joins_its_split_description() -> None:
    """Lever splits the body over `description`, `lists` and `additional`."""
    match = ats.detect(LEVER_URL)
    assert match is not None
    posting = ats.parse(payload("lever.json"), match, LEVER_URL)
    for expected in (
        "telemetry platform",
        "What you will do",
        "Own ingestion",
        "equal opportunity",
    ):
        assert expected in posting.description
    assert posting.employment_type == "Full-time"


def test_ashby_selects_the_requested_job_from_the_whole_board() -> None:
    """Ashby serves every posting at once; picking the first would be wrong."""
    match = ats.detect(ASHBY_URL)
    assert match is not None
    posting = ats.parse(payload("ashby.json"), match, ASHBY_URL)
    assert posting.title == "Staff Data Engineer"
    assert posting.remote is False


def test_ashby_refuses_to_substitute_a_different_job() -> None:
    match = ats.AtsMatch("ashby", "northwind", "missing-id")
    with pytest.raises(ats.AtsParseError, match="did not contain job missing-id"):
        ats.parse(payload("ashby.json"), match, ASHBY_URL)


# --- JSON-LD --------------------------------------------------------------


def test_jsonld_is_found_inside_a_graph() -> None:
    posting = jsonld.extract(fixture("jsonld_page.html"), "https://example.test/j/1")
    assert posting is not None
    assert posting.title == "Staff Data Engineer"
    assert posting.company == "Northwind Analytics"
    assert posting.location == "Boston, MA, US"
    assert posting.remote is True
    assert posting.salary == "USD 180000-220000 per year"
    assert posting.posted == "2026-08-14"


def test_a_broken_jsonld_block_does_not_stop_the_scan() -> None:
    """Pages ship invalid JSON-LD alongside valid blocks more often than not."""
    assert jsonld.extract(fixture("jsonld_page.html"), "u") is not None


def test_a_page_without_jsonld_yields_nothing() -> None:
    assert jsonld.extract(fixture("plain_page.html"), "u") is None


# --- manual paths ---------------------------------------------------------


def test_saved_page_prefers_jsonld() -> None:
    posting = sources.from_html(fixture("jsonld_page.html"), "https://example.test/j/1")
    assert posting.tier == "manual:jsonld"
    assert posting.title == "Staff Data Engineer"


def test_saved_page_without_jsonld_falls_back_to_the_densest_block() -> None:
    posting = sources.from_html(fixture("plain_page.html"), "https://example.test/j/1")
    assert posting.tier == "manual:html"
    assert "own ingestion" in posting.description.lower()
    assert "Similar job" not in posting.description, "sidebar link soup leaked in"
    assert "Northwind" in posting.description


def test_pasted_text_is_taken_as_given() -> None:
    posting = sources.from_text("  Just the description.  ", "https://x.test/1")
    assert posting.description == "Just the description."
    assert posting.tier == "manual:text"


# --- the ladder -----------------------------------------------------------


def _fetcher(tmp_path: Path, handler) -> Fetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Fetcher(root=tmp_path, client=client)


def test_an_ats_url_goes_straight_to_the_api(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=fixture("greenhouse.json"))

    posting = _fetcher(tmp_path, handler).fetch(GREENHOUSE_URL)
    assert posting.tier == "ats"
    assert seen == ["https://boards-api.greenhouse.io/v1/boards/northwind/jobs/4012345"]


def test_a_generic_url_falls_through_to_jsonld(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=fixture("jsonld_page.html"))

    posting = _fetcher(tmp_path, handler).fetch("https://example.test/careers/1")
    assert posting.tier == "jsonld"
    assert posting.source == "generic"


@pytest.mark.parametrize(
    ("url", "page", "title", "company", "description"),
    [
        (
            "https://www.linkedin.com/jobs/view/4012345",
            "linkedin_page.html",
            "Principal Platform Engineer",
            "Northwind Systems",
            "Own developer infrastructure",
        ),
        (
            "https://www.indeed.com/viewjob?jk=abc123",
            "indeed_page.html",
            "Senior Data Engineer",
            "Contoso Analytics",
            "Python and SQL",
        ),
    ],
)
def test_job_sites_fall_through_to_public_html(
    tmp_path: Path,
    url: str,
    page: str,
    title: str,
    company: str,
    description: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=fixture(page))

    posting = _fetcher(tmp_path, handler).fetch(url)
    assert posting.tier == "site:html"
    assert posting.title == title
    assert posting.company == company
    assert description in posting.description


def test_a_page_with_nothing_usable_explains_what_to_do_instead(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=fixture("plain_page.html"))

    url = "https://www.linkedin.com/jobs/view/4012345"
    with pytest.raises(FetchError) as excinfo:
        _fetcher(tmp_path, handler).fetch(url)
    message = str(excinfo.value)
    assert "cvme job add --html" in message
    assert url in message


def test_an_http_error_is_reported_not_raised_raw(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(FetchError, match="could not fetch"):
        _fetcher(tmp_path, handler).fetch("https://example.test/careers/1")


def test_the_second_fetch_is_served_from_cache(tmp_path: Path) -> None:
    calls: list[str] = []
    rate_checks: list[None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=fixture("greenhouse.json"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = Fetcher(
        root=tmp_path,
        client=client,
        before_request=lambda: rate_checks.append(None),
    )
    fetcher.fetch(GREENHOUSE_URL)
    fetcher.fetch(GREENHOUSE_URL)
    assert len(calls) == 1
    assert len(rate_checks) == 1, "cached reads must not wait on the limiter"

    match = ats.detect(GREENHOUSE_URL)
    assert match is not None
    assert Cache(tmp_path).path(match.api_url, ".json").is_file()


def test_no_cache_refetches(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=fixture("greenhouse.json"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    Fetcher(root=tmp_path, client=client).fetch(GREENHOUSE_URL)
    Fetcher(root=tmp_path, client=client, use_cache=False).fetch(GREENHOUSE_URL)
    assert len(calls) == 2


# --- output ---------------------------------------------------------------


def test_markdown_carries_frontmatter_and_body() -> None:
    match = ats.detect(GREENHOUSE_URL)
    assert match is not None
    text = to_markdown(ats.parse(payload("greenhouse.json"), match, GREENHOUSE_URL))
    assert text.startswith("---\n")
    assert "title: Staff Data Engineer" in text
    assert "# Staff Data Engineer at Northwind Analytics" in text


def test_empty_fields_are_left_out_of_frontmatter() -> None:
    text = to_markdown(JobPosting(url="u", description="d"))
    assert "location:" not in text
    assert "salary:" not in text


def test_the_slug_is_stable_and_readable() -> None:
    posting = JobPosting(
        url="https://x.test/1",
        title="Staff Data Engineer",
        company="Northwind Analytics",
    )
    assert posting.slug.startswith("northwind-analytics-staff-data-engineer-")
    assert posting.slug == posting.model_copy().slug


def test_different_urls_get_different_filenames() -> None:
    a = JobPosting(url="https://x.test/1", title="Engineer", company="Acme")
    b = JobPosting(url="https://x.test/2", title="Engineer", company="Acme")
    assert a.slug != b.slug


def test_missing_fields_are_reported_for_the_user_to_fill_in() -> None:
    assert set(JobPosting(url="u").missing()) == {"title", "company", "description"}
    complete = JobPosting(url="u", title="t", company="c", description="d")
    assert complete.missing() == []


def test_write_lands_in_the_jobs_directory(tmp_path: Path) -> None:
    posting = JobPosting(url="u", title="Engineer", company="Acme", description="d")
    path = write(posting, tmp_path / "jobs")
    assert path.parent.name == "jobs"
    assert path.read_text().startswith("---\n")


@pytest.mark.parametrize(
    ("job_id", "title", "company", "tier", "employment", "phrase"),
    [
        (
            "4453268982",
            "Data Engineer III - Digital and Technology Partners - Hybrid/Remote",
            "Mount Sinai Health System",
            "jsonld",
            "FULL_TIME",
            "150 E 42nd Street",
        ),
        (
            "4457172708",
            "Specialist Data Engineer",
            "Metropolitan Transportation Authority",
            "site:html",
            "Other",
            "$114,070 - $134,641",
        ),
    ],
)
def test_recorded_linkedin_postings(
    tmp_path: Path,
    job_id: str,
    title: str,
    company: str,
    tier: str,
    employment: str,
    phrase: str,
) -> None:
    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    html = fixture(f"linkedin_{job_id}.html")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=html)

    fetcher = _fetcher(tmp_path, handler)
    posting = fetcher.fetch(url)
    saved = sources.from_html(html, url)
    assert posting.tier == tier
    assert saved.tier == f"manual:{tier}"
    for captured in (posting, saved, fetcher.fetch(url)):
        assert captured.title == title
        assert captured.company == company
        assert captured.employment_type == employment
        assert captured.source == "linkedin"
        assert captured.location.startswith("New York, NY")
        assert captured.apply_url == url
        assert captured.missing() == []
        assert phrase in captured.description
        assert len(captured.description) > 5000
        assert "&lt;" not in captured.description
        assert "<br>" not in captured.description
        assert "Similar jobs and sign in" not in captured.description
    assert calls == [url]
    from cvme.jobs.writer import read

    assert read(write(posting, tmp_path)).description == posting.description


def test_title_only_jsonld_does_not_hide_the_html_description(tmp_path: Path) -> None:
    html = (
        '<script type="application/ld+json">'
        + json.dumps({"@type": "JobPosting", "title": "Incomplete metadata"})
        + "</script>"
        + fixture("linkedin_page.html")
    )
    fetcher = _fetcher(tmp_path, lambda _: httpx.Response(200, text=html))
    posting = fetcher.fetch("https://www.linkedin.com/jobs/view/123")
    assert posting.tier == "site:html"
    assert "Own developer infrastructure" in posting.description


def test_jsonld_preserves_escaped_examples_inside_real_html() -> None:
    posting = jsonld.from_dict(
        {"description": "<p>Work with &lt;service&gt; and R&amp;D.</p>"}, "u"
    )
    assert "<service>" in posting.description
    assert "R&D" in posting.description


@pytest.mark.parametrize(
    ("job_id", "salary", "bounds"),
    [
        ("4453268982", "$109000 - $163695 per year", (109000, 163695)),
        ("4457172708", "$114,070 - $134,641", (114070, 134641)),
    ],
)
def test_linkedin_salary_survives_capture_and_roundtrip(
    tmp_path: Path,
    job_id: str,
    salary: str,
    bounds: tuple[int, int],
) -> None:
    from cvme.hunt.pay import read as read_pay
    from cvme.jobs.writer import read

    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    html = fixture(f"linkedin_{job_id}.html")
    fetcher = _fetcher(tmp_path, lambda _: httpx.Response(200, text=html))
    for posting in (fetcher.fetch(url), sources.from_html(html, url)):
        assert posting.salary == salary
        stored = read(write(posting, tmp_path))
        pay = read_pay(stored.salary)
        assert (pay.low, pay.high) == bounds
        assert stored.salary == salary


def test_structured_salary_takes_precedence_over_description() -> None:
    posting = jsonld.from_dict(
        {
            "baseSalary": {
                "currency": "USD",
                "value": {"minValue": 180000, "maxValue": 220000, "unitText": "YEAR"},
            },
            "description": "Other roles pay $90,000 per year.",
        },
        "u",
    )
    assert posting.salary == "USD 180000-220000 per year"


def test_pasted_salary_preserves_hourly_period() -> None:
    assert sources.from_text("Salary: $72/hr", "u").salary == "$72 per hour"
    assert sources.from_text("We serve 10,000 patients per year", "u").salary == ""
