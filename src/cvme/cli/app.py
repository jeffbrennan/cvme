"""The ``cvme`` command-line entry point."""

from __future__ import annotations

import sys

import typer
from rich.console import Console

from cvme import __version__
from cvme.cli.render import render
from cvme.errors import CvmeError

app = typer.Typer(
    name="cvme",
    help="Typeset resumes and cover letters from markdown.",
    no_args_is_help=True,
    add_completion=False,
)
err_console = Console(stderr=True)


app.command()(render)


@app.command()
def version() -> None:
    """Print the cvme version."""
    typer.echo(__version__)


@app.command()
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
    """Run the CLI, reporting expected failures without a traceback."""
    try:
        app()
    except CvmeError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise SystemExit(exc.exit_code) from exc


if __name__ == "__main__":
    main()
