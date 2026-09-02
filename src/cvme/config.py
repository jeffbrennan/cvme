"""Project configuration.

``cvme.toml`` marks the root of a documents directory. It is discovered by
walking up from the working directory, so the CLI works from anywhere inside
a project, and every path it holds resolves relative to the file itself rather
than to the shell's cwd.

Style resolution is layered, later winning over earlier:

    packaged preset -> the document's `overrides` table -> --set on the CLI

``--style`` selects which preset that stack starts from.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from cvme.errors import ConfigError

CONFIG_NAME = "cvme.toml"


class DocumentConfig(BaseModel):
    """One renderable document."""

    model_config = {"extra": "forbid"}

    path: Path
    template: str = "resume"
    style: str = "standard"
    overrides: dict[str, Any] = Field(default_factory=dict)


class ProjectConfig(BaseModel):
    model_config = {"extra": "forbid"}

    output_dir: Path = Path("out")
    jobs_dir: Path = Path("jobs")
    applications_dir: Path = Path("applications")
    facts: list[Path] = Field(default_factory=list)


class GenerateConfig(BaseModel):
    """Knobs for the tailoring prompt."""

    model_config = {"extra": "forbid"}

    agent: str = "codex"
    min_bullets: int = 2
    max_bullets: int = 5
    max_bullet_words: int = 32


class SearchSourceConfig(BaseModel):
    """One repeatable search on a supported job board."""

    model_config = {"extra": "forbid"}

    site: Literal["linkedin", "indeed"]
    query: str
    location: str = ""
    pages: int = Field(default=1, ge=1, le=10)
    remote: bool = False
    posted_within_days: int | None = Field(default=None, ge=1, le=30)


class SearchConfig(BaseModel):
    """Discovery, filtering, and ranking preferences for ``cvme digest``."""

    model_config = {"extra": "forbid"}

    database: Path = Path(".cvme/jobs.sqlite3")
    sources: list[SearchSourceConfig] = Field(default_factory=list)
    blocked_companies: list[str] = Field(default_factory=list)
    preferred_titles: list[str] = Field(default_factory=list)
    excluded_titles: list[str] = Field(default_factory=list)
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_only: bool = False
    minimum_score: int = Field(default=0, ge=0)


class Config(BaseModel):
    """A loaded ``cvme.toml``, with every path made absolute."""

    model_config = {"extra": "forbid"}

    root: Path
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    documents: dict[str, DocumentConfig] = Field(default_factory=dict)
    generate: GenerateConfig = Field(default_factory=GenerateConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    #: Raw [agents.<name>] tables, layered over the packaged defaults at use.
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def document(self, name: str) -> DocumentConfig:
        if name not in self.documents:
            known = ", ".join(sorted(self.documents)) or "none configured"
            raise ConfigError(f"no document named '{name}' in {CONFIG_NAME}: {known}")
        return self.documents[name]

    def sole_document(self) -> tuple[str, DocumentConfig]:
        """The only configured document, when there is exactly one."""
        if len(self.documents) == 1:
            return next(iter(self.documents.items()))
        known = ", ".join(sorted(self.documents)) or "none configured"
        raise ConfigError(f"name a document to render: {known}")


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` looking for cvme.toml."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path) -> Config:
    """Load and validate a config file, resolving paths against its directory."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    root = path.parent
    try:
        config = Config(root=root, **data)
    except Exception as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    config.project.output_dir = _resolve(root, config.project.output_dir)
    config.project.jobs_dir = _resolve(root, config.project.jobs_dir)
    config.project.applications_dir = _resolve(root, config.project.applications_dir)
    config.project.facts = [_resolve(root, f) for f in config.project.facts]
    config.search.database = _resolve(root, config.search.database)
    for document in config.documents.values():
        document.path = _resolve(root, document.path)
    return config


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()
