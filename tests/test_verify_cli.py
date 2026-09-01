from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME

runner = CliRunner()
FACTS = [
    "--facts",
    "tests/fixtures/facts/skills.md",
    "--facts",
    "tests/fixtures/facts/metrics.md",
]


def test_clean_document_exits_zero() -> None:
    result = runner.invoke(app, ["verify", "tests/fixtures/resume.md", *FACTS])
    assert result.exit_code == 0, result.output
    assert "ok" in result.output


def test_failure_uses_its_own_exit_code() -> None:
    """3, so a script can tell verification from a bad file or a page overflow."""
    result = runner.invoke(app, ["verify", "tests/fixtures/resume_bad.md", *FACTS])
    assert result.exit_code == 3
    assert "appears nowhere in the fact corpus" in result.output


def test_json_mode_emits_parseable_output() -> None:
    import json

    result = runner.invoke(
        app, ["verify", "tests/fixtures/resume_bad.md", *FACTS, "--json"]
    )
    payload = json.loads(result.output.split("error:")[0])
    assert payload["findings"]


def test_verify_uses_the_configured_corpus(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(
        app, ["verify", "resume", "--config", str(tmp_path / CONFIG_NAME)]
    )
    assert result.exit_code == 0, result.output


def test_without_a_target_every_configured_document_is_checked(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["verify", "--config", str(tmp_path / CONFIG_NAME)])
    assert result.exit_code == 0, result.output
    assert result.output.count("ok") >= 2
