"""Reading pay out of a posting, which is mostly a matter of not being fooled."""

from __future__ import annotations

import pytest

from cvme.hunt.pay import Pay, read


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("Compensation: $150,000 - $190,000 per year", 150_000, 190_000),
        ("USD 120000-150000 per YEAR", 120_000, 150_000),
        ("The range is 150k–190k", 150_000, 190_000),
        ("Base pay $130,000 to $160,000 annually.", 130_000, 160_000),
        ("Salary: up to £95,000 per annum", 95_000, 0),
        ("Equity 0.1%, salary $180,000", 180_000, 0),
    ],
)
def test_a_stated_range_is_read_as_written(text: str, low: int, high: int) -> None:
    found = read(text)
    assert (found.low, found.high) == (low, high)


@pytest.mark.parametrize(
    ("text", "annual"),
    [("$72/hr", 72 * 2080), ("pay is 45.50 an hour", round(45.5 * 2080))],
)
def test_a_rate_is_annualised_so_the_column_compares(text: str, annual: int) -> None:
    assert read(text).low == annual


@pytest.mark.parametrize(
    "text",
    [
        "We need 5+ years of experience and a team of 30 people",
        "We serve over 10,000 patients per year",
        "401k with a 4% match and 25 days of PTO",
        "A role with no numbers in it at all",
    ],
)
def test_a_number_that_is_not_money_is_not_read_as_money(text: str) -> None:
    assert not read(text)


def test_an_implausible_figure_is_discarded_rather_than_reported() -> None:
    assert not read("serving $4,500,000,000 in claims annually")


def test_the_first_source_given_wins() -> None:
    """A posting's own salary field is better evidence than its prose."""
    found = read("USD 200000 per year", "we pay $90,000")
    assert found.low == 200_000


def test_the_currency_survives_into_the_cell() -> None:
    assert read("£80,000 - £100,000 per year").short == "£80k-100k"


def test_an_unread_posting_is_falsey_and_prints_a_dash() -> None:
    assert not Pay()
    assert Pay().short == "-"


def test_the_midpoint_is_what_a_sort_compares() -> None:
    assert Pay(low=150_000, high=190_000).midpoint == 170_000
    assert Pay(low=150_000).midpoint == 150_000
