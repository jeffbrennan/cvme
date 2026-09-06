"""``cvme linkedin`` -- keep a profile in step with the source documents.

Read ``cvme.linkedin.review`` before wiring anything to ``--transport api``:
the Profile Edit API is partner-gated, so the review transport is the default
and, for most people, the only one that will run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cvme.cli.errors import err_console, handled
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError
from cvme.linkedin import auth, review, sync
from cvme.linkedin import state as sync_state
from cvme.linkedin.client import Client
from cvme.linkedin.sync import Plan

app = typer.Typer(
    name="linkedin",
    help="Sync the source documents to a LinkedIn profile.",
    no_args_is_help=True,
    add_completion=False,
)

_SETUP_STEPS = """\
Create a LinkedIn app once, then cvme never asks again.

  1. Open https://www.linkedin.com/developers/apps/new
  2. Give it any name, attach a LinkedIn Page you control, and create it.
  3. On the Products tab, request "Sign In with LinkedIn using OpenID Connect".
  4. On the Auth tab, add this exact redirect URL:

       {redirect_uri}

  5. Copy the Client ID and Client Secret from the same tab.

The secret is stored at {path}, readable only by you, and never in the project.
"""

#: Said once, at setup, rather than at every failed push. Someone configuring
#: this deserves to know what it can and cannot do before they spend an hour
#: on it, not after.
_ACCESS_NOTE = """\
What this gets you: cvme signs in as you and can confirm who you are.

Writing to profile sections -- headline, About, experience, education, skills
-- needs LinkedIn's Profile Edit API, which is granted through a partner
programme and is not part of the self-serve developer tier. Unless your app
has that permission, `--transport api` will return 403.

The default `--transport review` needs none of this. It writes the changed
fields to a file you paste in, which is why setup is optional.
"""


def _config(config_path: Path | None) -> Config:
    found = config_path or find_config()
    if found is None:
        raise ConfigError("no cvme.toml found; run `cvme init` first")
    return load_config(found)


@app.command()
@handled
def setup(
    client_id: Annotated[
        str, typer.Option("--client-id", help="The app's Client ID.")
    ] = "",
    client_secret: Annotated[
        str, typer.Option("--client-secret", help="The app's Client Secret.")
    ] = "",
    port: Annotated[
        int, typer.Option("--port", help="Local port for the OAuth redirect.")
    ] = auth.DEFAULT_PORT,
    scope: Annotated[
        list[str] | None,
        typer.Option("--scope", help="An OAuth scope to request. Repeatable."),
    ] = None,
    login_now: Annotated[
        bool, typer.Option("--login/--no-login", help="Sign in once configured.")
    ] = True,
) -> None:
    """Register your LinkedIn app with cvme, once, on this machine."""
    credentials = auth.load()
    credentials.port = port
    credentials.scopes = list(scope) if scope else credentials.scopes

    typer.echo(
        _SETUP_STEPS.format(
            redirect_uri=credentials.redirect_uri, path=auth.credentials_path()
        )
    )
    credentials.client_id = client_id or typer.prompt(
        "Client ID",
        default=credentials.client_id,
        show_default=bool(credentials.client_id),
    )
    credentials.client_secret = client_secret or typer.prompt(
        "Client Secret", hide_input=True
    )

    path = auth.save(credentials)
    typer.echo(f"\nSaved to {path} (mode 600).\n")
    typer.echo(_ACCESS_NOTE)

    if login_now:
        auth.save(auth.authorize(credentials))
        typer.echo("Signed in.")
    else:
        typer.echo("Run `cvme linkedin login` when you are ready to sign in.")


@app.command()
@handled
def login(
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Print the URL instead of opening it.")
    ] = False,
) -> None:
    """Authorise cvme against your LinkedIn app."""
    credentials = auth.authorize(auth.load(), open_browser=not no_browser)
    with Client(auth.access_token(credentials)) as client:
        credentials.person_id = client.whoami()
    auth.save(credentials)
    typer.echo("Signed in.")


@app.command()
@handled
def logout() -> None:
    """Forget the stored token, keeping the app registration."""
    typer.echo("Token removed." if auth.forget_token() else "No token was stored.")


@app.command()
@handled
def status(
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """What is configured, what is signed in, and what is outstanding."""
    credentials = auth.load()
    typer.echo(f"credentials  {auth.credentials_path()}")
    for name, value in credentials.redacted().items():
        typer.echo(f"  {name:<14} {value}")

    config = _config(config_path)
    plan = sync.build(config)
    recorded = sync_state.load(config.root)
    typer.echo(f"\nsource       {plan.source}")
    typer.echo(f"overlay      {plan.overlay or 'none'}")
    typer.echo(f"fields       {', '.join(config.linkedin.fields)}")
    typer.echo(
        "last sync    "
        + (
            f"{recorded.synced_at:%Y-%m-%d %H:%M UTC} via {recorded.transport}"
            if recorded.recorded
            else "never"
        )
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
    transport: Annotated[
        str, typer.Option("--transport", help="'review' or 'api'.")
    ] = "review",
    record_now: Annotated[
        bool,
        typer.Option(
            "--record/--no-record",
            help="Record the changeset as applied. Only meaningful for review; "
            "an api sync is confirmed by LinkedIn and always recorded.",
        ),
    ] = False,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Bring the profile in step with the source documents."""
    if transport not in ("review", "api"):
        raise ConfigError(f"unknown transport '{transport}'; use 'review' or 'api'")
    config = _config(config_path)
    plan = sync.build(config)

    # Refused rather than truncated, and refused before anything is sent: a
    # field LinkedIn would reject is a sentence to shorten, not a sentence to
    # cut off mid-word.
    if plan.blocked:
        raise ConfigError(
            "these fields are longer than LinkedIn accepts:\n"
            + "\n".join(f"  {violation}" for violation in plan.violations)
            + f"\n  Shorten them in {plan.overlay or plan.source}."
        )

    if not plan.changeset:
        typer.echo("nothing to sync; the profile matches the source documents")
        return

    if transport == "review":
        _review(config, plan, record_now)
    else:
        _api(config, plan)
    _warn(plan)


def _review(config: Config, plan: Plan, record_now: bool) -> None:
    path = config.project.output_dir / config.linkedin.changeset
    review.write(
        path, plan.changeset, violations=plan.violations, unmapped=plan.unmapped
    )
    typer.echo(f"wrote {path}  [{plan.changeset.summary()}]")
    if record_now:
        # Only when asked. Recording says "the profile now looks like this",
        # and cvme has no way to know whether the file was actually pasted in.
        typer.echo(f"recorded {sync.record(config, plan, transport='review', ids={})}")
    else:
        typer.echo("Apply it, then run `cvme linkedin record`.")


def _api(config: Config, plan: Plan) -> None:
    credentials = auth.load()
    token = auth.access_token(credentials)
    known = sync_state.load(config.root).remote_ids
    with Client(
        token,
        person_id=credentials.person_id,
        locale=_locale(config.linkedin.locale),
    ) as client:
        ids = sync.apply_api(plan, client, known)
    # Recorded unconditionally, unlike review: LinkedIn confirmed these
    # changes, so leaving them unrecorded would re-push every one next run.
    typer.echo(f"applied {plan.changeset.summary()}")
    typer.echo(f"recorded {sync.record(config, plan, transport='api', ids=ids)}")


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
    path = sync.record(
        config, plan, transport="manual", ids=sync_state.load(config.root).remote_ids
    )
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


def _locale(value: str) -> tuple[str, str]:
    language, _, country = value.partition("_")
    if not language or not country:
        raise ConfigError(f"`[linkedin] locale` must look like 'en_US', not '{value}'")
    return language, country


def _warn(plan: Plan) -> None:
    for violation in plan.violations:
        err_console.print(f"[yellow]too long[/yellow] {violation}")
    if plan.unmapped:
        err_console.print(
            f"[yellow]not synced[/yellow] no LinkedIn field for: "
            f"{', '.join(plan.unmapped)}"
        )
