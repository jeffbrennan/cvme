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


def test_doctor_finds_every_vendored_font() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout
