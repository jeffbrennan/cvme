"""``cvme job`` -- turn a posting into reviewable markdown."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from cvme.cli.errors import handled
from cvme.config import find_config, load_config
from cvme.errors import ConfigError
from cvme.jobs import sources
from cvme.jobs.models import JobPosting
from cvme.jobs.writer import to_markdown, write

app = typer.Typer(
    name="job", help="Capture job postings.", no_args_is_help=True, add_completion=False
)


def _destination(output: Path | None, config_path: Path | None) -> tuple[Path, Path]:
    """Returns (project root, jobs directory)."""
    found = config_path or find_config()
    config = load_config(found) if found else None
    root = config.root if config else Path.cwd()
    if output is not None:
        return root, output
    return root, (config.project.jobs_dir if config else root / "jobs")


def _emit(posting: JobPosting, directory: Path, *, stdout: bool) -> None:
    if stdout:
        typer.echo(to_markdown(posting))
        return
    path = write(posting, directory)
    typer.echo(f"wrote {path}  [{posting.source}, tier {posting.tier}]")
    if missing := posting.missing():
        typer.echo(f"  incomplete: no {', '.join(missing)}; fill them in by hand")


@app.command()
@handled
def fetch(
    url: Annotated[str, typer.Argument(help="The job posting URL.")],
    output: Annotated[
        Path | None, typer.Option("--out", "-o", help="Directory to write into.")
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Ignore any cached response.")
    ] = False,
    stdout: Annotated[
        bool, typer.Option("--stdout", help="Print instead of writing a file.")
    ] = False,
) -> None:
    """Fetch a posting by URL, walking the source ladder."""
    root, directory = _destination(output, config_path)
    fetcher = sources.Fetcher(root=root, use_cache=not no_cache)
    _emit(fetcher.fetch(url), directory, stdout=stdout)


@app.command()
@handled
def add(
    url: Annotated[str, typer.Option("--url", help="The posting's URL.")] = "",
    html: Annotated[
        Path | None, typer.Option("--html", help="A saved HTML page to parse.")
    ] = None,
    text: Annotated[
        Path | None, typer.Option("--text", help="A file holding the description.")
    ] = None,
    stdin: Annotated[
        bool, typer.Option("--stdin", help="Read the description from stdin.")
    ] = False,
    title: Annotated[str, typer.Option("--title", help="Job title.")] = "",
    company: Annotated[str, typer.Option("--company", help="Company name.")] = "",
    output: Annotated[
        Path | None, typer.Option("--out", "-o", help="Directory to write into.")
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
    stdout: Annotated[
        bool, typer.Option("--stdout", help="Print instead of writing a file.")
    ] = False,
) -> None:
    """Capture a posting you already have: a saved page, a file, or a paste.

    This is a first-class path, not a fallback. For a personal tool fetching
    one page, pasting the description is a perfectly good answer, and unlike
    every scraper it never stops working.
    """
    chosen = [
        n for n, v in (("--html", html), ("--text", text), ("--stdin", stdin)) if v
    ]
    if len(chosen) != 1:
        raise ConfigError("give exactly one of --html, --text or --stdin")

    if html is not None:
        if not html.is_file():
            raise ConfigError(f"no such file: {html}")
        posting = sources.from_html(
            html.read_text(encoding="utf-8", errors="replace"), url
        )
    elif text is not None:
        if not text.is_file():
            raise ConfigError(f"no such file: {text}")
        posting = sources.from_text(text.read_text(encoding="utf-8"), url)
    else:
        posting = sources.from_text(sys.stdin.read(), url)

    posting.title = title or posting.title
    posting.company = company or posting.company
    if not posting.description.strip():
        raise ConfigError("no description found; check the input")

    _, directory = _destination(output, config_path)
    _emit(posting, directory, stdout=stdout)
