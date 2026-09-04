"""Tracking applications, so the question "what have I not sent yet" has an answer.

The directory on disk is the artefact; this table is the index over it. It
holds the fit score, the status, and where the directory currently is, which is
what a listing needs and what a filesystem walk would have to re-derive on
every run. It lives in the same database as job discovery, because a posting
found by ``cvme digest`` and an application prepared from it are the same job.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cvme.errors import ConfigError, HuntError
from cvme.hunt.culture import NO_CULTURE, Culture, decode
from cvme.hunt.layout import OPEN
from cvme.hunt.pay import NO_PAY, Pay

#: Columns added after the table first shipped. They are applied to a fresh
#: database and to an existing one by the same code path, so there is one
#: statement of what each column is and no schema that only new users get.
ADDED_COLUMNS = (
    ("salary_low", "INTEGER NOT NULL DEFAULT 0"),
    ("salary_high", "INTEGER NOT NULL DEFAULT 0"),
    ("salary_period", "TEXT NOT NULL DEFAULT ''"),
    ("salary_currency", "TEXT NOT NULL DEFAULT ''"),
    ("salary_text", "TEXT NOT NULL DEFAULT ''"),
    ("wlb", "INTEGER NOT NULL DEFAULT 0"),
    ("wlb_band", "TEXT NOT NULL DEFAULT ''"),
    ("wlb_signals", "TEXT NOT NULL DEFAULT ''"),
    ("arrangement", "TEXT NOT NULL DEFAULT ''"),
)

#: What ``--sort`` accepts, and the columns each key orders by. Sorting is
#: whitelisted rather than interpolated: the key names a plan, it does not
#: become SQL. Each entry is (expression, descending), and the natural
#: direction is the useful one -- best fit, best pay, longest wait.
ORDERS: dict[str, tuple[tuple[str, bool], ...]] = {
    "fit": (("fit", True), ("updated_at", True)),
    "salary": (("salary_high", True), ("salary_low", True)),
    "wlb": (("wlb", True), ("fit", True)),
    "age": (("created_at", False),),
    # Never sent is not "waiting longest", so those rows go to the end
    # whatever the dates say.
    "waiting": (("applied_at = ''", False), ("applied_at", False)),
    "updated": (("updated_at", True),),
    "company": (("company COLLATE NOCASE", False),),
    "title": (("title COLLATE NOCASE", False),),
    "status": (("status COLLATE NOCASE", False), ("fit", True)),
    "versions": (("rounds", True),),
}


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
    pay: Pay = field(default_factory=Pay)
    wlb: int = 0
    wlb_band: str = ""
    wlb_signals: str = ""
    arrangement: str = ""

    @property
    def path(self) -> Path:
        return Path(self.directory)

    @property
    def culture(self) -> Culture:
        """The work-life reading, restored from the row that stored it."""
        return Culture(self.wlb, decode(self.wlb_signals))

    def age_days(self, now: datetime | None = None) -> int:
        """Days since this was prepared."""
        return _days_since(self.created_at, now)

    def waiting_days(self, now: datetime | None = None) -> int:
        """Days since it was sent, or -1 where it has not been."""
        return _days_since(self.applied_at, now) if self.applied_at else -1


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
        self._migrate()
        self.connection.commit()

    def _migrate(self) -> None:
        """Add any column this version knows about and the file does not."""
        have = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(applications)")
        }
        for name, declaration in ADDED_COLUMNS:
            if name not in have:
                self.connection.execute(
                    f"ALTER TABLE applications ADD COLUMN {name} {declaration}"
                )

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
        pay: Pay = NO_PAY,
        culture: Culture = NO_CULTURE,
        arrangement: str = "",
        note: str = "",
    ) -> None:
        """Insert or refresh one application, keeping its status and dates."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self.connection.execute(
            """
            INSERT INTO applications
                (slug, year, url, company, title, location, directory, fit, band,
                 status, rounds, created_at, updated_at, note,
                 salary_low, salary_high, salary_period, salary_currency,
                 salary_text, wlb, wlb_band, wlb_signals, arrangement)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                note = CASE WHEN excluded.note = '' THEN note ELSE excluded.note END,
                salary_low = excluded.salary_low,
                salary_high = excluded.salary_high,
                salary_period = excluded.salary_period,
                salary_currency = excluded.salary_currency,
                salary_text = excluded.salary_text,
                wlb = excluded.wlb,
                wlb_band = excluded.wlb_band,
                wlb_signals = excluded.wlb_signals,
                arrangement = excluded.arrangement
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
                *_conditions(pay, culture, arrangement),
            ),
        )
        self.connection.commit()

    def set_conditions(
        self, slug: str, *, pay: Pay, culture: Culture, arrangement: str
    ) -> None:
        """Refresh what the posting says about pay and hours, nothing else.

        Separate from :meth:`record` because re-reading a posting that is
        already on disk is not a new version of the application, and must not
        touch the fit, the status, or the dates.
        """
        self.connection.execute(
            """UPDATE applications SET
                   salary_low = ?, salary_high = ?, salary_period = ?,
                   salary_currency = ?, salary_text = ?,
                   wlb = ?, wlb_band = ?, wlb_signals = ?, arrangement = ?
               WHERE slug = ?""",
            (*_conditions(pay, culture, arrangement), slug),
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

    def select(
        self,
        statuses: list[str] | None = None,
        *,
        order: str = "fit",
        reverse: bool = False,
    ) -> list[Application]:
        """Applications in one of the orders worth working in, best first."""
        sql = "SELECT * FROM applications"
        params: tuple[str, ...] = ()
        if statuses:
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params = tuple(statuses)
        sql += f" ORDER BY {order_by(order, reverse)}"
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


def check_order(key: str) -> str:
    """Validate a sort key. A typo is bad input, not a broken hunt."""
    if key not in ORDERS:
        raise ConfigError(f"unknown sort '{key}'; use one of: {', '.join(ORDERS)}")
    return key


def order_by(key: str, reverse: bool = False) -> str:
    """The ORDER BY clause for one whitelisted sort key."""
    clauses = [
        f"{column} {'DESC' if descending != reverse else 'ASC'}"
        for column, descending in ORDERS[check_order(key)]
    ]
    return ", ".join([*clauses, "slug ASC"])


def _conditions(pay: Pay, culture: Culture, arrangement: str) -> tuple[object, ...]:
    return (
        pay.low,
        pay.high,
        pay.period,
        pay.currency,
        pay.stated,
        culture.score,
        culture.band,
        culture.encode(),
        arrangement,
    )


def _days_since(stamp: str, now: datetime | None = None) -> int:
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return 0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, ((now or datetime.now(UTC)) - when).days)


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
        pay=Pay(
            low=row["salary_low"],
            high=row["salary_high"],
            period=row["salary_period"],
            currency=row["salary_currency"],
            stated=row["salary_text"],
        ),
        wlb=row["wlb"],
        wlb_band=row["wlb_band"],
        wlb_signals=row["wlb_signals"],
        arrangement=row["arrangement"],
    )
