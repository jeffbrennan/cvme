"""``cvme apps`` -- what is prepared, what was sent, and what came back.

Two questions, and this exists to answer them. Which of the things I have
prepared have I not sent, best first, because that is the order to spend an
evening in. And where did the one I did send go, which is a matter of moving
its directory so that what is left at the top of the year is what is still
outstanding.

"Best" is not only fit. A strong match that pays less than the job you have,
or that advertises itself with "we are a family" and "unlimited PTO", is not
the one to spend the evening on, so the table carries what the posting said
about pay and about the hours beside the score, and ``--sort`` picks which of
them decides the order. Every column is read from the posting and can be
recomputed from it; nothing here was asserted by a model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console, JustifyMethod
from rich.table import Table
from rich.text import Text

from cvme.cli.errors import handled
from cvme.cli.prep import conditions
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError, CvmeError, HuntError
from cvme.hunt import layout
from cvme.hunt.layout import OPEN, STATUSES
from cvme.hunt.pay import thousands
from cvme.hunt.store import ORDERS, Application, ApplicationStore, check_order
from cvme.jobs import writer

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

#: Work-life bands, on the same principle and the same colours.
_WLB_BANDS = {
    "calm": "green",
    "steady": "cyan",
    "unstated": "bright_black",
    "busy": "yellow",
    "grind": "red",
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


@dataclass(frozen=True)
class Column:
    """One cell of the listing, and how to fill it."""

    name: str
    render: Callable[[Config, Application], str]
    justify: JustifyMethod = "left"
    wrap: bool = False


def _fit(entry: Application) -> str:
    colour = _BANDS.get(entry.band, "white")
    return f"[{colour}]{entry.fit} {entry.band}[/{colour}]"


def _wlb(entry: Application) -> str:
    colour = _WLB_BANDS.get(entry.wlb_band, "white")
    if entry.wlb_band in ("", "unstated"):
        # The baseline is not a reading, and printing it as one would invite
        # comparison with scores that were actually earned.
        return f"[{colour}]{entry.wlb_band or 'unread'}[/{colour}]"
    return f"[{colour}]{entry.wlb} {entry.wlb_band}[/{colour}]"


def _days(count: int) -> str:
    return f"{count}d" if count >= 0 else "-"


#: Every column the listing can show. ``--columns`` names them; the default
#: set is what fits a terminal and answers "which one tonight".
COLUMNS: dict[str, Column] = {
    "fit": Column("fit", lambda _, e: _fit(e), justify="right"),
    "company": Column("company", lambda _, e: e.company or "unknown"),
    "title": Column("title", lambda _, e: e.title or "unknown", wrap=True),
    "salary": Column("salary", lambda _, e: e.pay.short, justify="right"),
    "wlb": Column("work-life", lambda _, e: _wlb(e), justify="right"),
    "age": Column("age", lambda _, e: _days(e.age_days()), justify="right"),
    "waiting": Column("waiting", lambda _, e: _days(e.waiting_days()), justify="right"),
    "status": Column("status", lambda _, e: e.status),
    "versions": Column("v", lambda _, e: str(e.rounds), justify="right"),
    "where": Column("where", lambda _, e: e.arrangement or "-"),
    "location": Column("location", lambda _, e: e.location or "-", wrap=True),
    "note": Column("note", lambda _, e: e.note, wrap=True),
    "slug": Column("slug", lambda _, e: e.slug),
    "url": Column("url", lambda _, e: e.url, wrap=True),
    "directory": Column("directory", lambda c, e: _relative(c, e.directory), wrap=True),
}

#: What a listing shows when nothing else is asked for. The directory is not
#: in it: it is the widest thing in the table and the least scannable, and
#: ``cvme apps show`` prints it in full. Add it back with
#: ``--columns fit,company,title,directory``.
DEFAULT_COLUMNS = (
    "fit",
    "company",
    "title",
    "salary",
    "wlb",
    "where",
    "age",
    "status",
    "versions",
)


#: The order the default set gives way in on a narrow terminal, least useful
#: first. What is left when this is exhausted is the answer to "which one
#: tonight", and is never dropped: a table too narrow for it is one to widen.
DROP_ORDER = ("versions", "status", "where", "age")

#: How wide a wrapping column is allowed to count for when deciding what fits.
#: A long title wraps rather than pushing another column out of the table.
WRAP_BUDGET = 22


def check_columns(names: str | None) -> list[str]:
    """The columns to show, defaulted, in the order they were asked for."""
    if not names:
        return list(DEFAULT_COLUMNS)
    wanted = [name.strip() for name in names.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in COLUMNS]
    if unknown:
        raise ConfigError(
            f"unknown column{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(unknown)}; use: {', '.join(COLUMNS)}"
        )
    return wanted


def _width(config: Config, name: str, applications: list[Application]) -> int:
    """How wide this column wants to be, in characters, markup excluded."""
    column = COLUMNS[name]
    longest = max(
        (
            Text.from_markup(column.render(config, entry)).cell_len
            for entry in applications
        ),
        default=0,
    )
    wanted = max(len(column.name), longest)
    return min(wanted, WRAP_BUDGET) if column.wrap else wanted


def fitting(
    config: Config, applications: list[Application], columns: list[str], width: int
) -> list[str]:
    """The asked-for columns, minus what a terminal this wide cannot hold.

    Rich will squeeze a table that does not fit until the company name is four
    characters and an ellipsis, which is worse than not showing a column at
    all. So the decision is made here, and what was dropped is said out loud.
    """
    widths = {name: _width(config, name, applications) for name in columns}
    chosen = list(columns)
    while sum(widths[name] for name in chosen) + 3 * len(chosen) + 1 > width:
        droppable = [name for name in DROP_ORDER if name in chosen]
        if not droppable:
            break
        chosen.remove(droppable[0])
    return chosen


def _table(
    config: Config,
    applications: list[Application],
    heading: str,
    columns: list[str],
) -> Table:
    table = Table(title=heading, title_justify="left", header_style="bold")
    for name in columns:
        column = COLUMNS[name]
        table.add_column(
            column.name,
            justify=column.justify,
            no_wrap=not column.wrap,
            overflow="fold" if column.wrap else "ellipsis",
        )
    for entry in applications:
        table.add_row(*(COLUMNS[name].render(config, entry) for name in columns))
    return table


def _footer(applications: list[Application], counts: dict[str, int]) -> str:
    """Counts by status, and what the listed rows are worth taken together."""
    parts = [f"{count} {name}" for name, count in sorted(counts.items())]
    paid = sorted(entry.pay.midpoint for entry in applications if entry.pay)
    if paid:
        middle = paid[len(paid) // 2]
        parts.append(f"median pay {thousands(middle)} of {len(paid)} stated")
    stated = [entry for entry in applications if entry.wlb_band not in ("", "unstated")]
    if stated:
        average = round(sum(entry.wlb for entry in stated) / len(stated))
        parts.append(f"mean work-life {average} of {len(stated)} stated")
    return "  ".join(parts)


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
    sort: Annotated[
        str,
        typer.Option("--sort", help=f"Order by: {', '.join(ORDERS)}."),
    ] = "fit",
    reverse: Annotated[
        bool, typer.Option("--reverse", "-r", help="Worst first instead of best.")
    ] = False,
    columns: Annotated[
        str | None,
        typer.Option("--columns", "-c", help=f"Comma-separated: {', '.join(COLUMNS)}."),
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """List applications, best first. Unsubmitted ones by default."""
    config = _config(config_path)
    wanted_columns = check_columns(columns)
    check_order(sort)
    if show_all:
        wanted, heading = None, "all applications"
    elif status:
        wanted = [layout.check_status(s.strip()) for s in status.split(",")]
        heading = ", ".join(wanted)
    else:
        wanted, heading = [OPEN], "prepared, not yet sent"

    with ApplicationStore(config.search.database) as store:
        found = store.select(wanted, order=sort, reverse=reverse)
        counts = store.counts()

    if not found:
        typer.echo(f"nothing {heading}. 'cvme prep URL' prepares one.")
        return
    shown = (
        wanted_columns
        if columns
        else fitting(config, found, wanted_columns, console.width)
    )
    order = f"{heading}, by {sort}{' reversed' if reverse else ''}"
    console.print(_table(config, found, order, shown))
    console.print(_footer(found, counts))
    if dropped := [name for name in wanted_columns if name not in shown]:
        console.print(
            f"[bright_black]{', '.join(dropped)} not shown; the terminal is "
            f"{console.width} wide. --columns picks your own.[/bright_black]"
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
    stated = f" (as stated: {entry.pay.stated})" if entry.pay.stated else ""
    console.print(
        f"pay {entry.pay.short}{stated}"
        if entry.pay
        else "pay: the posting did not say"
    )
    if entry.arrangement:
        console.print(f"where {entry.arrangement}, {entry.location or 'no location'}")
    _print_culture(entry)
    console.print(
        f"status {entry.status}, prepared {entry.created_at[:10]} "
        f"({entry.age_days()} days ago)"
    )
    if entry.applied_at:
        console.print(f"applied {entry.applied_at[:10]} ({entry.waiting_days()}d ago)")
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


def _print_culture(entry: Application) -> None:
    """The work-life score and, under it, every phrase that produced it."""
    culture = entry.culture
    colour = _WLB_BANDS.get(culture.band, "white")
    console.print(
        f"work-life [{colour}]{culture.score}/100 ({culture.band})[/{colour}]"
    )
    for signal in culture.signals:
        tint = "red" if signal.weight < 0 else "green"
        says = f": {signal.says}" if signal.says else ""
        console.print(f"  [{tint}]{signal.sign:>4}[/{tint}] {signal.term}{says}")


@app.command()
@handled
def rescan(
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Re-read every captured posting for pay and hours, and update the table.

    The fit score is left alone: it is measured against the corpus and belongs
    to the run that produced the documents. Pay and the work-life reading come
    from the posting alone, so they can be brought up to date -- after the
    lexicon changes, or for applications prepared before the columns existed --
    without pretending a new version was prepared.
    """
    config = _config(config_path)
    read = 0
    missing: list[str] = []
    unreadable: list[str] = []
    with ApplicationStore(config.search.database) as store:
        for entry in store.select(None):
            posting_path = entry.path / "posting.md"
            if not posting_path.is_file():
                missing.append(entry.slug)
                continue
            try:
                posting = writer.read(posting_path)
            except CvmeError as exc:
                # One unreadable posting is not a reason to leave the rest of
                # the table stale.
                unreadable.append(f"{entry.slug}: {exc}")
                continue
            money, culture = conditions(config, posting)
            store.set_conditions(
                entry.slug,
                pay=money,
                culture=culture,
                arrangement=posting.arrangement,
            )
            read += 1
    typer.echo(f"re-read {read} posting{'' if read == 1 else 's'}")
    for slug in missing:
        typer.echo(f"  no posting.md for {slug}; nothing to read")
    for problem in unreadable:
        typer.echo(f"  {problem}")


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
