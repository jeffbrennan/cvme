"""``cvme prep`` -- one posting, one directory, everything in it.

The commands underneath this one already existed and were each a step: fetch
the posting, tailor to it, verify, render. What was missing was the thing that
holds them, so that a week later the question "what did I send these people,
and why did I think it was worth sending" has an answer that is not memory.

A run produces, or adds a version to:

    hunts/2026/01_northwind_staff-data-engineer_2026-01-04/
        posting.md    the posting as captured, unedited
        report.md     the computed fit, then the written background
        apps/         every version, and an index of how they differ

Running it twice on the same posting adds version 2 beside version 1 rather
than overwriting it, because the useful comparison is against what you nearly
sent.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from cvme.cli.errors import handled
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError, VerificationFailed
from cvme.generate import agent as agents
from cvme.generate.bundle import build
from cvme.generate.produce import generate, produce, write_prompt
from cvme.hunt import index, layout, report
from cvme.hunt.score import Fit
from cvme.hunt.score import evaluate as evaluate_fit
from cvme.hunt.store import ApplicationStore
from cvme.jobs import sources, writer
from cvme.jobs.models import JobPosting
from cvme.style.schema import resolve as resolve_style
from cvme.verify.corpus import Corpus
from cvme.verify.corpus import load as load_corpus


def _config(config_path: Path | None) -> Config:
    found = config_path or find_config()
    if found is None:
        raise ConfigError("prep needs a project; run 'cvme init DIRECTORY' first")
    return load_config(found)


def _capture(
    target: str,
    config: Config,
    *,
    html: Path | None,
    text: Path | None,
    stdin: bool,
    no_cache: bool,
) -> JobPosting:
    """Get the posting, from wherever it is easiest to get it honestly."""
    given = (("--html", html), ("--text", text), ("--stdin", stdin))
    manual = [name for name, value in given if value]
    if len(manual) > 1:
        raise ConfigError("give at most one of --html, --text or --stdin")

    if html is not None:
        if not html.is_file():
            raise ConfigError(f"no such file: {html}")
        page = html.read_text(encoding="utf-8", errors="replace")
        return sources.from_html(page, target)
    if text is not None:
        if not text.is_file():
            raise ConfigError(f"no such file: {text}")
        return sources.from_text(text.read_text(encoding="utf-8"), target)
    if stdin:
        return sources.from_text(sys.stdin.read(), target)

    candidate = Path(target)
    if candidate.is_file():
        return writer.read(candidate)
    in_jobs = config.project.jobs_dir / f"{target}.md"
    if in_jobs.is_file():
        return writer.read(in_jobs)
    if "://" not in target:
        raise ConfigError(
            f"'{target}' is not a URL, a file, or a posting in "
            f"{config.project.jobs_dir}"
        )
    return sources.Fetcher(root=config.root, use_cache=not no_cache).fetch(target)


def corpus_text(config: Config, documents: list[str]) -> str:
    """Everything you are entitled to claim, as one blob to look for terms in."""
    paths = list(config.project.facts)
    paths += [config.document(name).path for name in documents]
    return "\n\n".join(
        path.read_text(encoding="utf-8") for path in paths if path.is_file()
    )


def _locate(config: Config, posting: JobPosting, *, new: bool) -> layout.Hunt:
    """The hunt this posting belongs to, existing or freshly numbered."""
    root = config.project.hunts_dir
    if not new:
        with ApplicationStore(config.search.database) as store:
            if (existing := store.by_url(posting.url)) is not None:
                found = layout.find(root, existing.slug)
                if found is not None:
                    return found
    year = str(date.today().year)
    sequence = layout.next_sequence(root, year)
    slug = layout.make_slug(sequence, posting.company, posting.title)
    return layout.Hunt(root, year, slug)


def _fit_only(posting: JobPosting, fit: Fit) -> None:
    typer.echo(report.fit_block(posting, fit).rstrip())


@handled
def prep(
    target: Annotated[
        str, typer.Argument(help="A posting URL, a job markdown file, or its name.")
    ],
    documents: Annotated[
        str | None,
        typer.Option("--documents", "-d", help="Comma-separated names to produce."),
    ] = None,
    agent_name: Annotated[
        str | None,
        typer.Option(
            "--agent", help="Agent to invoke. 'none' just writes the prompts."
        ),
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
    html: Annotated[
        Path | None, typer.Option("--html", help="A saved HTML page to read instead.")
    ] = None,
    text: Annotated[
        Path | None, typer.Option("--text", help="A file holding the description.")
    ] = None,
    stdin: Annotated[
        bool, typer.Option("--stdin", help="Read the description from stdin.")
    ] = False,
    title: Annotated[str, typer.Option("--title", help="Override the job title.")] = "",
    company: Annotated[
        str, typer.Option("--company", help="Override the company name.")
    ] = "",
    note: Annotated[
        str, typer.Option("--note", help="Why this version exists; goes in the index.")
    ] = "",
    new: Annotated[
        bool,
        typer.Option("--new", help="Start a new hunt even if this URL has one."),
    ] = False,
    fit_only: Annotated[
        bool,
        typer.Option("--fit-only", help="Score the posting, write nothing, stop."),
    ] = False,
    no_report: Annotated[
        bool, typer.Option("--no-report", help="Skip the company background.")
    ] = False,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Ignore any cached fetch.")
    ] = False,
    no_verify: Annotated[
        bool, typer.Option("--no-verify", help="Skip the verification gate.")
    ] = False,
    no_render: Annotated[
        bool, typer.Option("--no-render", help="Do not produce PDFs.")
    ] = False,
) -> None:
    """Capture a posting, tailor documents to it, and brief yourself on it."""
    config = _config(config_path)
    wanted = (
        [d.strip() for d in documents.split(",")] if documents else config.tailorable()
    )
    if not wanted:
        raise ConfigError("no documents configured to tailor")
    for name in wanted:
        config.document(name)  # raises with the known names

    posting = _capture(
        target, config, html=html, text=text, stdin=stdin, no_cache=no_cache
    )
    posting.title = title or posting.title
    posting.company = company or posting.company
    if not posting.description.strip():
        raise ConfigError("no description found; check the input")

    fit = evaluate_fit(
        posting,
        corpus_text(config, wanted),
        config.search,
        extra_terms=config.fit.extra_terms,
    )
    if fit_only:
        _fit_only(posting, fit)
        return

    hunt = _locate(config, posting, new=new)
    hunt.apps.mkdir(parents=True, exist_ok=True)
    hunt.posting.write_text(writer.to_markdown(posting), encoding="utf-8")
    typer.echo(f"hunt {hunt.slug}")
    typer.echo(f"  wrote {hunt.posting}  [{posting.source}, tier {posting.tier}]")
    if gaps := posting.missing():
        typer.echo(f"  incomplete: no {', '.join(gaps)}; fill them in by hand")

    stems = [config.hunt_stem(name) for name in wanted]
    round_number = layout.next_round(hunt.apps, stems)

    spec = agents.resolve(agent_name or config.generate.agent, config.agents)
    corpus: Corpus = (
        load_corpus(config.project.facts) if config.project.facts else Corpus()
    )
    if not no_verify and not corpus:
        raise ConfigError(
            "prep verification requires a fact corpus; configure project.facts "
            "or pass --no-verify explicitly"
        )

    prompts = hunt.path / ".prompts"
    produced = []
    rejected: list[str] = []
    for name in wanted:
        document = config.document(name)
        stem = config.hunt_stem(name)
        style = resolve_style(document.style, document.overrides)
        bundle = build(
            document=name,
            template=document.template,
            base_path=document.path,
            job_path=hunt.posting,
            facts=config.project.facts,
            output_path=hunt.apps / f"{stem}{round_number}.md",
            style=style,
            generate=config.generate,
            agent_output_path=Path(f"{stem}{round_number}.md"),
        )
        try:
            produced.append(
                produce(
                    bundle,
                    spec,
                    prompt_dir=prompts,
                    corpus=corpus,
                    style=style,
                    template=document.template,
                    verify=not no_verify,
                    should_render=not no_render,
                    echo=typer.echo,
                )
            )
        except VerificationFailed as exc:
            # The gate holds: no PDF was produced. But the rest of the run is
            # still worth having, and a rejected draft with a report beside it
            # is what you fix from.
            typer.echo(f"  {exc}")
            rejected.append(name)

    if not no_report:
        _write_report(config, hunt, posting, fit, spec, prompts)

    changes = _changes(config, hunt, wanted, round_number)
    pages = ", ".join(
        f"{p.document} {p.pages}p" for p in produced if p.pages is not None
    )
    with ApplicationStore(config.search.database) as store:
        store.record(
            slug=hunt.slug,
            year=hunt.year,
            url=posting.url,
            company=posting.company,
            title=posting.title,
            location=posting.location,
            directory=hunt.path,
            fit=fit.score,
            band=fit.band,
            rounds=round_number,
            note=note,
        )
        store.add_round(
            slug=hunt.slug,
            number=round_number,
            documents=", ".join(
                f"{config.hunt_stem(p.document)}{round_number}"
                for p in produced
                if p.markdown is not None
            ),
            pages=pages,
            fit=fit.score,
            changes=changes,
            note=note,
        )
        index.write(
            hunt.index,
            hunt.slug,
            " at ".join(p for p in (posting.title, posting.company) if p),
            store.rounds_for(hunt.slug),
        )

    typer.echo(f"  wrote {hunt.index}")
    typer.echo("")
    typer.echo(f"{hunt.path}  version {round_number}")
    typer.echo(report.summary_line(fit))
    if not no_report:
        typer.echo(f"read {hunt.report} before you write anything by hand")
    if rejected:
        raise VerificationFailed(
            f"{', '.join(rejected)} did not pass verification and "
            f"{'was' if len(rejected) == 1 else 'were'} not rendered; "
            "the draft and the report are in place to fix from"
        )


def _write_report(
    config: Config,
    hunt: layout.Hunt,
    posting: JobPosting,
    fit: Fit,
    spec: agents.AgentSpec,
    prompts: Path,
) -> None:
    """Compose the report: the computed score, then the agent's background.

    The score is written by cvme rather than asked of the agent, so nothing in
    the report claims a number that cannot be recomputed from the posting.
    """
    base = config.document(next(iter(config.tailorable() or config.documents))).path
    bundle = build(
        document="report",
        template="report",
        base_path=base,
        job_path=hunt.posting,
        facts=config.project.facts,
        output_path=hunt.path / ".background.md",
        style=resolve_style("standard"),
        generate=config.generate,
        agent_output_path=Path("background.md"),
    )
    prompt_path = write_prompt(bundle, prompts)
    if spec.writes_nothing:
        hunt.report.write_text(
            report.compose(posting, fit, f"_Run the prompt at {prompt_path}._"),
            encoding="utf-8",
        )
        typer.echo(f"  wrote {hunt.report} (fit only; no agent ran)")
        return

    typer.echo(f"running {spec.name} for the report...")
    generate(spec, bundle, prompt_path)
    background = bundle.output_path.read_text(encoding="utf-8")
    bundle.output_path.unlink()
    hunt.report.write_text(report.compose(posting, fit, background), encoding="utf-8")
    typer.echo(f"  wrote {hunt.report}")


def _changes(
    config: Config, hunt: layout.Hunt, documents: list[str], round_number: int
) -> str:
    """How this round's lead document differs from the round before it."""
    stem = config.hunt_stem(documents[0])
    current = hunt.apps / f"{stem}{round_number}.md"
    if not current.is_file():
        return "not generated"
    earlier = layout.rounds(hunt.apps, stem)
    prior = [n for n in earlier if n < round_number]
    previous = hunt.apps / f"{stem}{max(prior)}.md" if prior else None
    return index.summarise(previous, current)
