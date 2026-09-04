"""``cvme ats`` -- read a rendered PDF back the way a parser would."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import typer

from cvme.ats.check import check_pdf
from cvme.config import Config, DocumentConfig, find_config, load_config
from cvme.errors import ConfigError, CvmeError
from cvme.md.parse import parse_file
from cvme.render.fit import fit
from cvme.style.schema import resolve


class AtsCheckFailed(CvmeError):
    """A rendered document does not read back the way it was written."""

    exit_code = 3


def _select(target: str | None, config: Config | None) -> tuple[str | None, Path]:
    if target is not None and Path(target).is_file():
        return None, Path(target)
    if config is None:
        raise ConfigError(
            f"no such file: {target}" if target else "give a file, or run 'cvme init'"
        )
    if target is None:
        name, _ = config.sole_document()
        return name, config.document(name).path if name else Path()
    return target, config.document(target).path


def ats(
    target: Annotated[
        str | None,
        typer.Argument(help="A PDF, a markdown file, or a document name."),
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit findings as JSON.")
    ] = False,
) -> None:
    """Check that a rendered PDF reads back the way it was written."""
    found = config_path or find_config()
    config = load_config(found) if found else None
    name, path = _select(target, config)

    if not path.is_file():
        raise ConfigError(f"no such file: {path}")

    if path.suffix.lower() == ".pdf":
        report = check_pdf(path)
    else:
        document = (
            config.document(name) if config and name else DocumentConfig(path=path)
        )
        style = resolve(document.style, document.overrides)
        source = parse_file(path)
        with tempfile.TemporaryDirectory() as workdir:
            rendered = Path(workdir) / "check.pdf"
            fit(source, style, output=rendered, template=document.template)
            report = check_pdf(rendered, source=source, max_pages=style.max_pages)
        report = type(report)(path=path, findings=report.findings)

    typer.echo(report.to_json() if as_json else report.format())
    if not report.ok:
        raise AtsCheckFailed("the rendered document loses structure a parser needs")
