"""Read and write a posting as markdown, so it is reviewable and diffable."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from cvme.errors import ConfigError
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


def read(path: Path) -> JobPosting:
    """Read back a posting written by ``write``.

    The markdown is the record, so a posting captured once can be re-used
    without re-fetching it, and a description corrected by hand is the one
    everything downstream sees.
    """
    text = path.read_text(encoding="utf-8")
    front: dict[str, object] = {}
    body = text
    if text.startswith("---\n"):
        _, _, rest = text.partition("---\n")
        header, marker, body = rest.partition("\n---\n")
        if not marker:
            raise ConfigError(f"{path}: frontmatter is not closed")
        loaded = yaml.safe_load(header) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"{path}: frontmatter is not a mapping")
        front = loaded

    # The heading write() adds is a rendering of the frontmatter, not content.
    lines = body.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]

    fields = {k: v for k, v in front.items() if k in JobPosting.model_fields}
    fields.setdefault("url", "")
    fields["description"] = "\n".join(lines).strip()
    try:
        return JobPosting.model_validate(fields)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def write(posting: JobPosting, directory: Path, name: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name or posting.slug}.md"
    path.write_text(to_markdown(posting), encoding="utf-8")
    return path
