"""``cvme linkedin`` -- keep a profile in step with the source documents.

Writing is a file you paste from: LinkedIn's Profile Edit API, the only way to
change a profile section programmatically, is restricted to partner-approved
developers. Reading back is the data export, which any member can download and
which is what ``check`` audits against. See ``cvme.linkedin.review`` and
``cvme.linkedin.export``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cvme.cli.errors import err_console, handled
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError
from cvme.linkedin import audit, review, sync
from cvme.linkedin import export as export_reader
from cvme.linkedin import state as sync_state
from cvme.linkedin.sync import Plan

app = typer.Typer(
    name="linkedin",
    help="Sync the source documents to a LinkedIn profile.",
    no_args_is_help=True,
    add_completion=False,
)


def _config(config_path: Path | None) -> Config:
    found = config_path or find_config()
    if found is None:
        raise ConfigError("no cvme.toml found; run `cvme init` first")
    return load_config(found)


@app.command()
@handled
def status(
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Which documents feed the profile, and what is outstanding."""
    config = _config(config_path)
    plan = sync.build(config)
    recorded = sync_state.load(config.root)
    typer.echo(f"source       {plan.source}")
    typer.echo(f"overlay      {plan.overlay or 'none'}")
    typer.echo(f"fields       {', '.join(config.linkedin.fields)}")
    typer.echo(
        "last sync    "
        + (f"{recorded.synced_at:%Y-%m-%d %H:%M UTC}" if recorded.recorded else "never")
    )
    typer.echo(f"outstanding  {plan.changeset.summary()}")
    _warn(plan)


@app.command()
@handled
def diff(
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Show what has changed since the last recorded sync."""
    plan = sync.build(_config(config_path))
    if not plan.changeset:
        typer.echo("no changes")
    for change in plan.changeset.changes:
        typer.echo(str(change))
    _warn(plan)


@app.command("sync")
@handled
def sync_(
    record_now: Annotated[
        bool,
        typer.Option(
            "--record/--no-record",
            help="Record the changeset as applied, for when you paste as you go.",
        ),
    ] = False,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Write the changes to apply to the profile."""
    config = _config(config_path)
    plan = sync.build(config)

    # Refused rather than truncated: a field LinkedIn would reject is a
    # sentence to shorten, not a sentence to cut off mid-word.
    if plan.blocked:
        raise ConfigError(
            "these fields are longer than LinkedIn accepts:\n"
            + "\n".join(f"  {violation}" for violation in plan.violations)
            + f"\n  Shorten them in {plan.overlay or plan.source}."
        )

    if not plan.changeset:
        typer.echo("nothing to sync; the profile matches the source documents")
        return

    path = config.project.output_dir / config.linkedin.changeset
    review.write(
        path, plan.changeset, violations=plan.violations, unmapped=plan.unmapped
    )
    typer.echo(f"wrote {path}  [{plan.changeset.summary()}]")
    if record_now:
        # Only when asked. Recording says "the profile now looks like this",
        # and cvme has no way to know whether the file was actually pasted in.
        typer.echo(f"recorded {sync.record(config, plan)}")
    else:
        typer.echo("Apply it, then run `cvme linkedin record`.")
    _warn(plan)


@app.command()
@handled
def check(
    export: Annotated[
        Path,
        typer.Argument(
            help="The LinkedIn data export ZIP, or a directory of its CSVs."
        ),
    ],
    strict: Annotated[
        bool,
        typer.Option(
            "--strict", help="Also fail on entries LinkedIn has and you do not."
        ),
    ] = False,
    record_now: Annotated[
        bool,
        typer.Option("--record", help="Record the exported profile as the live state."),
    ] = False,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Check the live profile against the source documents, and fail on drift.

    Get the export from Settings & Privacy > Data Privacy > Get a copy of your
    data. It is the only first-party way to read the profile back: the read
    scopes are as partner-gated as the write ones.
    """
    config = _config(config_path)
    plan = sync.build(config)
    result = audit.audit(plan.profile, export_reader.read(export))

    for line in result.lines():
        typer.echo(line)
    typer.echo(result.summary())

    if record_now:
        # What LinkedIn holds, not what cvme projected: recording the export
        # leaves whatever has not been applied still outstanding, which is the
        # point of grounding the state in evidence rather than in a promise.
        keep = audit.recordable(plan.profile, result.live, strict=strict)
        path = sync_state.save(config.root, keep)
        typer.echo(f"recorded the exported profile to {path}")

    _warn(plan)
    if result.failed(strict=strict):
        raise audit.DriftError(
            f"the profile does not match your documents ({result.summary()}).\n"
            "  Run `cvme linkedin sync` for the changes to apply."
        )


@app.command()
@handled
def record(
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Mark the current source documents as applied to the profile."""
    config = _config(config_path)
    plan = sync.build(config)
    path = sync.record(config, plan)
    typer.echo(f"recorded {plan.changeset.summary()} to {path}")


@app.command()
@handled
def reset(
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Forget the sync state, so the next run offers the whole profile."""
    config = _config(config_path)
    cleared = sync_state.clear(config.root)
    typer.echo("Sync state cleared." if cleared else "No sync state was recorded.")


def _warn(plan: Plan) -> None:
    for violation in plan.violations:
        err_console.print(f"[yellow]too long[/yellow] {violation}")
    if plan.unmapped:
        err_console.print(
            f"[yellow]not synced[/yellow] no LinkedIn field for: "
            f"{', '.join(plan.unmapped)}"
        )
