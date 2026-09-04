"""The index over the hunt directories: what it stores, and how it orders it."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cvme.errors import ConfigError
from cvme.hunt.culture import Culture, Signal
from cvme.hunt.pay import Pay
from cvme.hunt.store import ADDED_COLUMNS, ApplicationStore, order_by

#: The table as it shipped before pay and the work-life score existed.
ORIGINAL = """
CREATE TABLE applications (
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


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / ".cvme" / "jobs.sqlite3"


def add(store: ApplicationStore, slug: str, **fields: object) -> None:
    defaults = {
        "year": "2026",
        "url": f"https://example.com/{slug}",
        "company": slug.title(),
        "title": "Data Engineer",
        "location": "Remote",
        "directory": Path("/tmp") / slug,
        "fit": 50,
        "band": "fair",
        "rounds": 1,
    }
    store.record(slug=slug, **{**defaults, **fields})  # type: ignore[arg-type]


def test_an_older_database_gains_the_new_columns(database: Path) -> None:
    database.parent.mkdir(parents=True)
    old = sqlite3.connect(database)
    old.execute(ORIGINAL)
    old.execute(
        "INSERT INTO applications (slug, year, directory, created_at, updated_at)"
        " VALUES ('01_acme', '2026', '/tmp/01_acme', '2026-01-01', '2026-01-01')"
    )
    old.commit()
    old.close()

    with ApplicationStore(database) as store:
        entry = store.select(None)[0]
        assert entry.slug == "01_acme", "the row survives the migration"
        assert not entry.pay
        assert entry.wlb_band == ""
        columns = {
            row[1]
            for row in store.connection.execute("PRAGMA table_info(applications)")
        }
    assert {name for name, _ in ADDED_COLUMNS} <= columns


def test_what_the_posting_said_survives_the_round_trip(database: Path) -> None:
    culture = Culture(48, [Signal("unlimited pto", -12, "no accrued balance")])
    with ApplicationStore(database) as store:
        add(
            store,
            "01_acme",
            pay=Pay(150_000, 190_000, "year", "$", "$150,000 - $190,000"),
            culture=culture,
            arrangement="hybrid",
        )
        entry = store.select(None)[0]

    assert entry.pay.short == "$150k-190k"
    assert entry.pay.stated == "$150,000 - $190,000"
    assert entry.arrangement == "hybrid"
    assert entry.wlb == 48 and entry.wlb_band == "busy"
    assert [s.term for s in entry.culture.signals] == ["unlimited pto"]


def test_conditions_are_refreshed_without_touching_the_fit(database: Path) -> None:
    with ApplicationStore(database) as store:
        add(store, "01_acme", fit=71, band="fair")
        store.set_conditions(
            "01_acme",
            pay=Pay(low=120_000),
            culture=Culture(30, []),
            arrangement="remote",
        )
        entry = store.select(None)[0]
    assert (entry.fit, entry.band) == (71, "fair")
    assert entry.pay.low == 120_000
    assert entry.wlb == 30


def test_each_sort_puts_the_one_to_work_on_first(database: Path) -> None:
    with ApplicationStore(database) as store:
        add(store, "01_low", fit=90, pay=Pay(90_000, 100_000), culture=Culture(20, []))
        add(
            store, "02_high", fit=40, pay=Pay(180_000, 220_000), culture=Culture(90, [])
        )
        assert [e.slug for e in store.select(order="fit")] == ["01_low", "02_high"]
        assert [e.slug for e in store.select(order="salary")] == ["02_high", "01_low"]
        assert [e.slug for e in store.select(order="wlb")] == ["02_high", "01_low"]
        assert [e.slug for e in store.select(order="wlb", reverse=True)] == [
            "01_low",
            "02_high",
        ]


def test_an_unknown_sort_is_refused_rather_than_interpolated() -> None:
    with pytest.raises(ConfigError):
        order_by("fit; DROP TABLE applications")


def test_age_counts_from_when_it_was_prepared(database: Path) -> None:
    with ApplicationStore(database) as store:
        add(store, "01_acme")
        entry = store.select(None)[0]
    later = datetime.now(UTC) + timedelta(days=9)
    assert entry.age_days(later) == 9
    assert entry.waiting_days(later) == -1, "it has not been sent"
