"""``cvme prep`` and ``cvme apps`` end to end, driven by a stub agent.

The stub stands in for whatever writes the documents, because the thing under
test is the pipeline around it: a posting in, a numbered directory out, with a
score that was computed and a version that was verified before it rendered.
"""

from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME
from tests.conftest import FIXTURES
from tests.test_tailor_cli import STUB

runner = CliRunner()

POSTING = """\
Northwind Health is hiring a Staff Data Engineer to own the lakehouse.

This is a fully remote role. Compensation: $150,000 - $190,000 per year.
We are a fast-paced team and we offer unlimited PTO. Paid parental leave.

Requirements:
- 5+ years building data pipelines
- Advanced Python and SQL
- Databricks and Airflow in production
- Kubernetes is a plus
- Rust experience preferred
"""

YEAR = str(date.today().year)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    runner.invoke(app, ["init", str(tmp_path)])
    for name in ("resume.md", "cover_letter.md"):
        shutil.copyfile(FIXTURES / name, tmp_path / "base" / name)
    for name in ("skills.md", "metrics.md"):
        shutil.copyfile(FIXTURES / "facts" / name, tmp_path / "facts" / name)

    stub = tmp_path / "stub.py"
    stub.write_text(STUB)
    config = tmp_path / CONFIG_NAME
    config.write_text(
        config.read_text().replace(
            "preferred_titles = []", 'preferred_titles = ["data engineer"]'
        )
    )
    with config.open("a") as handle:
        for name, extra in (("stub", ""), ("liar", '"--invent", ')):
            handle.write(
                f"\n[agents.{name}]\n"
                f'argv = ["{sys.executable}", "{stub}", "{{prompt_file}}", {extra}]\n'
            )

    (tmp_path / "posting.txt").write_text(POSTING)
    return tmp_path


def prep(project: Path, *args: str):
    return runner.invoke(
        app,
        [
            "prep",
            "https://example.com/jobs/1",
            "--config",
            str(project / CONFIG_NAME),
            "--text",
            str(project / "posting.txt"),
            "--title",
            "Staff Data Engineer",
            "--company",
            "Northwind Health",
            *args,
        ],
    )


def apps(project: Path, *args: str):
    return runner.invoke(app, ["apps", *args, "--config", str(project / CONFIG_NAME)])


def prepare(project: Path, name: str, company: str, body: str, *args: str):
    """A second posting in the same project, so a listing has rows to order."""
    path = project / f"{name}.txt"
    path.write_text(body)
    return runner.invoke(
        app,
        [
            "prep",
            f"https://example.com/jobs/{name}",
            "--config",
            str(project / CONFIG_NAME),
            "--text",
            str(path),
            "--title",
            "Data Engineer",
            "--company",
            company,
            "--agent",
            "stub",
            "-d",
            "resume",
            "--no-report",
            *args,
        ],
    )


def hunts(project: Path) -> Path:
    return project / "hunts" / YEAR


def test_fit_only_scores_the_posting_and_writes_nothing(project: Path) -> None:
    result = prep(project, "--fit-only")
    assert result.exit_code == 0, result.output
    assert "Fit " in result.output
    assert "**Answered.**" in result.output
    assert "rust" in result.output, "an unanswered requirement has to be visible"
    assert not (project / "hunts").exists()


def test_a_run_builds_the_whole_directory(project: Path) -> None:
    result = prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    assert result.exit_code == 0, result.output

    directories = list(hunts(project).iterdir())
    assert len(directories) == 1
    hunt = directories[0]
    assert hunt.name.startswith("01_northwind-health_staff-data-engineer_")

    assert (hunt / "posting.md").is_file()
    assert (hunt / "apps" / "cv1.md").is_file()
    assert (hunt / "apps" / "cv1.pdf").is_file()
    assert (hunt / "apps" / "index.md").is_file()
    assert "first version" in (hunt / "apps" / "index.md").read_text()


def test_the_exit_message_carries_the_fit(project: Path) -> None:
    result = prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    assert "fit " in result.output
    assert "/100" in result.output


def test_the_report_puts_the_computed_score_above_what_was_written(
    project: Path,
) -> None:
    result = prep(project, "--agent", "stub", "-d", "resume")
    assert result.exit_code == 0, result.output
    report = (next(iter(hunts(project).iterdir())) / "report.md").read_text()
    assert "**Fit " in report
    assert report.index("**Fit ") < report.index("---")


def test_a_second_run_adds_a_version_beside_the_first(project: Path) -> None:
    first = prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    assert first.exit_code == 0, first.output
    result = prep(
        project, "--agent", "stub", "-d", "resume", "--no-report", "--note", "shorter"
    )
    assert result.exit_code == 0, result.output

    assert len(list(hunts(project).iterdir())) == 1, "the same posting, one hunt"
    apps_dir = next(iter(hunts(project).iterdir())) / "apps"
    assert (apps_dir / "cv1.md").is_file()
    assert (apps_dir / "cv2.md").is_file()
    index = (apps_dir / "index.md").read_text()
    assert "| 1 |" in index and "| 2 |" in index
    assert "shorter" in index


def test_new_forces_a_separate_hunt(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    prep(project, "--agent", "stub", "-d", "resume", "--no-report", "--new")
    names = sorted(p.name for p in hunts(project).iterdir())
    assert len(names) == 2
    assert names[1].startswith("02_")


def test_an_invented_metric_stops_the_pdf_but_not_the_run(project: Path) -> None:
    """The gate holds, and the rest of the run is still what you fix from."""
    result = prep(project, "--agent", "liar", "-d", "resume")
    assert result.exit_code == 3, result.output

    hunt = next(iter(hunts(project).iterdir()))
    assert (hunt / "apps" / "cv1.md").is_file(), "the draft is kept for inspection"
    assert not (hunt / "apps" / "cv1.pdf").exists()
    assert (hunt / "report.md").is_file(), "the report is still worth having"
    assert (hunt / "apps" / "index.md").is_file()
    assert "did not pass verification" in result.output

    listed = apps(project, "list")
    assert "Northwind Health" in listed.output, "and it is still tracked"
    assert "cv1 (rejected)" in (hunt / "apps" / "index.md").read_text()


def test_the_none_agent_leaves_prompts_and_a_score(project: Path) -> None:
    result = prep(project, "--agent", "none", "-d", "resume")
    assert result.exit_code == 0, result.output
    hunt = next(iter(hunts(project).iterdir()))
    assert (hunt / ".prompts" / "resume.prompt.md").is_file()
    assert (hunt / ".prompts" / "report.prompt.md").is_file()
    assert "**Fit " in (hunt / "report.md").read_text()


def test_a_posting_already_captured_is_reused(project: Path) -> None:
    jobs = project / "jobs"
    jobs.mkdir(exist_ok=True)
    (jobs / "northwind.md").write_text(
        "---\ntitle: Staff Data Engineer\ncompany: Northwind Health\n"
        "url: https://example.com/jobs/1\n---\n\n"
        f"# Staff Data Engineer at Northwind Health\n\n{POSTING}"
    )
    result = runner.invoke(
        app,
        ["prep", "northwind", "--config", str(project / CONFIG_NAME), "--fit-only"],
    )
    assert result.exit_code == 0, result.output
    assert "Northwind Health" in result.output


def test_a_bare_word_that_is_not_a_posting_says_where_it_looked(project: Path) -> None:
    result = runner.invoke(
        app, ["prep", "nonsense", "--config", str(project / CONFIG_NAME), "--fit-only"]
    )
    assert result.exit_code == 1
    assert "not a URL, a file, or a posting" in result.output


def test_apps_lists_the_unsubmitted_by_fit(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    result = apps(project, "list")
    assert result.exit_code == 0, result.output
    assert "Northwind Health" in result.output
    assert "prepared" in result.output


def test_submitting_moves_the_directory_out_of_the_open_list(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    slug = next(iter(hunts(project).iterdir())).name

    result = apps(project, "submit", "northwind")
    assert result.exit_code == 0, result.output
    assert (hunts(project) / "applied" / slug / "posting.md").is_file()
    assert not (hunts(project) / slug).exists()

    assert "nothing prepared" in apps(project, "list").output
    assert "Northwind" in apps(project, "list", "--all").output


def test_status_refiles_and_records_the_note(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    result = apps(project, "status", "northwind", "interviewing", "--note", "call tue")
    assert result.exit_code == 0, result.output
    slug = next(iter((hunts(project) / "interviewing").iterdir())).name
    assert "call tue" in apps(project, "show", slug).output


def test_an_unknown_status_is_refused(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    result = apps(project, "status", "northwind", "ghosted")
    assert result.exit_code == 7
    assert "interviewing" in result.output


def test_an_unmatched_reference_says_so(project: Path) -> None:
    result = apps(project, "show", "nobody")
    assert result.exit_code == 7
    assert "no application matching" in result.output


def test_show_reports_every_version(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    result = apps(project, "show", "northwind")
    assert result.exit_code == 0, result.output
    assert "cv1" in result.output and "cv2" in result.output


GRIM = """\
Hypergrowth Labs wants a founding engineer, full stack, to move fast in a
scrappy startup with a work hard play hard culture. All hands on deck. 996.
We are like a family. $90,000 - $110,000 per year. Python and SQL required.
"""

CALM = """\
Steady State is hiring a Data Engineer. We work a four day work week with core
hours, no on call, 25 days of PTO, paid parental leave and a learning budget.
$200,000 - $240,000 per year. Python, SQL and dbt.
"""


def test_the_listing_carries_what_the_posting_said_about_pay_and_hours(
    project: Path,
) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    result = apps(project, "list", "--columns", "company,salary,wlb,where")
    assert result.exit_code == 0, result.output
    assert "$150k-190k" in result.output
    assert "remote" in result.output, "the posting says the role is remote"
    assert "busy" in result.output, "and that it is fast-paced with unlimited PTO"


def test_sorting_by_pay_and_by_hours_orders_differently(project: Path) -> None:
    assert prepare(project, "grim", "Hypergrowth Labs", GRIM).exit_code == 0
    assert prepare(project, "calm", "Steady State", CALM).exit_code == 0

    by_pay = apps(project, "list", "--sort", "salary").output
    assert by_pay.index("Steady State") < by_pay.index("Hypergrowth")

    by_hours = apps(project, "list", "--sort", "wlb").output
    assert by_hours.index("Steady State") < by_hours.index("Hypergrowth")

    worst_first = apps(project, "list", "--sort", "salary", "--reverse").output
    assert worst_first.index("Hypergrowth") < worst_first.index("Steady State")


def test_a_listing_says_which_order_it_is_in(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    assert "by salary" in apps(project, "list", "--sort", "salary").output


def test_columns_are_chosen_by_name(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    result = apps(project, "list", "--columns", "company,salary")
    assert "Northwind Health" in result.output
    assert "$150k-190k" in result.output
    assert "status" not in result.output, "a column not asked for is not shown"


def test_an_unknown_sort_or_column_lists_what_was_available(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    sort = apps(project, "list", "--sort", "vibes")
    assert sort.exit_code == 1
    assert "unknown sort 'vibes'" in sort.output and "salary" in sort.output
    columns = apps(project, "list", "--columns", "fit,vibes")
    assert columns.exit_code == 1
    assert "unknown column vibes" in columns.output


def test_show_gives_the_working_behind_the_work_life_score(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    result = apps(project, "show", "northwind")
    assert result.exit_code == 0, result.output
    assert "unlimited pto" in result.output
    assert "no accrued balance" in result.output, "a signal explains itself"
    assert "parental leave" in result.output


def test_rescan_rereads_the_postings_without_touching_the_fit(project: Path) -> None:
    prep(project, "--agent", "stub", "-d", "resume", "--no-report")
    before = apps(project, "list").output
    config = project / CONFIG_NAME
    config.write_text(
        config.read_text().replace(
            "[culture.extra_costs]", '[culture.extra_costs]\n"lakehouse" = 40'
        )
    )

    result = apps(project, "rescan")
    assert result.exit_code == 0, result.output
    assert "re-read 1 posting" in result.output

    after = apps(project, "list").output
    assert "grind" in after and "grind" not in before
    assert "89 strong" in after or after.count("strong") == before.count("strong")


def test_the_report_carries_the_pay_and_the_hours_it_read(project: Path) -> None:
    result = prep(project, "--agent", "none", "-d", "resume")
    assert result.exit_code == 0, result.output
    report = (next(iter(hunts(project).iterdir())) / "report.md").read_text()
    assert "**Pay** $150k-190k" in report
    assert "**Work-life " in report
    assert "unlimited pto" in report
