"""Persistent state for job discovery and digest decisions."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cvme.jobs.discovery import DiscoveredJob


@dataclass(frozen=True)
class StoredJob:
    key: str
    url: str
    source: str
    title: str
    company: str
    location: str
    status: str


class JobStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                company TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'discovered',
                reason TEXT NOT NULL DEFAULT '',
                score INTEGER,
                posting_path TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> JobStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def add(self, jobs: Iterable[DiscoveredJob]) -> tuple[int, int]:
        now = datetime.now(UTC).isoformat()
        added = seen = 0
        for job in jobs:
            existing = self.connection.execute(
                "SELECT 1 FROM jobs WHERE job_key = ?", (job.key,)
            ).fetchone()
            if existing:
                seen += 1
                self.connection.execute(
                    """UPDATE jobs SET last_seen = ?,
                       title = CASE WHEN title = '' THEN ? ELSE title END,
                       company = CASE WHEN company = '' THEN ? ELSE company END,
                       location = CASE WHEN location = '' THEN ? ELSE location END
                       WHERE job_key = ?""",
                    (now, job.title, job.company, job.location, job.key),
                )
            else:
                added += 1
                self.connection.execute(
                    """INSERT INTO jobs
                       (job_key, url, source, title, company, location,
                        first_seen, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job.key,
                        job.url,
                        job.source,
                        job.title,
                        job.company,
                        job.location,
                        now,
                        now,
                    ),
                )
        self.connection.commit()
        return added, seen

    def pending(self, limit: int | None = None) -> list[StoredJob]:
        sql = "SELECT * FROM jobs WHERE status = 'discovered' ORDER BY first_seen"
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return [self._stored(row) for row in self.connection.execute(sql, params)]

    def retry_errors(self) -> int:
        cursor = self.connection.execute(
            "UPDATE jobs SET status = 'discovered', error = '' WHERE status = 'error'"
        )
        self.connection.commit()
        return cursor.rowcount

    def decide(
        self,
        key: str,
        *,
        status: str,
        title: str = "",
        company: str = "",
        location: str = "",
        reason: str = "",
        score: int | None = None,
        posting_path: str = "",
        error: str = "",
    ) -> None:
        self.connection.execute(
            """UPDATE jobs SET status = ?, title = ?, company = ?, location = ?,
               reason = ?, score = ?, posting_path = ?, error = ?
               WHERE job_key = ?""",
            (
                status,
                title,
                company,
                location,
                reason,
                score,
                posting_path,
                error,
                key,
            ),
        )
        self.connection.commit()

    def counts(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, count(*) AS count FROM jobs GROUP BY status"
        )
        return {row["status"]: row["count"] for row in rows}

    @staticmethod
    def _stored(row: sqlite3.Row) -> StoredJob:
        return StoredJob(
            row["job_key"],
            row["url"],
            row["source"],
            row["title"],
            row["company"],
            row["location"],
            row["status"],
        )
