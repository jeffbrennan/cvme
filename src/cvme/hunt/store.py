"""Tracking applications, so the question "what have I not sent yet" has an answer.

The directory on disk is the artefact; this table is the index over it. It
holds the fit score, the status, and where the directory currently is, which is
what a listing needs and what a filesystem walk would have to re-derive on
every run. It lives in the same database as job discovery, because a posting
found by ``cvme digest`` and an application prepared from it are the same job.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cvme.errors import HuntError
from cvme.hunt.layout import OPEN


@dataclass(frozen=True)
class Round:
    """One pass of document generation for a hunt."""

    slug: str
    number: int
    created_at: str
    documents: str
    pages: str
    fit: int
    changes: str
    note: str


@dataclass(frozen=True)
class Application:
    slug: str
    year: str
    url: str
    company: str
    title: str
    location: str
    directory: str
    fit: int
    band: str
    status: str
    rounds: int
    created_at: str
    updated_at: str
    applied_at: str
    note: str

    @property
    def path(self) -> Path:
        return Path(self.directory)


class ApplicationStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                slug TEXT PRIMARY KEY,
                year TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                company TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                directory TEXT NOT NULL,
                fit INTEGER NOT NULL DEFAULT 0,
                band TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'prepared',
                rounds INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rounds (
                slug TEXT NOT NULL,
                number INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                documents TEXT NOT NULL DEFAULT '',
                pages TEXT NOT NULL DEFAULT '',
                fit INTEGER NOT NULL DEFAULT 0,
                changes TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (slug, number)
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ApplicationStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def record(
        self,
        *,
        slug: str,
        year: str,
        url: str,
        company: str,
        title: str,
        location: str,
        directory: Path,
        fit: int,
        band: str,
        rounds: int,
        note: str = "",
    ) -> None:
        """Insert or refresh one application, keeping its status and dates."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self.connection.execute(
            """
            INSERT INTO applications
                (slug, year, url, company, title, location, directory, fit, band,
                 status, rounds, created_at, updated_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                url = excluded.url,
                company = excluded.company,
                title = excluded.title,
                location = excluded.location,
                directory = excluded.directory,
                fit = excluded.fit,
                band = excluded.band,
                rounds = excluded.rounds,
                updated_at = excluded.updated_at,
                note = CASE WHEN excluded.note = '' THEN note ELSE excluded.note END
            """,
            (
                slug,
                year,
                url,
                company,
                title,
                location,
                str(directory),
                fit,
                band,
                OPEN,
                rounds,
                now,
                now,
                note,
            ),
        )
        self.connection.commit()

    def by_url(self, url: str) -> Application | None:
        if not url:
            return None
        row = self.connection.execute(
            "SELECT * FROM applications WHERE url = ? ORDER BY created_at DESC LIMIT 1",
            (url,),
        ).fetchone()
        return _application(row) if row else None

    def get(self, slug: str) -> Application | None:
        row = self.connection.execute(
            "SELECT * FROM applications WHERE slug = ?", (slug,)
        ).fetchone()
        return _application(row) if row else None

    def resolve(self, reference: str) -> Application:
        """Find one application by slug, slug fragment, or company name.

        Typing a full slug is not something anyone will do twice, and a
        fragment is unambiguous in practice; where it is not, say so and list
        what it could have meant rather than guessing.
        """
        if (exact := self.get(reference)) is not None:
            return exact
        pattern = f"%{reference.casefold()}%"
        rows = self.connection.execute(
            """SELECT * FROM applications
               WHERE lower(slug) LIKE ? OR lower(company) LIKE ? OR lower(title) LIKE ?
               ORDER BY created_at DESC""",
            (pattern, pattern, pattern),
        ).fetchall()
        if not rows:
            raise HuntError(f"no application matching '{reference}'")
        if len(rows) > 1:
            names = ", ".join(row["slug"] for row in rows[:6])
            raise HuntError(f"'{reference}' matches {len(rows)} applications: {names}")
        return _application(rows[0])

    def select(self, statuses: list[str] | None = None) -> list[Application]:
        """Applications, best fit first, because that is the order to work in."""
        sql = "SELECT * FROM applications"
        params: tuple[str, ...] = ()
        if statuses:
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params = tuple(statuses)
        sql += " ORDER BY fit DESC, updated_at DESC"
        return [_application(row) for row in self.connection.execute(sql, params)]

    def set_status(
        self, slug: str, status: str, *, directory: Path, note: str = ""
    ) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        applied = now if status == "applied" else ""
        self.connection.execute(
            """UPDATE applications SET status = ?, directory = ?, updated_at = ?,
                   applied_at = CASE WHEN ? = '' THEN applied_at ELSE ? END,
                   note = CASE WHEN ? = '' THEN note ELSE ? END
               WHERE slug = ?""",
            (status, str(directory), now, applied, applied, note, note, slug),
        )
        self.connection.commit()

    def add_round(
        self,
        *,
        slug: str,
        number: int,
        documents: str,
        pages: str,
        fit: int,
        changes: str,
        note: str = "",
    ) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self.connection.execute(
            """INSERT INTO rounds
                   (slug, number, created_at, documents, pages, fit, changes, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(slug, number) DO UPDATE SET
                   created_at = excluded.created_at,
                   documents = excluded.documents,
                   pages = excluded.pages,
                   fit = excluded.fit,
                   changes = excluded.changes,
                   note = excluded.note""",
            (slug, number, now, documents, pages, fit, changes, note),
        )
        self.connection.commit()

    def rounds_for(self, slug: str) -> list[Round]:
        rows = self.connection.execute(
            "SELECT * FROM rounds WHERE slug = ? ORDER BY number", (slug,)
        )
        return [
            Round(
                slug=row["slug"],
                number=row["number"],
                created_at=row["created_at"],
                documents=row["documents"],
                pages=row["pages"],
                fit=row["fit"],
                changes=row["changes"],
                note=row["note"],
            )
            for row in rows
        ]

    def counts(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, count(*) AS count FROM applications GROUP BY status"
        )
        return {row["status"]: row["count"] for row in rows}


def _application(row: sqlite3.Row) -> Application:
    return Application(
        slug=row["slug"],
        year=row["year"],
        url=row["url"],
        company=row["company"],
        title=row["title"],
        location=row["location"],
        directory=row["directory"],
        fit=row["fit"],
        band=row["band"],
        status=row["status"],
        rounds=row["rounds"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        applied_at=row["applied_at"],
        note=row["note"],
    )
