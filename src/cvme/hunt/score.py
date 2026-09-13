"""How well the corpus answers a posting.

The score is computed, not asked for. A model asked to rate a fit will produce
a number that reads well and cannot be checked, which is the failure `cvme
verify` exists to catch elsewhere; a number derived from term overlap can be
shown its own working, and the working -- which requirements are answered and
which are not -- is the part worth reading.

Weighting is by mention count. A posting that names Spark six times and Go
once is not asking for those equally, and its own repetition is the only
statement of priority it makes.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from cvme.config import SearchConfig
from cvme.hunt.wants import (
    AXES,
    DEFAULT_GATE,
    DEFAULT_WEIGHTS,
    Preferences,
    Profile,
)
from cvme.hunt.wants import evaluate as evaluate_wants
from cvme.jobs.models import JobPosting

if TYPE_CHECKING:
    from cvme.hunt.culture import Culture

LEXICON_PATH = Path(__file__).parent / "lexicon.toml"

#: Where domain sits when the posting says nothing about the cause it serves.
#: Not a compliment: domain rules move it up for care work and down for the
#: industries being avoided.
DOMAIN_BASELINE = 50

_NON_WORD = re.compile(r"[^a-z0-9+#]+")
_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:or more\s*)?year", re.IGNORECASE
)
_WORD_YEARS = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+years",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip

#: Points available per component. Skills dominate because they are the only
#: part measured against evidence rather than against a preference list.
WEIGHTS = {"skills": 60, "title": 15, "experience": 15, "location": 10}


@dataclass(frozen=True)
class Requirement:
    """One lexicon term the posting asks for."""

    term: str
    category: str
    mentions: int
    covered: bool


@dataclass(frozen=True)
class Component:
    name: str
    earned: float
    possible: int
    detail: str


@dataclass(frozen=True)
class Fit:
    """A composite out of 100, the axes under it, and everything that moved them."""

    score: int
    components: list[Component] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    preferences: Preferences | None = None
    axes: dict[str, int] = field(default_factory=dict)
    weights: dict[str, int] = field(default_factory=dict)
    gate: dict[str, int] = field(default_factory=dict)
    gate_hits: list[str] = field(default_factory=list)

    @property
    def band(self) -> str:
        if self.blockers:
            return "blocked"
        if self.score >= 75:
            return "strong"
        if self.score >= 55:
            return "fair"
        if self.score >= 35:
            return "thin"
        return "weak"

    @property
    def matched(self) -> list[Requirement]:
        return [r for r in self.requirements if r.covered]

    @property
    def missing(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.covered]

    def axis(self, name: str) -> int:
        return self.axes.get(name, 0)


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def _ratio(earned: float, possible: int) -> int:
    return round(100 * earned / possible) if possible else 0


def load_lexicon(extra: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """Canonical term -> spellings, flattened across categories."""
    data = tomllib.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    terms = {
        term: list(aliases)
        for category in data.values()
        for term, aliases in category.items()
    }
    for term, aliases in (extra or {}).items():
        terms.setdefault(term, [])
        terms[term] = sorted({*terms[term], *aliases, term})
    return terms


def categories() -> dict[str, str]:
    """Canonical term -> the category it was declared under."""
    data = tomllib.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    return {term: category for category, terms in data.items() for term in terms}


def normalise(text: str) -> list[str]:
    return [token for token in _NON_WORD.sub(" ", text.casefold()).split() if token]


def _ngrams(tokens: list[str], width: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for size in range(1, width + 1):
        for start in range(len(tokens) - size + 1):
            counts[" ".join(tokens[start : start + size])] += 1
    return counts


def mentions(text: str, lexicon: dict[str, list[str]]) -> dict[str, int]:
    """How many times each lexicon term appears, counted over whole tokens."""
    tokens = normalise(text)
    width = max(
        (len(normalise(alias)) for aliases in lexicon.values() for alias in aliases),
        default=1,
    )
    counts = _ngrams(tokens, width)
    found: dict[str, int] = {}
    for term, aliases in lexicon.items():
        total = sum(counts.get(" ".join(normalise(alias)), 0) for alias in aliases)
        if total:
            found[term] = total
    return found


def years_required(text: str) -> int | None:
    """The most demanding experience requirement stated, in years.

    A range gives its low end, because that is the bar to clear. Across
    several requirements the largest wins, so the score is never flattered by
    a posting that also asks for two years of something incidental.
    """
    numeric = [int(m) for m in _YEARS.findall(text) if int(m) <= 30]
    worded = [_NUMBER_WORDS[m.lower()] for m in _WORD_YEARS.findall(text)]
    found = numeric + worded
    return max(found) if found else None


def years_evidenced(corpus: str) -> int | None:
    """The largest span of experience the corpus itself claims."""
    return years_required(corpus)


def _title_component(posting: JobPosting, search: SearchConfig) -> Component:
    title = " ".join(normalise(posting.title))
    possible = WEIGHTS["title"]
    if not title:
        return Component("title", possible / 2, possible, "no title captured")
    for phrase in search.preferred_titles:
        if (wanted := " ".join(normalise(phrase))) and wanted in title:
            return Component("title", possible, possible, f"matches '{phrase}'")
    if not search.preferred_titles:
        return Component("title", possible / 2, possible, "no preferred titles set")
    return Component(
        "title", 0, possible, f"'{posting.title}' is not a preferred title"
    )


def _location_component(posting: JobPosting, search: SearchConfig) -> Component:
    possible = WEIGHTS["location"]
    remote = posting.remote is True or "remote" in " ".join(normalise(posting.location))
    if remote:
        return Component("location", possible, possible, "remote")
    if not search.locations:
        return Component(
            "location", possible / 2, possible, "no preferred locations set"
        )
    actual = " ".join(normalise(posting.location))
    if not actual:
        return Component("location", possible / 2, possible, "no location captured")
    for place in search.locations:
        if (wanted := " ".join(normalise(place))) and wanted in actual:
            return Component("location", possible, possible, f"in {place}")
    return Component(
        "location", 0, possible, f"{posting.location} is outside your list"
    )


def _experience_component(posting: JobPosting, corpus: str) -> Component:
    possible = WEIGHTS["experience"]
    wanted = years_required(f"{posting.title}\n{posting.description}")
    if wanted is None:
        return Component("experience", possible, possible, "no year requirement stated")
    have = years_evidenced(corpus)
    if have is None:
        return Component(
            "experience", 0, possible, f"asks {wanted}y, corpus states none"
        )
    ratio = min(1.0, have / wanted)
    return Component(
        "experience",
        possible * ratio,
        possible,
        f"asks {wanted}y, corpus evidences {have}y",
    )


def _blockers(posting: JobPosting, search: SearchConfig) -> list[str]:
    """Reasons this posting is not worth a score at all."""
    found: list[str] = []
    title = " ".join(normalise(posting.title))
    haystack = " ".join(
        normalise(f"{posting.title} {posting.company} {posting.description}")
    )
    for phrase in search.excluded_titles:
        if (wanted := " ".join(normalise(phrase))) and wanted in title:
            found.append(f"excluded title: {phrase}")
    for phrase in search.exclude_keywords:
        if (wanted := " ".join(normalise(phrase))) and wanted in haystack:
            found.append(f"excluded keyword: {phrase}")
    for phrase in search.blocked_companies:
        if (wanted := " ".join(normalise(phrase))) and wanted in " ".join(
            normalise(posting.company)
        ):
            found.append(f"blocked company: {phrase}")
    return found


def evaluate(
    posting: JobPosting,
    corpus: str,
    search: SearchConfig,
    *,
    extra_terms: dict[str, list[str]] | None = None,
    wants: Profile | None = None,
    culture: Culture | None = None,
) -> Fit:
    """Score one posting against the text of everything you can claim.

    Four axes are scored 0-100 and reported on their own. Skills is the
    weighted term overlap; role is the title, experience and location
    components plus role preferences; culture is the posting's own reading of
    the hours plus culture preferences; domain starts neutral and moves on the
    cause the engineering serves. A weighted composite ranks the posting, and
    a gated axis caps it, so a wrong domain cannot be carried by a strong
    skills match.
    """
    from cvme.hunt.culture import BASELINE as CULTURE_BASELINE

    lexicon = load_lexicon(extra_terms)
    category_of = categories()
    asked = mentions(f"{posting.title}\n{posting.description}", lexicon)
    held = mentions(corpus, lexicon)

    requirements = sorted(
        (
            Requirement(term, category_of.get(term, "custom"), count, term in held)
            for term, count in asked.items()
        ),
        key=lambda r: (-r.mentions, r.term),
    )

    possible = WEIGHTS["skills"]
    demand = sum(r.mentions for r in requirements)
    if demand:
        covered = sum(r.mentions for r in requirements if r.covered)
        answered = sum(1 for r in requirements if r.covered)
        skills = Component(
            "skills",
            possible * covered / demand,
            possible,
            f"{answered}/{len(requirements)} terms, weighted by mention count",
        )
    else:
        # Nothing in the lexicon appeared: the posting is outside the vocabulary
        # rather than a bad match, and a zero here would be a lie about it.
        skills = Component(
            "skills", possible / 2, possible, "no known terms in the posting"
        )

    title = _title_component(posting, search)
    experience = _experience_component(posting, corpus)
    location = _location_component(posting, search)
    components = [skills, title, experience, location]

    preferences = evaluate_wants(posting, wants) if wants is not None else None
    by_axis = preferences.by_axis if preferences is not None else dict.fromkeys(AXES, 0)
    weights = dict(wants.weights) if wants is not None else dict(DEFAULT_WEIGHTS)
    gate = dict(wants.gate) if wants is not None else dict(DEFAULT_GATE)

    logistics_earned = title.earned + experience.earned + location.earned
    logistics_possible = title.possible + experience.possible + location.possible
    culture_base = culture.score if culture is not None else CULTURE_BASELINE
    axes = {
        "skills": _clamp(_ratio(skills.earned, skills.possible) + by_axis["skills"]),
        "role": _clamp(_ratio(logistics_earned, logistics_possible) + by_axis["role"]),
        "culture": _clamp(culture_base + by_axis["culture"]),
        "domain": _clamp(DOMAIN_BASELINE + by_axis["domain"]),
    }

    blockers = _blockers(posting, search)
    total_weight = sum(weights.get(axis, 0) for axis in AXES) or 1
    composite = round(
        sum(weights.get(axis, 0) * axes[axis] for axis in AXES) / total_weight
    )
    gate_hits: list[str] = []
    if not blockers:
        for axis, floor in gate.items():
            if axes.get(axis, 0) < floor:
                composite = min(composite, axes[axis])
                gate_hits.append(f"{axis} {axes[axis]} below {floor}")
    score = 0 if blockers else max(0, min(100, composite))
    return Fit(
        score,
        components,
        requirements,
        blockers,
        preferences,
        axes,
        weights,
        gate,
        gate_hits,
    )
