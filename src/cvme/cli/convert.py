"""``cvme convert`` -- an existing PDF resume in, markdown out."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cvme.convert import convert_file, pdf_to_markdown
from cvme.errors import ConvertError
from cvme.md.parse import parse


def convert(
    source: Annotated[Path, typer.Argument(help="A PDF resume to convert.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output path. Defaults to <source>.md."),
    ] = None,
    stdout: Annotated[
        bool, typer.Option("--stdout", help="Write the markdown to stdout instead.")
    ] = False,
) -> None:
    """Convert a PDF resume into cvme markdown."""
    if source.suffix.lower() != ".pdf":
        raise ConvertError(f"expected a PDF, got {source}")
    if stdout:
        typer.echo(pdf_to_markdown(source), nl=False)
        return

    out = output or source.with_suffix(".md")
    markdown = convert_file(source, out)
    document = parse(markdown, path=str(out))
    entries = sum(len(section.entries) for section in document.sections)
    typer.echo(f"wrote {out} ({len(document.sections)} sections, {entries} entries)")
    typer.echo("  review it: a PDF records layout, not intent")
