"""How the posting describes the week, scored the same way the fit is.

The same argument as :mod:`cvme.hunt.score` applies here and applies harder: a
model asked "what is work-life balance like at this company" will answer, and
the answer is worth nothing. What can be checked is the vocabulary the posting
chose. "996", "wear many hats" and "unlimited PTO" are not neutral descriptions
-- each one reliably predicts something about the hours -- and a posting that
names a four-day week or a bargained contract is making a claim it can be held
to.

So the score is a reading of the advertisement, not of the company. It starts
at :data:`BASELINE`, subtracts what each cost phrase is worth and adds what
each lift is worth, and reports every phrase it found and why that phrase
counts. Where the posting says nothing either way the band is ``unstated``,
because silence is not the same as sixty.

A phrase counts once however many times it appears. Boilerplate repeated in
three sections is one statement about the job, not three, which is the
opposite of how requirements work and the reason this does not reuse the fit
score's weighting.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from cvme.hunt.score import mentions, normalise

LEXICON_PATH = Path(__file__).parent / "culture.toml"

#: Where a posting that says nothing sits. Not a compliment: everything
#: measured here is a departure from it in one direction or the other.
BASELINE = 60


@dataclass(frozen=True)
class Entry:
    """One phrase family, and what finding it is worth."""

    term: str
    weight: int
    says: str
    phrases: list[str]


@dataclass(frozen=True)
class Signal:
    """One phrase family the posting actually used."""

    term: str
    weight: int
    says: str

    @property
    def sign(self) -> str:
        return f"+{self.weight}" if self.weight > 0 else str(self.weight)


@dataclass(frozen=True)
class Culture:
    """A score out of 100 and every phrase that moved it."""

    score: int = BASELINE
    signals: list[Signal] = field(default_factory=list)

    @property
    def band(self) -> str:
        if not self.signals:
            return "unstated"
        if self.score >= 75:
            return "calm"
        if self.score >= 55:
            return "steady"
        if self.score >= 35:
            return "busy"
        return "grind"

    @property
    def costs(self) -> list[Signal]:
        return [s for s in self.signals if s.weight < 0]

    @property
    def lifts(self) -> list[Signal]:
        return [s for s in self.signals if s.weight > 0]

    def encode(self) -> str:
        """The signals as one string, so a row of the table can carry them."""
        return "|".join(f"{s.term}:{s.sign}" for s in self.signals)


#: A posting that has not been read for what it says about the hours.
NO_CULTURE = Culture()


def load(
    extra_costs: dict[str, int] | None = None,
    extra_lifts: dict[str, int] | None = None,
) -> list[Entry]:
    """The packaged lexicon, with anything the project added to it."""
    data = tomllib.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    entries = [
        Entry(
            term=item["term"],
            weight=-abs(item["weight"]) if kind == "cost" else abs(item["weight"]),
            says=item.get("says", ""),
            phrases=list(item.get("phrases", [])) or [item["term"]],
        )
        for kind in ("cost", "lift")
        for item in data.get(kind, [])
    ]
    own = [
        Entry(term, -abs(weight), "your own list", [term])
        for term, weight in (extra_costs or {}).items()
    ] + [
        Entry(term, abs(weight), "your own list", [term])
        for term, weight in (extra_lifts or {}).items()
    ]
    # A project's own weight for a packaged term replaces it rather than
    # stacking with it, so a term is only ever counted once.
    packaged = {entry.term: entry for entry in entries}
    packaged.update({entry.term: entry for entry in own})
    return list(packaged.values())


def _surviving(text: str, entries: list[Entry]) -> set[str]:
    """The phrases the posting used, minus the ones a longer phrase negates.

    "no on call" contains "on call", so a posting that promises the first
    would otherwise be charged for the second. Where one matched phrase
    contains another, only the longer one is believed.
    """
    phrases = {phrase for entry in entries for phrase in entry.phrases}
    found = set(mentions(text, {phrase: [phrase] for phrase in phrases}))
    tokens = {phrase: f" {' '.join(normalise(phrase))} " for phrase in found}
    return {
        phrase
        for phrase, span in tokens.items()
        if not any(
            other != phrase and len(longer) > len(span) and span in longer
            for other, longer in tokens.items()
        )
    }


def evaluate(
    text: str,
    *,
    extra_costs: dict[str, int] | None = None,
    extra_lifts: dict[str, int] | None = None,
) -> Culture:
    """Read one posting for what it says about the hours."""
    entries = load(extra_costs, extra_lifts)
    used = _surviving(text, entries)
    signals = sorted(
        (
            Signal(entry.term, entry.weight, entry.says)
            for entry in entries
            if used.intersection(entry.phrases)
        ),
        key=lambda s: (s.weight, s.term),
    )
    total = BASELINE + sum(signal.weight for signal in signals)
    return Culture(max(0, min(100, total)), signals)


def decode(encoded: str) -> list[Signal]:
    """Signals read back from a stored row, with their reasons restored."""
    says = {entry.term: entry.says for entry in load()}
    signals: list[Signal] = []
    for part in filter(None, encoded.split("|")):
        term, _, weight = part.rpartition(":")
        if not term or not weight.lstrip("+-").isdigit():
            continue
        signals.append(Signal(term, int(weight), says.get(term, "")))
    return sorted(signals, key=lambda s: (s.weight, s.term))


def summary_line(culture: Culture) -> str:
    """The one line worth putting in a report or a CLI message."""
    if not culture.signals:
        return "work-life: the posting says nothing either way"
    worst = culture.costs[:3]
    best = culture.lifts[-3:]
    parts = [f"work-life {culture.score}/100 ({culture.band})"]
    if worst:
        parts.append(f"costs: {', '.join(s.term for s in worst)}")
    if best:
        parts.append(f"lifts: {', '.join(s.term for s in best)}")
    return "; ".join(parts)
