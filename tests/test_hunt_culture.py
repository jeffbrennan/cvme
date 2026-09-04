"""The work-life score, which is a reading of the advertisement and says so."""

from __future__ import annotations

from cvme.hunt.culture import BASELINE, decode, evaluate, load, summary_line

GRIM = """
We are a fast-paced team of rockstars. You will wear many hats, thrive under
pressure, and do whatever it takes. Unlimited PTO. We are like a family here.
"""

DECENT = """
We work a four day work week with core hours. No on call. Paid parental leave,
25 days of PTO, a company shutdown in December, and blameless postmortems.
"""


def test_a_grim_posting_scores_below_a_decent_one() -> None:
    assert evaluate(GRIM).score < BASELINE < evaluate(DECENT).score


def test_every_phrase_that_moved_the_score_is_named() -> None:
    found = {signal.term for signal in evaluate(GRIM).signals}
    assert {"rockstar", "many hats", "unlimited pto", "family"} <= found
    assert all(signal.says for signal in evaluate(GRIM).signals)


def test_a_posting_that_says_nothing_is_unstated_rather_than_average() -> None:
    culture = evaluate("A data engineering role building batch pipelines.")
    assert culture.score == BASELINE
    assert culture.band == "unstated"
    assert "says nothing" in summary_line(culture)


def test_a_phrase_repeated_counts_once() -> None:
    once = evaluate("A fast paced team.")
    thrice = evaluate("Fast paced. We are fast paced. Did we say fast paced?")
    assert once.score == thrice.score


def test_a_promise_is_not_charged_for_the_thing_it_promises_to_avoid() -> None:
    """ "no on call" contains "on call", and only the longer phrase is believed."""
    culture = evaluate("There is no on call and no crunch on this team.")
    assert {signal.term for signal in culture.signals} == {
        "no on call",
        "sustainable pace",
    }
    assert culture.score > BASELINE


def test_matching_is_on_whole_tokens() -> None:
    culture = evaluate("A learning environment with a leaning towards Python.")
    assert "lean team" not in {signal.term for signal in culture.signals}


def test_a_project_can_add_its_own_and_override_a_packaged_weight() -> None:
    culture = evaluate(
        "Relocation required. Unlimited PTO.",
        extra_costs={"relocation required": 20, "unlimited pto": 2},
    )
    weights = {signal.term: signal.weight for signal in culture.signals}
    assert weights == {"relocation required": -20, "unlimited pto": -2}


def test_signals_survive_a_round_trip_through_a_stored_row() -> None:
    culture = evaluate(GRIM)
    restored = decode(culture.encode())
    assert [(s.term, s.weight) for s in restored] == [
        (s.term, s.weight) for s in culture.signals
    ]
    assert all(signal.says for signal in restored)


def test_the_score_is_bounded() -> None:
    assert evaluate(GRIM * 3).score >= 0
    assert evaluate(DECENT * 3).score <= 100


def test_every_packaged_entry_is_complete() -> None:
    for entry in load():
        assert entry.phrases, entry.term
        assert entry.says, entry.term
        assert entry.weight != 0, entry.term
