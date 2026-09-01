"""The tailoring flow end to end, driven by a stub agent.

A stub rather than a real agent: the point under test is the pipeline around
the agent -- prompt in, file out, verified, rendered -- and that has to hold
whatever writes the file.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME
from tests.conftest import FIXTURES

runner = CliRunner()

STUB = """
import re, sys, pathlib
prompt = pathlib.Path(sys.argv[1]).read_text()
out = pathlib.Path(re.search(r"Write the result to: `([^`]+)`", prompt).group(1))
pattern = r"# BASE DOCUMENT\\n\\n(.*?)\\n\\n---\\n"
base = re.search(pattern, prompt + "\\n\\n---\\n", re.S).group(1)
if "--invent" in sys.argv:
    base = base.replace("14 facilities", "22 facilities")
if "--nothing" in sys.argv:
    sys.exit(0)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(base)
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    runner.invoke(app, ["init", str(tmp_path)])
    for name in ("resume.md", "cover_letter.md"):
        shutil.copyfile(FIXTURES / name, tmp_path / "base" / name)
    for name in ("skills.md", "metrics.md"):
        shutil.copyfile(FIXTURES / "facts" / name, tmp_path / "facts" / name)

    stub = tmp_path / "stub.py"
    stub.write_text(STUB)
    with (tmp_path / CONFIG_NAME).open("a") as handle:
        for name, extra in (
            ("stub", ""),
            ("liar", '"--invent", '),
            ("lazy", '"--nothing", '),
        ):
            handle.write(
                f"\n[agents.{name}]\n"
                f'argv = ["{sys.executable}", "{stub}", "{{prompt_file}}", {extra}]\n'
            )

    jobs = tmp_path / "jobs"
    jobs.mkdir(exist_ok=True)
    (jobs / "northwind.md").write_text(
        "---\ntitle: Staff Data Engineer\ncompany: Northwind\n---\n\n"
        "# Staff Data Engineer\n\nOwn ingestion and transformation.\n"
    )
    return tmp_path


def run(project: Path, *args: str):
    return runner.invoke(
        app, ["tailor", "northwind", "--config", str(project / CONFIG_NAME), *args]
    )


def test_dry_run_prints_the_prompt_and_writes_nothing(project: Path) -> None:
    result = run(project, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "# JOB POSTING" in result.output
    assert "Own ingestion and transformation." in result.output
    assert not (project / "applications").exists()


def test_a_good_run_verifies_and_renders(project: Path) -> None:
    result = run(project, "--agent", "stub", "-d", "resume")
    assert result.exit_code == 0, result.output
    out = project / "applications" / "northwind"
    assert (out / "resume.md").is_file()
    assert (out / "resume.pdf").is_file()
    assert (out / "resume.prompt.md").is_file()


def test_an_invented_metric_blocks_the_pdf(project: Path) -> None:
    result = run(project, "--agent", "liar", "-d", "resume")
    assert result.exit_code == 3, result.output
    out = project / "applications" / "northwind"
    assert (out / "resume.md").is_file(), "the draft is kept for inspection"
    assert not (out / "resume.pdf").exists()
    assert "appears nowhere in the fact corpus" in result.output


def test_a_failed_run_removes_a_stale_pdf(project: Path) -> None:
    """Otherwise a rejected draft sits beside a PDF that could still be sent."""
    assert run(project, "--agent", "stub", "-d", "resume").exit_code == 0
    pdf = project / "applications" / "northwind" / "resume.pdf"
    assert pdf.is_file()

    result = run(project, "--agent", "liar", "-d", "resume")
    assert result.exit_code == 3
    assert not pdf.exists()
    assert "no longer matches" in result.output


def test_an_agent_that_writes_nothing_is_caught(project: Path) -> None:
    result = run(project, "--agent", "lazy", "-d", "resume")
    assert result.exit_code == 5, result.output
    assert "did not write" in result.output
    assert "run it by hand" in result.output


def test_the_none_agent_leaves_a_prompt_to_paste(project: Path) -> None:
    result = run(project, "--agent", "none", "-d", "resume")
    assert result.exit_code == 0, result.output
    prompt = project / "applications" / "northwind" / "resume.prompt.md"
    assert prompt.is_file()
    assert "# BASE DOCUMENT" in prompt.read_text()
    assert not (project / "applications" / "northwind" / "resume.md").exists()


def test_no_verify_lets_a_bad_document_through(project: Path) -> None:
    result = run(project, "--agent", "liar", "-d", "resume", "--no-verify")
    assert result.exit_code == 0, result.output
    assert (project / "applications" / "northwind" / "resume.pdf").is_file()


def test_both_documents_are_produced_by_default(project: Path) -> None:
    result = run(project, "--agent", "stub")
    assert result.exit_code == 0, result.output
    out = project / "applications" / "northwind"
    assert (out / "resume.pdf").is_file()
    assert (out / "cover_letter.pdf").is_file()


def test_an_unknown_document_lists_the_configured_ones(project: Path) -> None:
    result = run(project, "-d", "nonsense", "--dry-run")
    assert result.exit_code == 1
    assert "resume" in result.output


def test_a_missing_job_names_both_places_it_looked(project: Path) -> None:
    result = runner.invoke(
        app, ["tailor", "nope", "--config", str(project / CONFIG_NAME), "--dry-run"]
    )
    assert result.exit_code == 1
    assert "no job posting at" in result.output
