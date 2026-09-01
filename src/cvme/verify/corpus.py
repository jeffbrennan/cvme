"""The fact corpus: the only claims a document is allowed to make.

Facts are read from markdown bullet lists, optionally tagged with an id:

    - [m-databricks-spend] Managed a platform at ~$100k per month.

The base resume is loaded as a source too, so a claim already standing in your
own resume does not have to be duplicated into the metrics file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from cvme.errors import ConfigError
from cvme.verify.numbers import Claim, extract

_BULLET = re.compile(r"^\s*[-*+]\s+(?:\[(?P<id>[A-Za-z0-9_.-]+)\]\s*)?(?P<text>.+)$")
_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    source: Path
    line: int
    claims: tuple[Claim, ...]

    @property
    def keys(self) -> set[tuple[float, str | None]]:
        return {c.key for c in self.claims}


@dataclass
class Corpus:
    facts: dict[str, Fact] = field(default_factory=dict)
    #: Every claim available from any source, including untagged prose.
    keys: set[tuple[float, str | None]] = field(default_factory=set)
    sources: list[Path] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.sources)

    def describe(self, key: tuple[float, str | None]) -> list[str]:
        """Facts whose value matches but whose unit does not, for hinting."""
        value, _ = key
        return [
            f.text for f in self.facts.values() if any(v == value for v, _ in f.keys)
        ]


def _derive_id(text: str, taken: set[str]) -> str:
    base = _SLUG.sub("-", text.lower()).strip("-")[:40] or "fact"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def load(paths: list[Path]) -> Corpus:
    """Read a corpus from fact files and/or base documents."""
    corpus = Corpus()
    for path in paths:
        if not path.is_file():
            raise ConfigError(f"fact file not found: {path}")
        corpus.sources.append(path)
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = _BULLET.match(raw)
            text = match.group("text") if match else line
            claims = tuple(extract(text))
            corpus.keys.update(c.key for c in claims)
            if match:
                identifier = match.group("id") or _derive_id(text, set(corpus.facts))
                corpus.facts[identifier] = Fact(
                    id=identifier,
                    text=text,
                    source=path,
                    line=number,
                    claims=claims,
                )
    return corpus
