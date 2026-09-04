"""Where a hunt lives on disk, and what it is called.

One directory per posting, numbered within its year so the order you found
things in survives sorting, and named for the company and role so the
directory listing is the index. Everything a single application needs is
inside it: the posting as captured, the report, and every version of the
documents that were sent or nearly sent.

    hunts/2026/01_northwind_staff-data-engineer_2026-01-04/
        posting.md
        report.md
        apps/
            index.md
            cv1.md  cv1.pdf  cover_letter1.md  cover_letter1.pdf
            cv2.md  cv2.pdf  cover_letter2.md  cover_letter2.pdf

Filing moves the whole directory under a status, so what is still unanswered
is what is still at the top level of the year.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cvme.errors import HuntError

#: The one status that stays at the top of its year. Everything else is filed.
OPEN = "prepared"
STATUSES = (OPEN, "applied", "interviewing", "offer", "rejected", "withdrawn")

_SLUG = re.compile(r"[^a-z0-9]+")
_SEQUENCE = re.compile(r"^(\d+)_")
_ROUND = re.compile(r"(\d+)$")


def slugify(value: str, limit: int = 28) -> str:
    return _SLUG.sub("-", value.casefold()).strip("-")[:limit].strip("-")


def make_slug(sequence: int, company: str, title: str, when: date | None = None) -> str:
    parts = [
        f"{sequence:02d}",
        slugify(company) or "unknown",
        slugify(title) or "role",
        (when or date.today()).isoformat(),
    ]
    return "_".join(parts)


@dataclass(frozen=True)
class Hunt:
    """One posting's directory, wherever it is currently filed."""

    root: Path
    year: str
    slug: str
    status: str = OPEN

    @property
    def path(self) -> Path:
        base = self.root / self.year
        if self.status == OPEN:
            return base / self.slug
        return base / self.status / self.slug

    @property
    def apps(self) -> Path:
        return self.path / "apps"

    @property
    def posting(self) -> Path:
        return self.path / "posting.md"

    @property
    def report(self) -> Path:
        return self.path / "report.md"

    @property
    def index(self) -> Path:
        return self.apps / "index.md"

    def refiled(self, status: str) -> Hunt:
        return Hunt(self.root, self.year, self.slug, status)


def check_status(status: str) -> str:
    if status not in STATUSES:
        raise HuntError(f"unknown status '{status}'; use one of: {', '.join(STATUSES)}")
    return status


def existing(root: Path, year: str) -> list[Hunt]:
    """Every hunt recorded on disk for one year, filed or not."""
    found: list[Hunt] = []
    base = root / year
    if not base.is_dir():
        return found
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in STATUSES:
            found.extend(
                Hunt(root, year, child.name, entry.name)
                for child in sorted(entry.iterdir())
                if child.is_dir()
            )
        else:
            found.append(Hunt(root, year, entry.name, OPEN))
    return found


def next_sequence(root: Path, year: str) -> int:
    """One past the highest number used this year, filed hunts included."""
    used = [
        int(match.group(1))
        for hunt in existing(root, year)
        if (match := _SEQUENCE.match(hunt.slug))
    ]
    return max(used, default=0) + 1


def find(root: Path, slug: str) -> Hunt | None:
    """Locate a hunt by exact slug across every year and status."""
    if not root.is_dir():
        return None
    for year_dir in sorted(root.iterdir()):
        if not year_dir.is_dir():
            continue
        for hunt in existing(root, year_dir.name):
            if hunt.slug == slug:
                return hunt
    return None


def rounds(apps: Path, stem: str) -> list[int]:
    """Which numbered versions of one document already exist."""
    if not apps.is_dir():
        return []
    found = []
    for path in apps.glob(f"{stem}*.md"):
        if match := _ROUND.match(path.stem[len(stem) :]):
            found.append(int(match.group(1)))
    return sorted(found)


def next_round(apps: Path, stems: list[str]) -> int:
    """The next version number, shared by every document in the hunt.

    Shared rather than per-document because a resume and the cover letter that
    went with it are one attempt, and reading them back apart is how you end up
    sending version three of one with version one of the other.
    """
    used = [n for stem in stems for n in rounds(apps, stem)]
    return max(used, default=0) + 1


def refile(hunt: Hunt, status: str) -> Hunt:
    """Move a hunt's directory to match a new status."""
    check_status(status)
    target = hunt.refiled(status)
    if target.path == hunt.path:
        return target
    if not hunt.path.is_dir():
        raise HuntError(f"nothing to move at {hunt.path}")
    if target.path.exists():
        raise HuntError(f"{target.path} already exists")
    target.path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(hunt.path), str(target.path))
    return target
