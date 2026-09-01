"""The ``cvme`` command-line entry point."""

from __future__ import annotations

import functools
import sys
from collections.abc import Callable
from typing import Any, cast

import typer
from rich.console import Console

from cvme import __version__
from cvme.cli.init import init
from cvme.cli.render import render
from cvme.errors import CvmeError

app = typer.Typer(
    name="cvme",
    help="Typeset resumes and cover letters from markdown.",
    no_args_is_help=True,
    add_completion=False,
)
err_console = Console(stderr=True)


def handled[F: Callable[..., Any]](command: F) -> F:
    """Report expected failures as a message and an exit code, not a traceback.

    Applied per command rather than around ``app()`` so the behaviour holds
    however the CLI is entered, including from tests.
    """

    @functools.wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except CvmeError as exc:
            err_console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(exc.exit_code) from exc

    # functools.wraps preserves the signature typer introspects, but the
    # wrapper's own type is not F.
    return cast(F, wrapper)


app.command()(handled(init))
app.command()(handled(render))


@app.command()
def version() -> None:
    """Print the cvme version."""
    typer.echo(__version__)


@app.command()
@handled
def doctor() -> None:
    """Check that the rendering environment is usable."""
    from cvme.render.fonts import font_report

    ok = True
    typer.echo(f"cvme {__version__}")
    typer.echo(f"python {sys.version.split()[0]}")

    try:
        import typst

        typer.echo(f"typst {getattr(typst, '__version__', 'installed')}")
    except ImportError:  # pragma: no cover - dependency is declared
        err_console.print("[red]typst is not installed[/red]")
        ok = False

    for name, found, detail in font_report():
        mark = "[green]ok[/green]" if found else "[red]missing[/red]"
        err_console.print(f"font {name}: {mark} {detail}")
        ok = ok and found

    if not ok:
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
