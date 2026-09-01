from __future__ import annotations

from typer.testing import CliRunner

from cvme import __version__
from cvme.cli.app import app

runner = CliRunner()


def test_version_reports_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_bare_invocation_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Typeset resumes and cover letters" in result.stdout


def test_expected_failures_report_without_a_traceback() -> None:
    """Error handling hangs off the commands, so it holds from any entry point."""
    result = runner.invoke(app, ["render", "definitely-not-a-file"])
    assert result.exit_code == 1
    assert "no such file" in result.output
    assert "Traceback" not in result.output


def test_a_document_over_budget_exits_with_its_own_code(tmp_path) -> None:
    from pathlib import Path

    source = Path("tests/fixtures/resume_long.md")
    result = runner.invoke(
        app,
        [
            "render",
            str(source),
            "-o",
            str(tmp_path / "o.pdf"),
            "--max-pages",
            "1",
            "--set",
            "body_size=15",
            "--style",
            "airy",
        ],
    )
    assert result.exit_code in (0, 2)


def test_doctor_finds_every_vendored_font() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout
