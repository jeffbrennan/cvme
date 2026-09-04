"""``cvme tailor`` -- produce documents targeted at one job posting.

The flow is: assemble a prompt, let an agent write files, verify what it
wrote, then render. Verification is a gate rather than a report, because a
document that invents a metric should never reach a PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cvme.cli.errors import handled
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError
from cvme.generate import agent as agents
from cvme.generate.bundle import Bundle, build
from cvme.generate.produce import produce
from cvme.style.schema import resolve as resolve_style
from cvme.verify.corpus import Corpus
from cvme.verify.corpus import load as load_corpus


def _config(config_path: Path | None) -> Config:
    found = config_path or find_config()
    if found is None:
        raise ConfigError("tailoring needs a project; run 'cvme init' first")
    return load_config(found)


def _job_path(target: str, config: Config) -> Path:
    candidate = Path(target)
    if candidate.is_file():
        return candidate
    in_jobs = config.project.jobs_dir / f"{target}.md"
    if in_jobs.is_file():
        return in_jobs
    raise ConfigError(f"no job posting at {target} or {in_jobs}")


@handled
def tailor(
    job: Annotated[str, typer.Argument(help="A job markdown file, or its name.")],
    documents: Annotated[
        str | None,
        typer.Option("--documents", "-d", help="Comma-separated names to produce."),
    ] = None,
    agent_name: Annotated[
        str | None,
        typer.Option("--agent", help="Agent to invoke. 'none' just writes the prompt."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Directory to write into.")
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the assembled prompt and stop."),
    ] = False,
    no_verify: Annotated[
        bool, typer.Option("--no-verify", help="Skip the verification gate.")
    ] = False,
    no_render: Annotated[
        bool, typer.Option("--no-render", help="Do not produce PDFs.")
    ] = False,
) -> None:
    """Tailor your documents to a job posting."""
    config = _config(config_path)
    job_path = _job_path(job, config)
    wanted = (
        [d.strip() for d in documents.split(",")] if documents else config.tailorable()
    )
    if not wanted:
        raise ConfigError("no documents configured to tailor")
    for name in wanted:
        config.document(name)  # raises with the known names

    workdir = (out or (config.project.applications_dir / job_path.stem)).resolve()

    bundles: list[Bundle] = []
    for name in wanted:
        document = config.document(name)
        bundles.append(
            build(
                document=name,
                template=document.template,
                base_path=document.path,
                job_path=job_path,
                facts=config.project.facts,
                output_path=workdir / f"{name}.md",
                style=resolve_style(document.style, document.overrides),
                generate=config.generate,
                agent_output_path=Path(f"{name}.md"),
            )
        )

    if dry_run:
        # No side effects: the directory is only created once something is
        # actually going to be written into it.
        for bundle in bundles:
            typer.echo(f"\n{'=' * 72}\n# prompt for {bundle.document}\n{'=' * 72}\n")
            typer.echo(bundle.prompt)
        return

    spec = agents.resolve(agent_name or config.generate.agent, config.agents)
    corpus: Corpus = (
        load_corpus(config.project.facts) if config.project.facts else Corpus()
    )
    if not no_verify and not corpus:
        raise ConfigError(
            "tailoring verification requires a fact corpus; configure "
            "project.facts or pass --no-verify explicitly"
        )

    workdir.mkdir(parents=True, exist_ok=True)

    for bundle in bundles:
        document = config.document(bundle.document)
        produce(
            bundle,
            spec,
            prompt_dir=workdir,
            corpus=corpus,
            style=resolve_style(document.style, document.overrides),
            template=document.template,
            verify=not no_verify,
            should_render=not no_render,
            echo=typer.echo,
        )
