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
from typing import Any

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
    facts: list[Path] = Field(default_factory=list)


class Config(BaseModel):
    """A loaded ``cvme.toml``, with every path made absolute."""

    model_config = {"extra": "forbid"}

    root: Path
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    documents: dict[str, DocumentConfig] = Field(default_factory=dict)

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
    config.project.facts = [_resolve(root, f) for f in config.project.facts]
    for document in config.documents.values():
        document.path = _resolve(root, document.path)
    return config


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()
