"""Project configuration discovery and layering."""

from __future__ import annotations

from pathlib import Path

import pytest

from cvme.config import CONFIG_NAME, find_config, load_config
from cvme.errors import ConfigError

SAMPLE = """
[project]
output_dir = "build"
facts = ["facts/skills.md"]

[documents.resume]
path = "base/resume.md"
template = "resume"
style = "compact"

[documents.resume.overrides]
max_pages = 2
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / CONFIG_NAME).write_text(SAMPLE)
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "resume.md").write_text("## Skills\n\n- a\n")
    return tmp_path


def test_config_is_found_by_walking_up(project: Path) -> None:
    deep = project / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert find_config(deep) == project / CONFIG_NAME


def test_missing_config_is_not_an_error(tmp_path: Path) -> None:
    assert find_config(tmp_path) is None


def test_paths_resolve_against_the_config_not_the_cwd(project: Path) -> None:
    config = load_config(project / CONFIG_NAME)
    assert config.documents["resume"].path == project / "base" / "resume.md"
    assert config.project.output_dir == project / "build"
    assert config.project.facts == [project / "facts" / "skills.md"]
    assert config.search.database == project / ".cvme" / "jobs.sqlite3"


def test_absolute_paths_are_left_alone(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text(
        f'[documents.r]\npath = "{tmp_path / "x.md"}"\n'
    )
    config = load_config(tmp_path / CONFIG_NAME)
    assert config.documents["r"].path == tmp_path / "x.md"


def test_document_overrides_are_carried(project: Path) -> None:
    document = load_config(project / CONFIG_NAME).documents["resume"]
    assert document.style == "compact"
    assert document.overrides == {"max_pages": 2}


def test_unknown_document_lists_what_exists(project: Path) -> None:
    config = load_config(project / CONFIG_NAME)
    with pytest.raises(ConfigError, match="resume"):
        config.document("nope")


def test_sole_document_is_used_when_unambiguous(project: Path) -> None:
    name, _ = load_config(project / CONFIG_NAME).sole_document()
    assert name == "resume"


def test_several_documents_require_a_name(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text(
        '[documents.a]\npath = "a.md"\n[documents.b]\npath = "b.md"\n'
    )
    with pytest.raises(ConfigError, match="name a document"):
        load_config(tmp_path / CONFIG_NAME).sole_document()


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text("[project]\nnonsense = 1\n")
    with pytest.raises(ConfigError, match="nonsense"):
        load_config(tmp_path / CONFIG_NAME)


def test_malformed_toml_names_the_file(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text("[project\n")
    with pytest.raises(ConfigError, match=CONFIG_NAME):
        load_config(tmp_path / CONFIG_NAME)
