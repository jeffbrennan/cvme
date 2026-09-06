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
from cvme.linkedin import audit, live, review, sync
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
def login(
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Open a browser for you to sign in to LinkedIn, and keep the session.

    LinkedIn's user agreement prohibits automated access and makes no
    exception for your own profile, so this is opt-in and the risk to your
    account is yours. cvme never types a credential, never hides that it is
    automation, and stops rather than work around a verification challenge.

    The session is a Chromium profile of cvme's own, separate from your
    everyday browser. `cvme linkedin logout` deletes it.
    """
    del config_path
    from cvme.linkedin import browser

    with browser.session() as page:
        browser.login(page)
        url = browser.own_profile(page)
    typer.echo(f"Signed in. Session stored in {browser.session_dir()}")
    typer.echo(f"Profile bound to {url}")


@app.command()
@handled
def logout() -> None:
    """Delete cvme's stored browser session."""
    from cvme.linkedin import browser

    if browser.forget():
        typer.echo(f"Removed {browser.session_dir()}")
    else:
        typer.echo("No browser session was stored.")


@app.command()
@handled
def capture(
    output: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the capture as JSON to this file."),
    ] = None,
) -> None:
    """Read your profile in the browser and print what was recovered.

    The capture-only path: it compares nothing and records nothing, so it is
    the command to run while checking that extraction actually matches the
    page in front of you.
    """
    from cvme.linkedin import browser

    with browser.session() as page:
        result = browser.capture(page)

    typer.echo(f"captured {result.profile_url}")
    for line in result.lines():
        typer.echo(line)
    body = result.model_dump_json(indent=2, exclude_defaults=True)
    if output is None:
        typer.echo(body)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body + "\n", encoding="utf-8")
    typer.echo(f"wrote {output}")


@app.command()
@handled
def check(
    profile: Annotated[
        Path | None,
        typer.Argument(
            help="Your profile PDF (More > Save to PDF), or a data export "
            "ZIP/directory. Omit it with --browser."
        ),
    ] = None,
    browser_source: Annotated[
        bool,
        typer.Option("--browser", help="Read the profile from a signed-in browser."),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict", help="Also fail on entries LinkedIn has and you do not."
        ),
    ] = False,
    record_now: Annotated[
        bool,
        typer.Option("--record", help="Record the profile you read as the live state."),
    ] = False,
    show: Annotated[
        bool,
        typer.Option("--show", help="Print what cvme read from the source, and stop."),
    ] = False,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Check the live profile against the source documents, and fail on drift.

    Quickest sanctioned route: your profile > More > Save to PDF, then point
    this at it. The data export (Settings & Privacy > Data Privacy > Get a
    copy of your data) takes a few minutes and is the one that can vouch for
    your skills list.

    `--browser` reads your own profile from a signed-in local browser. It is
    the most convenient and the only one LinkedIn's terms do not permit; see
    `cvme linkedin login --help`.
    """
    config = _config(config_path)
    source = _source(profile, browser_source)
    typer.echo(f"read {source.label}")

    if show:
        typer.echo(source.profile.model_dump_json(indent=2, exclude_defaults=True))
        return

    plan = sync.build(config)
    result = audit.audit(plan.profile, source)

    for line in result.lines():
        typer.echo(line)
    typer.echo(result.summary())
    if source.unchecked:
        # Said every time, not just on failure: a clean run against a source
        # that never looked at your skills is not a clean profile.
        typer.echo(
            f"not checked  {', '.join(source.unchecked)} (this source "
            "does not report them in full)"
        )

    if record_now:
        # What LinkedIn holds, not what cvme projected: recording the source
        # leaves whatever has not been applied still outstanding, which is the
        # point of grounding the state in evidence rather than in a promise.
        keep = audit.recordable(
            plan.profile, source, sync_state.load(config.root).profile, strict=strict
        )
        path = sync_state.save(config.root, keep)
        typer.echo(f"recorded the profile you read to {path}")

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


def _source(profile: Path | None, use_browser: bool) -> live.Source:
    """Whichever source the flags name, refusing an ambiguous pair."""
    if use_browser == (profile is not None):
        raise ConfigError(
            "name one source: a profile PDF or export path, or --browser."
        )
    if profile is not None:
        return live.read(profile)

    from cvme.linkedin import browser

    with browser.session() as page:
        result = browser.capture(page)
    for line in result.lines():
        err_console.print(line)
    return result.as_source()


def _warn(plan: Plan) -> None:
    for violation in plan.violations:
        err_console.print(f"[yellow]too long[/yellow] {violation}")
    if plan.unmapped:
        err_console.print(
            f"[yellow]not synced[/yellow] no LinkedIn field for: "
            f"{', '.join(plan.unmapped)}"
        )
