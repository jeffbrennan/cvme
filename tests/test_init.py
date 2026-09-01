"""``cvme init`` scaffolding."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME, load_config

runner = CliRunner()


def test_init_scaffolds_a_working_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    for expected in (
        CONFIG_NAME,
        "base/resume.md",
        "base/cover_letter.md",
        "facts/skills.md",
        "facts/metrics.md",
    ):
        assert (tmp_path / expected).is_file(), expected


def test_scaffolded_documents_render(tmp_path: Path) -> None:
    """The starters must be valid input, not just plausible-looking text."""
    runner.invoke(app, ["init", str(tmp_path)])
    config = load_config(tmp_path / CONFIG_NAME)
    for name in config.documents:
        result = runner.invoke(
            app, ["render", name, "--config", str(tmp_path / CONFIG_NAME)]
        )
        assert result.exit_code == 0, result.stdout
        assert (config.project.output_dir / f"{name}.pdf").is_file()


def test_init_refuses_to_clobber(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code != 0
    # `output` rather than `stdout`: errors are written to stderr.
    assert "--force" in result.output


def test_force_overwrites(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    (tmp_path / "base" / "resume.md").write_text("clobbered")
    runner.invoke(app, ["init", str(tmp_path), "--force"])
    assert (tmp_path / "base" / "resume.md").read_text() != "clobbered"
