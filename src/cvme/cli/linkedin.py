"""``cvme linkedin`` -- keep a profile in step with the source documents.

There is one transport and it is a file you paste from. LinkedIn's Profile
Edit API, the only way to write a profile section programmatically, is
restricted to partner-approved developers, so an automated push is not
something this tool can offer. See ``cvme.linkedin.review``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cvme.cli.errors import err_console, handled
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError
from cvme.linkedin import review, sync
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
