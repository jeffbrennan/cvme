"""``cvme render`` -- markdown in, PDF out."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated, Any

import typer

from cvme.config import Config, DocumentConfig, find_config, load_config
from cvme.errors import ConfigError
from cvme.md.parse import parse_file
from cvme.render.engine import compile_document
from cvme.render.fit import fit
from cvme.style.schema import Style, resolve


def _overrides(pairs: list[str]) -> dict[str, Any]:
    """Parse ``--set key=value`` pairs, coercing to each field's type."""
    fields = Style.model_fields
    out: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ConfigError(f"--set expects key=value, got '{pair}'")
        key, raw = (part.strip() for part in pair.split("=", 1))
        if key not in fields:
            raise ConfigError(f"unknown style key '{key}'")
        annotation = fields[key].annotation
        try:
            if annotation is bool:
                out[key] = raw.lower() in {"1", "true", "yes", "on"}
            elif annotation is int:
                out[key] = int(raw)
            elif annotation is float:
                out[key] = float(raw)
            else:
                out[key] = raw
        except ValueError as exc:
            raise ConfigError(f"bad value for '{key}': {raw!r}") from exc
    return out


def _select(
    target: str | None, config: Config | None
) -> tuple[str | None, DocumentConfig]:
    """Resolve a target to a document.

    A target that names an existing file is taken as a path; otherwise it is
    looked up as a document name in cvme.toml. Checking the filesystem first
    keeps the common case unambiguous.
    """
    if target is None:
        if config is None:
            raise ConfigError("give a file to render, or run 'cvme init' first")
        return config.sole_document()
    if Path(target).is_file():
        return None, DocumentConfig(path=Path(target))
    if config is not None:
        return target, config.document(target)
    raise ConfigError(f"no such file: {target}")


def render(
    target: Annotated[
        str | None,
        typer.Argument(help="A markdown file, or a document name from cvme.toml."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output path.")
    ] = None,
    style: Annotated[
        str | None,
        typer.Option("--style", help="Preset: standard, compact, airy, letter."),
    ] = None,
    template: Annotated[
        str | None, typer.Option("--template", help="Template name.")
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
    png: Annotated[
        bool, typer.Option("--png", help="Also write a PNG per page, for eyeballing.")
    ] = False,
    set_: Annotated[
        list[str] | None,
        typer.Option("--set", help="Override a style key, e.g. --set leading=6.0."),
    ] = None,
    max_pages: Annotated[
        int | None, typer.Option("--max-pages", help="Page budget to fit within.")
    ] = None,
    no_autofit: Annotated[
        bool,
        typer.Option("--no-autofit", help="Render as authored; warn if over budget."),
    ] = False,
    pdf_standard: Annotated[
        str | None,
        typer.Option("--pdf-standard", help="Emit to a standard, e.g. ua-1, a-2b."),
    ] = None,
    watch: Annotated[
        bool, typer.Option("--watch", help="Re-render whenever the source changes.")
    ] = False,
) -> None:
    """Typeset a markdown document as a PDF."""
    found = config_path or find_config()
    if config_path is not None and not config_path.is_file():
        raise ConfigError(f"no such config file: {config_path}")
    config = load_config(found) if found else None

    name, document = _select(target, config)
    source = document.path
    if not source.is_file():
        raise ConfigError(f"no such file: {source}")

    overrides = dict(document.overrides)
    overrides.update(_overrides(set_ or []))
    if max_pages is not None:
        overrides["max_pages"] = max_pages
    if pdf_standard is not None:
        overrides["pdf_standard"] = pdf_standard
    if no_autofit:
        overrides["on_overflow"] = "warn"
    resolved = resolve(style or document.style, overrides)
    chosen_template = template or document.template

    if output is not None:
        out = output
    elif name is not None and config is not None:
        out = config.project.output_dir / f"{name}.pdf"
    else:
        out = source.with_suffix(".pdf")

    def once() -> None:
        doc = parse_file(source)
        result = fit(doc, resolved, output=out, template=chosen_template)
        typer.echo(f"wrote {out} ({result.pages} page{'s' * (result.pages != 1)})")
        if result.applied:
            typer.echo(f"  tightened to fit: {', '.join(result.applied)}")
        elif result.pages > resolved.max_pages:
            typer.echo(
                f"  warning: {result.pages} pages exceeds the budget of "
                f"{resolved.max_pages}"
            )
        if png:
            stem = out.with_suffix("")
            compile_document(
                doc,
                result.style,
                output=Path(f"{stem}_{{n}}.png"),
                template=chosen_template,
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
