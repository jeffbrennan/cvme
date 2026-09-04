"""``cvme apps`` -- what is prepared, what was sent, and what came back.

Two questions, and this exists to answer them. Which of the things I have
prepared have I not sent, best fit first, because that is the order to spend
an evening in. And where did the one I did send go, which is a matter of
moving its directory so that what is left at the top of the year is what is
still outstanding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from cvme.cli.errors import handled
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError, HuntError
from cvme.hunt import layout
from cvme.hunt.layout import OPEN, STATUSES
from cvme.hunt.store import Application, ApplicationStore

app = typer.Typer(
    name="apps",
    help="Track prepared applications.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

#: Fit bands, coloured so a listing can be read without reading the numbers.
_BANDS = {
    "strong": "green",
    "fair": "cyan",
    "thin": "yellow",
    "weak": "red",
    "blocked": "red",
}


def _config(config_path: Path | None) -> Config:
    found = config_path or find_config()
    if found is None:
        raise ConfigError("apps needs a project; run 'cvme init DIRECTORY' first")
    return load_config(found)


def _relative(config: Config, directory: str) -> str:
    try:
        return str(Path(directory).relative_to(config.root))
    except ValueError:
        return directory


def _table(config: Config, applications: list[Application], heading: str) -> Table:
    table = Table(title=heading, title_justify="left", header_style="bold")
    table.add_column("fit", justify="right", no_wrap=True)
    table.add_column("company", no_wrap=True)
    table.add_column("title")
    table.add_column("status", no_wrap=True)
    table.add_column("v", justify="right", no_wrap=True)
    table.add_column("directory", overflow="fold")
    for entry in applications:
        colour = _BANDS.get(entry.band, "white")
        table.add_row(
            f"[{colour}]{entry.fit} {entry.band}[/{colour}]",
            entry.company or "unknown",
            entry.title or "unknown",
            entry.status,
            str(entry.rounds),
            _relative(config, entry.directory),
        )
    return table


@app.command(name="list")
@handled
def list_applications(
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Comma-separated statuses to show."),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option("--all", "-a", help="Every application, whatever its status."),
    ] = False,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """List applications, best fit first. Unsubmitted ones by default."""
    config = _config(config_path)
    if show_all:
        wanted, heading = None, "all applications"
    elif status:
        wanted = [layout.check_status(s.strip()) for s in status.split(",")]
        heading = ", ".join(wanted)
    else:
        wanted, heading = [OPEN], "prepared, not yet sent"

    with ApplicationStore(config.search.database) as store:
        found = store.select(wanted)
        counts = store.counts()

    if not found:
        typer.echo(f"nothing {heading}. 'cvme prep URL' prepares one.")
        return
    console.print(_table(config, found, heading))
    console.print(
        "  ".join(f"{count} {name}" for name, count in sorted(counts.items()))
    )


@app.command()
@handled
def show(
    reference: Annotated[
        str, typer.Argument(help="A slug, part of one, or a company name.")
    ],
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Everything recorded about one application."""
    config = _config(config_path)
    with ApplicationStore(config.search.database) as store:
        entry = store.resolve(reference)
        rounds = store.rounds_for(entry.slug)

    console.print(f"[bold]{entry.title or 'unknown'}[/bold] at {entry.company}")
    colour = _BANDS.get(entry.band, "white")
    console.print(f"fit [{colour}]{entry.fit}/100 ({entry.band})[/{colour}]")
    console.print(f"status {entry.status}, prepared {entry.created_at[:10]}")
    if entry.applied_at:
        console.print(f"applied {entry.applied_at[:10]}")
    if entry.note:
        console.print(f"note: {entry.note}")
    console.print(entry.url or "no url recorded")
    console.print(entry.directory)

    if rounds:
        table = Table(header_style="bold")
        for column in ("v", "prepared", "documents", "pages", "changes"):
            table.add_column(column)
        for item in rounds:
            table.add_row(
                str(item.number),
                item.created_at[:10],
                item.documents,
                item.pages,
                item.changes,
            )
        console.print(table)
    if not entry.path.is_dir():
        console.print(f"[yellow]the directory is missing: {entry.directory}[/yellow]")


@app.command(name="status")
@handled
def set_status(
    reference: Annotated[
        str, typer.Argument(help="A slug, part of one, or a company name.")
    ],
    new_status: Annotated[str, typer.Argument(help=f"One of: {', '.join(STATUSES)}.")],
    note: Annotated[str, typer.Option("--note", help="Anything worth recording.")] = "",
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Refile an application, moving its directory to match."""
    config = _config(config_path)
    layout.check_status(new_status)
    with ApplicationStore(config.search.database) as store:
        entry = store.resolve(reference)
        if entry.status == new_status:
            typer.echo(f"{entry.slug} is already {new_status}")
            return
        hunt = layout.Hunt(
            config.project.hunts_dir, entry.year, entry.slug, entry.status
        )
        if not hunt.path.is_dir():
            found = layout.find(config.project.hunts_dir, entry.slug)
            if found is None:
                raise HuntError(
                    f"{entry.slug} is recorded at {entry.directory}, which is gone"
                )
            hunt = found
        moved = layout.refile(hunt, new_status)
        store.set_status(entry.slug, new_status, directory=moved.path, note=note)
    typer.echo(f"{entry.slug}: {entry.status} -> {new_status}")
    typer.echo(f"  moved to {moved.path}")


@app.command()
@handled
def submit(
    reference: Annotated[
        str, typer.Argument(help="A slug, part of one, or a company name.")
    ],
    note: Annotated[str, typer.Option("--note", help="Anything worth recording.")] = "",
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Mark an application sent, and file it out of the unsubmitted list."""
    set_status(reference, "applied", note=note, config_path=config_path)
