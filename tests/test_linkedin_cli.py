"""``cvme linkedin`` end to end."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME
from cvme.linkedin import state as sync_state

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
    assert "last sync    never" in result.output
    assert "overlay      none" in result.output


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
