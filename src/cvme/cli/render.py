"""``cvme render`` -- markdown in, PDF out."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated, Any

import typer

from cvme.errors import ConfigError
from cvme.md.parse import parse_file
from cvme.render.engine import compile_document
from cvme.style.schema import resolve


def _overrides(pairs: list[str]) -> dict[str, Any]:
    """Parse ``--set key=value`` pairs, coercing to the field's type."""
    from cvme.style.schema import Style

    fields = Style.model_fields
    out: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ConfigError(f"--set expects key=value, got '{pair}'")
        key, raw = pair.split("=", 1)
        key = key.strip()
        if key not in fields:
            raise ConfigError(f"unknown style key '{key}'")
        annotation = fields[key].annotation
        try:
            if annotation is bool:
                out[key] = raw.strip().lower() in {"1", "true", "yes", "on"}
            elif annotation is int:
                out[key] = int(raw)
            elif annotation is float:
                out[key] = float(raw)
            else:
                out[key] = raw
        except ValueError as exc:
            raise ConfigError(f"bad value for '{key}': {raw!r}") from exc
    return out


def render(
    source: Annotated[Path, typer.Argument(help="Markdown document to typeset.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output path. Defaults to <source>.pdf."),
    ] = None,
    style: Annotated[
        str, typer.Option("--style", help="Style preset: standard, compact, airy.")
    ] = "standard",
    template: Annotated[
        str, typer.Option("--template", help="Template name.")
    ] = "resume",
    png: Annotated[
        bool, typer.Option("--png", help="Also write a PNG per page, for eyeballing.")
    ] = False,
    set_: Annotated[
        list[str] | None,
        typer.Option("--set", help="Override a style key, e.g. --set leading=6.0."),
    ] = None,
    watch: Annotated[
        bool, typer.Option("--watch", help="Re-render whenever the source changes.")
    ] = False,
) -> None:
    """Typeset a markdown document as a PDF."""
    if not source.exists():
        raise ConfigError(f"no such file: {source}")
    out = output or source.with_suffix(".pdf")
    resolved = resolve(style, _overrides(set_ or []))

    def once() -> None:
        doc = parse_file(source)
        compile_document(doc, resolved, output=out, template=template)
        typer.echo(f"wrote {out}")
        if png:
            stem = out.with_suffix("")
            compile_document(
                doc,
                resolved,
                output=Path(f"{stem}_{{n}}.png"),
                template=template,
                fmt="png",
                ppi=110,
            )
            typer.echo(f"wrote {stem}_1.png")

    once()
    if not watch:
        return

    typer.echo(f"watching {source} (ctrl-c to stop)")
    last = source.stat().st_mtime
    try:
        while True:
            time.sleep(0.4)
            current = source.stat().st_mtime
            if current != last:
                last = current
                try:
                    once()
                except Exception as exc:  # keep watching after a bad edit
                    typer.echo(f"error: {exc}")
    except KeyboardInterrupt:
        typer.echo("stopped")
