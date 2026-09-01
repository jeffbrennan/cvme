"""On-disk cache of raw responses.

Keyed by URL, so re-parsing never re-fetches. That matters for two reasons:
selector work happens offline against the exact bytes that failed, and a
posting is fetched once no matter how often it is re-read.
"""

from __future__ import annotations

from hashlib import blake2b
from pathlib import Path

CACHE_DIRNAME = ".cvme/cache"


def key(url: str) -> str:
    return blake2b(url.encode(), digest_size=16).hexdigest()


class Cache:
    def __init__(self, root: Path):
        self.dir = root / CACHE_DIRNAME

    def path(self, url: str, suffix: str = ".raw") -> Path:
        return self.dir / f"{key(url)}{suffix}"

    def read(self, url: str, suffix: str = ".raw") -> str | None:
        path = self.path(url, suffix)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def write(self, url: str, body: str, suffix: str = ".raw") -> Path:
        path = self.path(url, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path
