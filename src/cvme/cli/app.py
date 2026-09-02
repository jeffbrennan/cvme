"""The ``cvme`` command-line entry point."""

from __future__ import annotations

import sys

import typer

from cvme import __version__
from cvme.cli.digest import digest
from cvme.cli.errors import err_console, handled
from cvme.cli.init import init
from cvme.cli.job import app as job_app
from cvme.cli.render import render
from cvme.cli.tailor import tailor
from cvme.cli.verify import verify

app = typer.Typer(
    name="cvme",
    help="Typeset resumes and cover letters from markdown.",
    no_args_is_help=True,
    add_completion=False,
)
app.command()(handled(init))
app.command()(handled(render))
app.command()(handled(verify))
app.command()(digest)
app.command()(tailor)
app.add_typer(job_app, name="job")


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

    # Agents are reported but never fail the check: cvme renders and verifies
    # without one, and `--agent none` is a supported way to work.
    from cvme.generate.agent import defaults, probe

    for spec in defaults().values():
        available, detail = probe(spec)
        mark = "[green]ok[/green]" if available else "[yellow]absent[/yellow]"
        err_console.print(f"agent {spec.name}: {mark} {detail}")

    if not ok:
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
