from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from cvme.cli.app import app

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"


def project(tmp_path: Path) -> Path:
    shutil.copy(FIXTURES / "resume.md", tmp_path / "base.md")
    (tmp_path / "cvme.toml").write_text(
        '[documents.base]\npath = "base.md"\ntemplate = "resume"\n',
        encoding="utf-8",
    )
    return tmp_path / "cvme.toml"


def test_send_names_one_copy_per_role(tmp_path: Path) -> None:
    config = project(tmp_path)
    result = runner.invoke(
        app,
        [
            "send",
            "Data Engineer",
            "Sr. Data Engineer, Platform",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    out = tmp_path / "send"
    assert (out / "morgan_avery_data_engineer.pdf").is_file()
    assert (out / "morgan_avery_senior_data_engineer.pdf").is_file()


def test_send_refuses_titles_that_collide_after_normalisation(tmp_path: Path) -> None:
    config = project(tmp_path)
    result = runner.invoke(
        app,
        [
            "send",
            "Senior Data Engineer",
            "Sr. Data Engineer III",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 1
    # The error console wraps, so match on the parts rather than the line.
    assert "both name" in result.output
    assert "morgan_avery_senior_data_engineer.pdf" in result.output
    assert not (tmp_path / "send").exists()


def test_send_writes_the_markdown_when_asked(tmp_path: Path) -> None:
    config = project(tmp_path)
    result = runner.invoke(
        app,
        [
            "send",
            "Data Engineer",
            "--md",
            "--dir",
            str(tmp_path / "outbox"),
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    copy = tmp_path / "outbox" / "morgan_avery_data_engineer.md"
    assert copy.read_text(encoding="utf-8") == (tmp_path / "base.md").read_text(
        encoding="utf-8"
    )
