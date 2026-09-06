"""``cvme linkedin`` end to end."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME
from cvme.linkedin import state as sync_state
from tests.test_linkedin_audit import POSITION_ROWS as EXPORT_POSITIONS
from tests.test_linkedin_audit import SOURCE as EXPORT_SOURCE
from tests.test_linkedin_audit import write_export

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


@pytest.fixture
def audited(project: Path) -> Path:
    """A project whose resume is the one the export fixtures were built from."""
    (project / "base" / "resume.md").write_text(EXPORT_SOURCE, encoding="utf-8")
    return project


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


def test_check_passes_when_the_export_matches(audited: Path) -> None:
    write_export(audited / "export")
    result = run(audited, "check", str(audited / "export"))
    assert result.exit_code == 0, result.output
    assert "the profile matches your documents" in result.output


def test_check_fails_on_drift_and_says_what_to_run(audited: Path) -> None:
    write_export(audited / "export", Skills=[["Name"]])
    result = run(audited, "check", str(audited / "export"))
    assert result.exit_code == 9
    assert "missing skills: Python, SQL" in result.output
    assert "cvme linkedin sync" in result.output


def test_check_does_not_fail_on_an_entry_only_linkedin_has(audited: Path) -> None:
    extra = [
        *EXPORT_POSITIONS,
        ["Harbor Coffee", "Barista", "Pulled shots", "", "Sep 2016", "May 2018"],
    ]
    write_export(audited / "export", Positions=extra)
    assert run(audited, "check", str(audited / "export")).exit_code == 0
    strict = run(audited, "check", str(audited / "export"), "--strict")
    assert strict.exit_code == 9
    assert "extra   position 'Barista @ Harbor Coffee'" in strict.output


def test_check_record_grounds_the_state_in_the_export(audited: Path) -> None:
    """The recorded state is evidence, not a promise that a paste happened."""
    write_export(audited / "export", Skills=[["Name"]])
    run(audited, "check", str(audited / "export"), "--record")
    assert sync_state.load(audited).recorded
    # What was already right is settled; only the skills remain outstanding.
    assert run(audited, "diff").output.strip().splitlines() == [
        "add skill 'Python'",
        "add skill 'SQL'",
    ]


def test_check_record_does_not_import_an_entry_cvme_does_not_manage(
    audited: Path,
) -> None:
    extra = [
        *EXPORT_POSITIONS,
        ["Harbor Coffee", "Barista", "Pulled shots", "", "Sep 2016", "May 2018"],
    ]
    write_export(audited / "export", Positions=extra)
    run(audited, "check", str(audited / "export"), "--record")
    assert "Barista" not in run(audited, "diff").output, (
        "a standing instruction to delete a job you meant to keep is worse "
        "than not tracking it"
    )


def test_check_record_under_strict_does_import_it(audited: Path) -> None:
    extra = [
        *EXPORT_POSITIONS,
        ["Harbor Coffee", "Barista", "Pulled shots", "", "Sep 2016", "May 2018"],
    ]
    write_export(audited / "export", Positions=extra)
    run(audited, "check", str(audited / "export"), "--record", "--strict")
    assert "remove position 'Barista @ Harbor Coffee'" in run(audited, "diff").output


def test_check_reports_an_unreadable_export_plainly(project: Path) -> None:
    result = run(project, "check", str(project / "nowhere"))
    assert result.exit_code == 10
    # Matched past the wrap: rich hard-wraps the message to the terminal width.
    assert "such file or directory" in result.output
