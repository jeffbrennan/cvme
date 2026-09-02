"""``cvme digest`` -- discover, deduplicate, parse, and rank job postings."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cvme.cli.errors import handled
from cvme.config import Config, find_config, load_config
from cvme.errors import ConfigError, CvmeError
from cvme.jobs.discovery import discover
from cvme.jobs.match import blocked_company, evaluate
from cvme.jobs.sources import Fetcher, FetchError
from cvme.jobs.store import JobStore
from cvme.jobs.writer import write


def _config(path: Path | None) -> Config:
    found = path or find_config()
    if found is None:
        raise ConfigError("digest needs a project; run 'cvme init DIRECTORY' first")
    return load_config(found)


@handled
def digest(
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Path to cvme.toml.")
    ] = None,
    no_search: Annotated[
        bool,
        typer.Option(
            "--no-search", help="Only process postings already in the database."
        ),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum new postings to parse."),
    ] = None,
    retry_errors: Annotated[
        bool,
        typer.Option("--retry-errors", help="Try previously failed fetches again."),
    ] = False,
) -> None:
    """Find new jobs and show candidates that pass your configured preferences."""
    config = _config(config_path)
    if not config.search.sources and not no_search:
        raise ConfigError("no [[search.sources]] configured in cvme.toml")

    candidates: list[tuple[str, str, str, int, str, Path]] = []
    with JobStore(config.search.database) as store:
        if retry_errors:
            typer.echo(f"retrying {store.retry_errors()} failed posting(s)")

        if not no_search:
            for source in config.search.sources:
                try:
                    jobs = discover(source)
                except FetchError as exc:
                    typer.echo(str(exc), err=True)
                    continue
                added, seen = store.add(jobs)
                typer.echo(
                    f"{source.site}: {len(jobs)} found, {added} new, "
                    f"{seen} already seen"
                )

        fetcher = Fetcher(root=config.root)
        pending = store.pending(limit)
        for job in pending:
            if reason := blocked_company(job.company, config.search):
                store.decide(
                    job.key,
                    status="filtered",
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    reason=reason,
                    score=0,
                )
                continue
            try:
                posting = fetcher.fetch(job.url)
            except CvmeError as exc:
                store.decide(
                    job.key,
                    status="error",
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    error=str(exc),
                )
                typer.echo(f"could not parse {job.url}: {exc}", err=True)
                continue

            # Search cards can retain useful metadata that a public detail page
            # omits, so use it to fill gaps rather than throwing it away.
            posting.title = posting.title or job.title
            posting.company = posting.company or job.company
            posting.location = posting.location or job.location
            match = evaluate(posting, config.search)
            if match.accepted:
                path = write(posting, config.project.jobs_dir)
                status = "candidate"
                candidates.append(
                    (
                        posting.title,
                        posting.company,
                        posting.url,
                        match.score,
                        match.reason,
                        path,
                    )
                )
            else:
                path = Path()
                status = "filtered"
            store.decide(
                job.key,
                status=status,
                title=posting.title,
                company=posting.company,
                location=posting.location,
                reason=match.reason,
                score=match.score,
                posting_path=str(path) if match.accepted else "",
            )

        for title, company, url, score, reason, path in sorted(
            candidates, key=lambda item: item[3], reverse=True
        ):
            typer.echo(f"[{score}] {title or path.stem} at {company or 'unknown'}")
            typer.echo(f"    {reason}")
            typer.echo(f"    {url}")
            typer.echo(f"    saved {path}")

        counts = store.counts()
        typer.echo(
            "digest: "
            + ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
        )
