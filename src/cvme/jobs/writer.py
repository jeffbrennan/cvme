"""Write a posting as markdown, so it is reviewable and diffable."""

from __future__ import annotations

from pathlib import Path

import yaml

from cvme.jobs.models import JobPosting

#: Frontmatter order, chosen so the useful fields are visible without scrolling.
_FIELDS = (
    "title",
    "company",
    "location",
    "employment_type",
    "remote",
    "salary",
    "posted",
    "url",
    "apply_url",
    "source",
    "tier",
    "fetched_at",
)


def to_markdown(posting: JobPosting) -> str:
    data = posting.model_dump(mode="json")
    front = {k: data[k] for k in _FIELDS if data.get(k) not in (None, "", [])}
    header = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    heading = " at ".join(p for p in (posting.title, posting.company) if p)
    body = posting.description or "_No description captured._"
    return f"---\n{header}\n---\n\n# {heading or 'Job posting'}\n\n{body}\n"


def write(posting: JobPosting, directory: Path, name: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name or posting.slug}.md"
    path.write_text(to_markdown(posting), encoding="utf-8")
    return path
