from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME
from tests.conftest import FIXTURES

runner = CliRunner()
JOBS = FIXTURES / "jobs"


def test_add_from_a_saved_page(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "job",
            "add",
            "--html",
            str(JOBS / "jsonld_page.html"),
            "--url",
            "https://example.test/j/1",
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    written = list(tmp_path.glob("*.md"))
    assert len(written) == 1
    assert "Staff Data Engineer" in written[0].read_text()


def test_add_from_stdin_with_supplied_title(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "job",
            "add",
            "--stdin",
            "--url",
            "https://x.test/1",
            "--title",
            "Data Engineer",
            "--company",
            "Acme",
            "--out",
            str(tmp_path),
        ],
        input="We need someone to own the pipeline.\n",
    )
    assert result.exit_code == 0, result.output
    text = next(tmp_path.glob("*.md")).read_text()
    assert "title: Data Engineer" in text
    assert "own the pipeline" in text


def test_exactly_one_input_is_required(tmp_path: Path) -> None:
    result = runner.invoke(app, ["job", "add", "--out", str(tmp_path)])
    assert result.exit_code == 1
    assert "exactly one" in result.output


def test_an_empty_description_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["job", "add", "--stdin", "--out", str(tmp_path)], input="   \n"
    )
    assert result.exit_code == 1
    assert "no description" in result.output


def test_incomplete_postings_say_what_to_fill_in(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["job", "add", "--stdin", "--out", str(tmp_path)], input="Some text.\n"
    )
    assert result.exit_code == 0, result.output
    assert "incomplete" in result.output
    assert "title" in result.output


def test_stdout_mode_writes_no_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["job", "add", "--stdin", "--stdout", "--out", str(tmp_path)],
        input="A description.\n",
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith("---")
    assert list(tmp_path.glob("*.md")) == []


def test_jobs_land_in_the_configured_directory(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(
        app,
        [
            "job",
            "add",
            "--stdin",
            "--url",
            "https://x.test/1",
            "--title",
            "Engineer",
            "--company",
            "Acme",
            "--config",
            str(tmp_path / CONFIG_NAME),
        ],
        input="A description.\n",
    )
    assert result.exit_code == 0, result.output
    assert list((tmp_path / "jobs").glob("*.md"))
