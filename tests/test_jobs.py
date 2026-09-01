"""Capturing job postings.

Everything here runs against recorded fixtures and a mock transport. The live
tiers cannot be exercised from an environment with no route to the sites, and
the parsers are pure functions over saved input anyway, which is the point of
keeping the fetch and the parse apart.
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

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=fixture("greenhouse.json"))

    fetcher = _fetcher(tmp_path, handler)
    fetcher.fetch(GREENHOUSE_URL)
    fetcher.fetch(GREENHOUSE_URL)
    assert len(calls) == 1

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
