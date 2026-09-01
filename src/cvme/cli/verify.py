"""``cvme verify`` -- check a document's claims and its prose."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError, CvmeError
from cvme.verify.check import verify_file
from cvme.verify.corpus import Corpus, load


class VerificationFailed(CvmeError):
    """A document made a claim it cannot support, or wrote like a machine."""

    exit_code = 3


def _targets(target: str | None, config: Config | None) -> list[Path]:
    if target is not None and Path(target).is_file():
        return [Path(target)]
    if config is None:
        raise ConfigError(
            f"no such file: {target}" if target else "give a file, or run 'cvme init'"
        )
    if target is None:
        return [d.path for d in config.documents.values()]
    return [config.document(target).path]


def verify(
    target: Annotated[
        str | None,
        typer.Argument(help="A markdown file, or a document name. Omit for all."),
    ] = None,
    facts: Annotated[
        list[Path] | None,
        typer.Option("--facts", help="Fact files. Defaults to the configured corpus."),
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit findings as JSON.")
    ] = False,
    no_facts: Annotated[
        bool,
        typer.Option("--no-facts", help="Check prose only; skip claim sourcing."),
    ] = False,
) -> None:
    """Check that every number is sourced and the prose does not read as generated."""
    found = config_path or find_config()
    config = load_config(found) if found else None

    paths = _targets(target, config)
    fact_files = list(facts or (config.project.facts if config else []))
    corpus: Corpus = load(fact_files) if fact_files else Corpus()

    if not no_facts and not corpus:
        typer.echo("no fact corpus configured; checking prose only", err=True)

    failed = False
    for path in paths:
        if not path.is_file():
            raise ConfigError(f"no such file: {path}")
        report = verify_file(path, corpus, check_facts=not no_facts)
        typer.echo(report.to_json() if as_json else report.format())
        failed = failed or not report.ok

    if failed:
        raise VerificationFailed("verification failed")
