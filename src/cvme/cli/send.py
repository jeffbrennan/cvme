"""``cvme send`` -- the untailored document under a recipient-facing name.

A recruiter who asks for "your resume" is not a posting: there is no title to
tailor to and no hunt to file the result under. What they get is the base
document as it stands, named for the role they are hiring for, so that what
lands in their inbox is `jeff_brennan_senior_data_engineer.pdf` rather than
`base.pdf`.

The PDF is rendered rather than copied, so a name never gets attached to a
stale render of a document that has since been edited.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError
from cvme.generate.naming import role_title, token
from cvme.md.parse import parse_file
from cvme.render.fit import fit
from cvme.style import color
from cvme.style.schema import resolve


def _config(config_path: Path | None) -> Config:
    found = config_path or find_config()
    if config_path is not None and not config_path.is_file():
        raise ConfigError(f"no such config file: {config_path}")
    if found is None:
        raise ConfigError("no cvme.toml found; run 'cvme init' first")
    return load_config(found)


def send(
    titles: Annotated[
        list[str],
        typer.Argument(
            help="Role titles to name copies for, e.g. 'Senior Data Engineer'."
        ),
    ],
    document: Annotated[
        str, typer.Option("--document", "-d", help="Document name from cvme.toml.")
    ] = "base",
    directory: Annotated[
        Path | None,
        typer.Option(
            "--dir", help="Where the copies go. Defaults to project.send_dir."
        ),
    ] = None,
    style: Annotated[
        str | None, typer.Option("--style", help="Preset: sans, serif, standard, ...")
    ] = None,
    accent: Annotated[
        str | None, typer.Option("--accent", help="Accent colour: #rrggbb or a name.")
    ] = None,
    markdown: Annotated[
        bool, typer.Option("--md", help="Write the markdown source alongside the PDF.")
    ] = False,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Copy an untailored document out under one filename per role title."""
    config = _config(config_path)
    spec = config.document(document)
    source = spec.path
    if not source.is_file():
        raise ConfigError(f"no such file: {source}")

    out_dir = directory or config.project.send_dir
    doc = parse_file(source)
    name = token(doc.name)
    if not name:
        raise ConfigError(f"{source} needs a name for send filenames")

    overrides = dict(spec.overrides)
    chosen = accent or config.accent.default
    if chosen:
        overrides["accent"] = color.parse(chosen)
    resolved = resolve(style or spec.style, overrides)

    # Titles are normalised before they are filenames, so two that differ only
    # in what normalisation drops -- a grade, an abbreviation, a location --
    # would otherwise land on one file and the second would quietly win.
    stems: dict[str, str] = {}
    for title in titles:
        role = role_title(title)
        if not role:
            raise ConfigError(f"'{title}' normalises to nothing usable as a filename")
        if role in stems:
            raise ConfigError(
                f"'{title}' and '{stems[role]}' both name {name}_{role}.pdf"
            )
        stems[role] = title

    out_dir.mkdir(parents=True, exist_ok=True)
    for role in stems:
        stem = f"{name}_{role}"
        out = out_dir / f"{stem}.pdf"
        result = fit(doc, resolved, output=out, template=spec.template)
        typer.echo(f"wrote {out} ({result.pages} page{'s' * (result.pages != 1)})")
        if result.pages > resolved.max_pages:
            typer.echo(
                f"  warning: {result.pages} pages exceeds the budget of "
                f"{resolved.max_pages}"
            )
        if markdown:
            copy = out_dir / f"{stem}.md"
            copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            typer.echo(f"wrote {copy}")
