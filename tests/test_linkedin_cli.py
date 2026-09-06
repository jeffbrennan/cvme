"""``cvme linkedin`` end to end."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME, load_config
from cvme.linkedin import state as sync_state
from cvme.linkedin import sync
from cvme.linkedin.client import Client

runner = CliRunner()

RESUME = """\
---
name: Morgan Avery
headline: Staff Data Engineer | Streaming platforms
---

## Summary

Six years across the data lifecycle.

## Experience

### Staff Data Engineer @ Northwind Analytics | Jul 2023 – Present

- Own ingestion for several hundred tenants

## Skills

- **Languages**: Python, SQL
"""

CONFIG = """\
[documents.resume]
path = "base/resume.md"
"""


@pytest.fixture(autouse=True)
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVME_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("CVME_LINKEDIN_CLIENT_ID", raising=False)
    monkeypatch.delenv("CVME_LINKEDIN_CLIENT_SECRET", raising=False)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    (root / "base").mkdir(parents=True)
    (root / "base" / "resume.md").write_text(RESUME, encoding="utf-8")
    (root / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    return root


def run(project: Path, *args: str):
    return runner.invoke(
        app, ["linkedin", *args, "--config", str(project / CONFIG_NAME)]
    )


def test_diff_lists_the_first_run_as_all_new(project: Path) -> None:
    result = run(project, "diff")
    assert result.exit_code == 0, result.output
    assert "set headline" in result.output
    assert "add position 'Staff Data Engineer @ Northwind Analytics'" in result.output


def test_sync_writes_a_changeset_without_touching_the_state(project: Path) -> None:
    result = run(project, "sync")
    assert result.exit_code == 0, result.output
    written = project / "out" / "linkedin-changeset.md"
    assert written.is_file()
    assert "Staff Data Engineer" in written.read_text()
    assert not sync_state.load(project).recorded, (
        "cvme cannot know a changeset was pasted in, so it does not claim so"
    )


def test_the_changeset_says_where_each_edit_goes(project: Path) -> None:
    run(project, "sync")
    text = (project / "out" / "linkedin-changeset.md").read_text()
    assert "*Edit intro > Headline*" in text
    assert "*Experience > the role > Edit*" in text
    assert "cvme linkedin record" in text


def test_record_then_diff_is_empty(project: Path) -> None:
    assert run(project, "record").exit_code == 0
    assert "no changes" in run(project, "diff").output
    assert "nothing to sync" in run(project, "sync").output


def test_an_edit_after_recording_is_the_only_thing_reported(project: Path) -> None:
    run(project, "record")
    source = project / "base" / "resume.md"
    source.write_text(RESUME.replace("several hundred", "a thousand"), encoding="utf-8")
    output = run(project, "diff").output
    assert (
        output.strip() == "update position 'Staff Data Engineer @ Northwind Analytics'"
    )


def test_reset_offers_the_whole_profile_again(project: Path) -> None:
    run(project, "record")
    assert "cleared" in run(project, "reset").output
    assert "set headline" in run(project, "diff").output


def test_an_over_long_field_refuses_the_sync(project: Path) -> None:
    source = project / "base" / "resume.md"
    source.write_text(
        RESUME.replace(
            "- Own ingestion for several hundred tenants", f"- {'x' * 2100}"
        ),
        encoding="utf-8",
    )
    result = run(project, "sync")
    assert result.exit_code != 0
    assert "over the limit" in result.output
    assert not (project / "out" / "linkedin-changeset.md").exists()


def test_an_unmapped_section_is_warned_about_not_silently_dropped(
    project: Path,
) -> None:
    source = project / "base" / "resume.md"
    source.write_text(RESUME + "\n## Projects\n\n- cvme\n", encoding="utf-8")
    assert "no LinkedIn field for: Projects" in run(project, "diff").output


def test_status_reports_without_credentials(project: Path) -> None:
    result = run(project, "status")
    assert result.exit_code == 0, result.output
    assert "client_secret  not set" in result.output
    assert "last sync    never" in result.output
    assert "overlay      none" in result.output


def test_an_unknown_transport_is_rejected(project: Path) -> None:
    result = run(project, "sync", "--transport", "carrier-pigeon")
    assert result.exit_code != 0
    assert "unknown transport" in result.output


def test_the_api_transport_needs_a_login(project: Path) -> None:
    result = run(project, "sync", "--transport", "api")
    assert result.exit_code != 0
    assert "not logged in" in result.output


def test_an_api_sync_pushes_each_change_and_records_the_ids(project: Path) -> None:
    """The whole API path, against a transport that answers like LinkedIn."""
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(201, headers={"x-linkedin-id": f"urn:{len(calls)}"})

    config = load_config(project / CONFIG_NAME)
    plan = sync.build(config)
    client = Client(
        "tok", person_id="ME", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    ids = sync.apply_api(plan, client, {})
    sync.record(config, plan, transport="api", ids=ids)

    assert ("POST", "/v2/people/id=ME") in calls, "headline and summary in one patch"
    assert ("POST", "/v2/people/id=ME/positions") in calls
    assert ("POST", "/v2/people/id=ME/skills") in calls
    assert len(ids) == len(plan.changeset.of("position", "education", "skill"))
    assert not sync.build(config).changeset, (
        "a recorded push leaves nothing outstanding"
    )


def test_an_api_update_targets_the_recorded_id(project: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, headers={"x-linkedin-id": "urn:new"})

    config = load_config(project / CONFIG_NAME)
    first = sync.build(config)
    known = {change.key: "urn:known" for change in first.changeset.of("position")}
    sync.record(config, first, transport="api", ids=known)

    source = project / "base" / "resume.md"
    source.write_text(RESUME.replace("several hundred", "a thousand"), encoding="utf-8")
    client = Client(
        "tok", person_id="ME", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    sync.apply_api(sync.build(config), client, known)
    assert "/v2/people/id=ME/positions/urn:known" in seen


def test_an_overlay_beside_the_resume_needs_no_configuration(project: Path) -> None:
    (project / "base" / "linkedin.md").write_text(
        "## Experience\n\n"
        "### Staff Data Engineer @ Northwind Analytics | Jul 2023 – Present\n\n"
        "- The long-form bullet the page had no room for\n",
        encoding="utf-8",
    )
    assert "linkedin.md" in run(project, "status").output
    run(project, "sync")
    text = (project / "out" / "linkedin-changeset.md").read_text()
    assert "no room for" in text
