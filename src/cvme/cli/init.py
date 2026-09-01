"""``cvme init`` -- scaffold a documents directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer

from cvme.config import CONFIG_NAME
from cvme.errors import ConfigError

STARTERS = Path(__file__).parent.parent / "starters"


def init(
    directory: Annotated[
        Path, typer.Argument(help="Where to scaffold. Defaults to the current dir.")
    ] = Path("."),
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite files that already exist.")
    ] = False,
) -> None:
    """Create cvme.toml, base documents, and a fact corpus to fill in."""
    if (directory / CONFIG_NAME).exists() and not force:
        raise ConfigError(
            f"{directory / CONFIG_NAME} already exists; pass --force to overwrite"
        )

    written: list[Path] = []
    for source in sorted(p for p in STARTERS.rglob("*") if p.is_file()):
        target = directory / source.relative_to(STARTERS)
        if target.exists() and not force:
            typer.echo(f"  skipped {target} (exists)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        written.append(target)

    for path in written:
        typer.echo(f"  created {path}")
    typer.echo(
        f"\nEdit {directory / 'base' / 'resume.md'}, then:\n  cvme render resume"
    )
