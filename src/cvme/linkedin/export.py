"""Reading what LinkedIn says your profile currently holds.

There is no API for this. The Profile API's read scopes are as partner-gated
as its write ones, and scraping the profile page is both blocked and against
LinkedIn's terms. What every member can get, without permission from anyone,
is their own data:

    Settings & Privacy > Data Privacy > Get a copy of your data
    > "Profile", "Positions", "Education", "Skills" (or the whole archive)

That arrives as a ZIP of CSVs within minutes, and it is first-party ground
truth: not what cvme believes it pushed, but what LinkedIn stores.

The columns are read by name and not by position, through an alias table,
because LinkedIn publishes no schema for this archive and has changed the
headers before. A file whose columns cannot be understood is an error naming
the headers that were actually found, so a rename is a five-second diagnosis
rather than a profile that silently audits as empty.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

from cvme.errors import CvmeError
from cvme.linkedin.dates import parse_point
from cvme.linkedin.model import Education, Position, Profile, Skill

#: Archive member -> the profile part it fills. Matched on the filename stem,
#: without case, so `Positions.csv` and `positions.csv` are the same file.
FILES = ("profile", "positions", "education", "skills")

#: Field -> the header spellings that mean it. First match wins, so the
#: current spelling leads and older ones follow.
COLUMNS: dict[str, dict[str, tuple[str, ...]]] = {
    "profile": {
        "headline": ("headline",),
        "summary": ("summary", "about"),
    },
    "positions": {
        "company": ("company name", "company"),
        "title": ("title", "position"),
        "description": ("description",),
        "location": ("location",),
        "start": ("started on", "start date", "started"),
        "end": ("finished on", "end date", "finished"),
    },
    "education": {
        "school": ("school name", "school"),
        "degree": ("degree name", "degree"),
        "field_of_study": ("field of study", "major"),
        "description": ("notes", "description", "activities"),
        "start": ("start date", "started on"),
        "end": ("end date", "finished on"),
    },
    "skills": {
        "name": ("name", "skill", "skill name"),
    },
}

#: Columns without which the file cannot be read at all. Everything else is
#: optional, so a LinkedIn schema change costs a field rather than the run.
REQUIRED = {
    "profile": (),
    "positions": ("company", "title"),
    "education": ("school",),
    "skills": ("name",),
}


class ExportError(CvmeError):
    exit_code = 10


def read(path: Path) -> Profile:
    """The live profile, from an export ZIP or an unpacked directory."""
    tables = _tables(path)
    if not tables:
        raise ExportError(
            f"{path}: no LinkedIn export data here.\n"
            "  Expected Profile.csv, Positions.csv, Education.csv or Skills.csv,\n"
            "  from Settings & Privacy > Data Privacy > Get a copy of your data."
        )

    profile = Profile()
    if rows := tables.get("profile"):
        pick = _picker("profile", rows[0])
        profile.headline = pick(rows[0], "headline")
        profile.summary = pick(rows[0], "summary")
    profile.positions = [_position(r, p) for r, p in _each("positions", tables)]
    profile.educations = [_education(r, p) for r, p in _each("education", tables)]
    profile.skills = [
        Skill(name=name)
        for row, pick in _each("skills", tables)
        if (name := pick(row, "name"))
    ]
    return profile


def _each(
    name: str, tables: dict[str, list[dict[str, str]]]
) -> Iterator[tuple[dict[str, str], _Pick]]:
    """Every row of one table, with a reader bound to that table's headers."""
    rows = tables.get(name) or []
    if not rows:
        return
    pick = _picker(name, rows[0])
    for row in rows:
        yield row, pick


def _position(row: dict[str, str], pick: _Pick) -> Position:
    return Position(
        title=pick(row, "title"),
        company=pick(row, "company"),
        description=pick(row, "description"),
        location=pick(row, "location"),
        start=parse_point(pick(row, "start")),
        end=parse_point(pick(row, "end")),
    )


def _education(row: dict[str, str], pick: _Pick) -> Education:
    return Education(
        school=pick(row, "school"),
        degree=pick(row, "degree"),
        field_of_study=pick(row, "field_of_study"),
        description=pick(row, "description"),
        start=parse_point(pick(row, "start")),
        end=parse_point(pick(row, "end")),
    )


class _Pick:
    """Reads one table's fields, having resolved its headers once."""

    def __init__(self, table: str, headers: dict[str, str]):
        self.table = table
        self.of: dict[str, str] = {}
        for field, aliases in COLUMNS[table].items():
            for alias in aliases:
                if alias in headers:
                    self.of[field] = headers[alias]
                    break
        if missing := [f for f in REQUIRED[table] if f not in self.of]:
            raise ExportError(
                f"{table}: this export has no column for "
                f"{', '.join(missing)}.\n"
                f"  Columns found: {', '.join(sorted(headers.values())) or 'none'}\n"
                "  LinkedIn publishes no schema for the archive and does rename "
                "these; please open an issue with the header line."
            )

    def __call__(self, row: dict[str, str], field: str) -> str:
        column = self.of.get(field)
        return (row.get(column) or "").strip() if column else ""


def _picker(table: str, sample: dict[str, str]) -> _Pick:
    return _Pick(table, {_norm(k): k for k in sample if k})


def _norm(header: str) -> str:
    return " ".join(header.replace("_", " ").split()).casefold()


def _tables(path: Path) -> dict[str, list[dict[str, str]]]:
    """Every recognised CSV in the archive, as rows of strings."""
    if not path.exists():
        raise ExportError(f"{path}: no such file or directory")
    sources = _from_zip(path) if zipfile.is_zipfile(path) else _from_dir(path)
    return {name: rows for name, rows in sources.items() if rows}


def _from_zip(path: Path) -> dict[str, list[dict[str, str]]]:
    found: dict[str, list[dict[str, str]]] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if (name := _recognise(member)) is not None:
                    found[name] = _rows(archive.read(member))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExportError(f"{path}: cannot read the export ({exc})") from exc
    return found


def _from_dir(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.is_dir():
        raise ExportError(
            f"{path}: expected the export ZIP, or a directory of its CSVs"
        )
    found: dict[str, list[dict[str, str]]] = {}
    for child in sorted(path.rglob("*.csv")):
        if (name := _recognise(child.name)) is not None:
            try:
                found[name] = _rows(child.read_bytes())
            except OSError as exc:
                raise ExportError(f"{child}: cannot read ({exc})") from exc
    return found


def _recognise(member: str) -> str | None:
    stem = Path(member).stem.casefold().replace("_", " ").strip()
    return stem if stem in FILES else None


def _rows(raw: bytes) -> list[dict[str, str]]:
    """CSV bytes to rows.

    The archive is UTF-8 and sometimes carries a BOM, which would otherwise
    become part of the first header's name and lose that column.
    """
    text = raw.decode("utf-8-sig", errors="replace")
    return [row for row in csv.DictReader(io.StringIO(text)) if any(row.values())]
