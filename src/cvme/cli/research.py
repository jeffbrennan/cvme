"""``cvme research`` -- an agent researches one employer's stability.

The posting does not carry these signals, so they are fetched from outside it.
The agent writes a dossier of dated, sourced facts and never a score; the score
is computed from the dossier in :mod:`cvme.hunt.stability`, so every point
traces to a citation and the number can be recomputed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from cvme.cli.errors import handled
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError
from cvme.generate import agent as agents
from cvme.generate.bundle import Bundle
from cvme.generate.produce import generate, write_prompt
from cvme.hunt import stability

PROMPT = Path(__file__).parent.parent / "generate" / "prompts" / "stability.md"


def _config(path: Path | None) -> Config:
    found = path or find_config()
    if found is None:
        raise ConfigError("research needs a project; run 'cvme init DIRECTORY' first")
    return load_config(found)


@handled
def research(
    company: Annotated[str, typer.Argument(help="The company to research.")],
    url: Annotated[
        str, typer.Option("--url", help="The posting URL, for context.")
    ] = "",
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Research again over an existing dossier.")
    ] = False,
    agent_name: Annotated[
        str | None,
        typer.Option("--agent", help="Agent to invoke. 'none' writes the prompt only."),
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
) -> None:
    """Research an employer's stability into a sourced dossier."""
    config = _config(config_path)
    directory = config.stability.dir
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{stability.slug(company)}.md"

    if output.is_file() and not refresh:
        existing = stability.load(
            directory,
            company,
            **config.stability.scoring(),
        )
        typer.echo(f"{output} exists")
        if existing is not None:
            typer.echo(f"  {stability.summary_line(existing)}")
        typer.echo("  pass --refresh to research it again")
        return

    posting_note = f"The role being considered is at {url}." if url.strip() else ""
    prompt = PROMPT.read_text(encoding="utf-8").format(
        company=company,
        today=date.today().isoformat(),
        posting_note=posting_note,
    )
    bundle = Bundle(
        document="stability",
        prompt=prompt,
        output_path=output,
        agent_output_path=Path("dossier.md"),
    )
    prompt_path = write_prompt(bundle, directory / ".prompts")
    chosen = agent_name or config.stability.agent or config.generate.agent
    spec = agents.resolve(chosen, config.agents)

    if spec.writes_nothing:
        typer.echo(f"wrote {prompt_path}")
        typer.echo("  run it in a browsing assistant, then save the dossier to")
        typer.echo(f"  {output}")
        return

    typer.echo(f"running {spec.name} to research {company}...")
    generate(spec, bundle, prompt_path)
    typer.echo(f"  wrote {output}")

    result = stability.load(
        directory,
        company,
        **config.stability.scoring(),
    )
    if result is None:  # pragma: no cover - generate wrote the file
        raise ConfigError(f"{output} was not written")
    typer.echo(f"  {stability.summary_line(result)}")
