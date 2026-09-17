"""Company stability, researched rather than read from the posting.

A posting does not state whether the employer is shrinking, unprofitable, or
turning over its executives, so stability cannot be read off the text the way
vocabulary is. Somebody has to go and find it. That somebody is a language
model, because the sources are scattered across news, filings, review sites,
and press releases, and no scraper survives them all.

But the model does not produce the number. Asking a model for a rating gives a
number that reads well and cannot be checked, which is the failure the rest of
the fit design exists to avoid. So the model produces a dossier of typed,
sourced facts, and this module computes the score from them by a fixed rule.
Every point traces to a cited event, and the whole thing can be recomputed from
the dossier alone.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal, get_args

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from cvme.errors import CvmeError


class StabilityError(CvmeError):
    exit_code = 6


#: The closed vocabulary a dossier may use. An unknown type is rejected rather
#: than ignored, so a researcher that invents a category is told to stop rather
#: than quietly having its finding dropped.
SignalType = Literal[
    "layoff",
    "headcount_decline",
    "headcount_growth",
    "not_profitable",
    "profitable",
    "exec_departure",
    "exec_hire",
    "exec_turnover",
    "leadership_continuity",
    "leadership_reset",
    "funding_early_stage",
    "funding_down_round",
    "funding_up_round",
    "ownership_public",
    "ownership_venture",
    "ownership_private_equity",
    "ownership_nonprofit",
    "ownership_government",
    "reviews_poor",
    "reviews_strong",
    "short_history",
    "long_history",
    "stable_workforce",
]

#: Whether a signal describes the whole employer or the data and engineering
#: organisation the seat sits in. A train operator's churn says nothing about
#: a data platform team, so team-scoped evidence is preferred and a whole-
#: company figure is discounted when only that is available.
SignalScope = Literal["company", "team"]

#: The job-seeker's own disposition toward an employer, written by hand rather
#: than researched. A verdict never moves the score: stability is what the
#: evidence shows, the verdict is what the reader decided about it. The closed
#: set keeps verdicts comparable across dossiers, which is the point of keeping
#: them in frontmatter instead of prose.
Verdict = Literal["interested", "uninterested", "undecided"]

SIGNAL_TYPES: tuple[str, ...] = get_args(SignalType)

#: Types where company scope is a weaker signal than team scope. Ownership,
#: profitability and age describe the whole employer and are not scoped.
SCOPED_TYPES: frozenset[str] = frozenset(
    {
        "layoff",
        "headcount_decline",
        "headcount_growth",
        "exec_departure",
        "exec_hire",
        "exec_turnover",
        "leadership_continuity",
        "leadership_reset",
        "reviews_poor",
        "reviews_strong",
        "stable_workforce",
    }
)

#: Senior people leaving. Departures are the instability; the appointments that
#: replace them are a separate signal, because a wave of departures and the
#: hires that follow are not the same event and should not net to nothing.
#: ``exec_turnover`` is the earlier name for a departure and still parses.
DEPARTURE_TYPES: frozenset[str] = frozenset({"exec_departure", "exec_turnover"})

#: A whole-company figure counts this fraction of a team-scoped one.
DEFAULT_COMPANY_SCOPE_FACTOR = 0.6

#: No single signal type may move the score more than this in either
#: direction, so three layoff rounds do not outweigh everything else.
DEFAULT_MAX_PER_TYPE = 12

#: The smallest leadership exodus worth scoring. Below this it is ordinary
#: churn, and scoring it made stable institutions read as brittle.
DEFAULT_EXEC_TURNOVER_MIN = 3
#: Where stability sits when no dossier has been researched. Neutral, not a
#: compliment: an unresearched employer is unknown, and the score says so by
#: staying at the baseline with no signals behind it.
BASELINE = 50

#: A signal older than this many years counts at half weight, because a layoff
#: five years ago says less about the employer now than one last quarter.
HORIZON_YEARS = 3

#: Bands, read the way the other axes are: a strong score is a durable
#: employer, a brittle one is mid-change.
STABLE = 65
BRITTLE = 40

#: Points each signal type is worth, before recency decay. Negative is an
#: employer showing instability, positive is evidence of durability. Override
#: per project under ``[stability.weights]``.
DEFAULT_WEIGHTS: dict[str, int] = {
    "layoff": -10,
    "headcount_decline": -8,
    "headcount_growth": 6,
    "not_profitable": -5,
    "profitable": 8,
    "exec_departure": -8,
    "exec_hire": 3,
    "exec_turnover": -8,
    "leadership_continuity": 5,
    "leadership_reset": -8,
    "funding_early_stage": -10,
    "funding_down_round": -8,
    "funding_up_round": 5,
    "ownership_public": 10,
    "ownership_venture": -6,
    "ownership_private_equity": -6,
    "ownership_nonprofit": 8,
    "ownership_government": 10,
    "reviews_poor": -6,
    "reviews_strong": 6,
    "short_history": -5,
    "long_history": 8,
    "stable_workforce": 8,
}

_FRONTMATTER = re.compile(r"^---\s*$")
_YEAR = re.compile(r"(?:19|20)\d{2}")


def _as_text(value: object) -> object:
    """YAML turns a bare year into an int and an ISO date into a date."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    return value


class Signal(BaseModel):
    """One researched fact, with the source it came from."""

    model_config = {"extra": "forbid"}

    type: SignalType
    source: str = Field(min_length=1)
    scope: SignalScope = "company"
    date: str = ""
    period: str = ""
    count: int | None = None
    change_pct: float | None = None
    detail: str = ""

    @field_validator("date", "period", mode="before")
    @classmethod
    def _clean_dates(cls, value: object) -> object:
        return _as_text(value)


class Dossier(BaseModel):
    """A company's researched stability signals, as written by the agent.

    The verdict fields are the one part written by the job-seeker rather than
    researched, so they carry no source and are excluded from scoring.
    """

    model_config = {"extra": "forbid"}

    company: str = Field(min_length=1)
    researched: str = Field(min_length=1)
    verdict: Verdict | None = None
    verdict_reason: str = ""
    verdict_date: str = ""
    signals: list[Signal] = Field(default_factory=list)
    notes: str = ""

    @field_validator("researched", "verdict_date", mode="before")
    @classmethod
    def _clean_researched(cls, value: object) -> object:
        return _as_text(value)

    @field_validator("verdict", mode="before")
    @classmethod
    def _clean_verdict(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold()
        return value


@dataclass(frozen=True)
class Researched:
    """A signal after scoring: what it was, and what it was worth."""

    type: str
    points: int
    source: str
    detail: str = ""


@dataclass(frozen=True)
class Stability:
    """A computed stability score and the facts that moved it."""

    company: str = ""
    score: int = BASELINE
    researched: str = ""
    verdict: str = ""
    verdict_reason: str = ""
    signals: list[Researched] = field(default_factory=list)

    @property
    def known(self) -> bool:
        """Whether a dossier exists. No dossier is unknown, not stable."""
        return bool(self.researched)

    @property
    def band(self) -> str:
        if not self.known:
            return "unresearched"
        if self.score >= STABLE:
            return "stable"
        if self.score >= BRITTLE:
            return "mixed"
        return "brittle"

    @property
    def sources(self) -> list[str]:
        return sorted({signal.source for signal in self.signals})


UNKNOWN = Stability()


def slug(company: str) -> str:
    """The dossier filename for a company."""
    return re.sub(r"[^a-z0-9]+", "-", company.casefold()).strip("-")


def parse(text: str) -> Dossier:
    """Read a dossier's frontmatter into the typed model."""
    lines = text.splitlines()
    if not lines or not _FRONTMATTER.match(lines[0]):
        raise StabilityError("expected YAML frontmatter beginning with ---")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise StabilityError("frontmatter is not closed") from exc
    try:
        return Dossier.model_validate(yaml.safe_load("\n".join(lines[1:end])))
    except (yaml.YAMLError, ValidationError) as exc:
        raise StabilityError(str(exc)) from exc


def _year(value: str) -> int | None:
    found = _YEAR.search(value or "")
    return int(found.group(0)) if found else None


def _decay(signal: Signal, today: date, horizon: int) -> float:
    year = _year(signal.date) or _year(signal.period)
    if year is None:
        return 1.0
    return 1.0 if today.year - year <= horizon else 0.5


def score(
    dossier: Dossier,
    *,
    weights: dict[str, int] | None = None,
    today: date | None = None,
    horizon: int = HORIZON_YEARS,
    max_per_type: int = DEFAULT_MAX_PER_TYPE,
    exec_turnover_min: int = DEFAULT_EXEC_TURNOVER_MIN,
    company_scope_factor: float = DEFAULT_COMPANY_SCOPE_FACTOR,
) -> Stability:
    """Compute a stability score from a dossier, once per cited signal.

    Three rules keep a real finding from swamping the number. A whole-company
    figure is discounted when the signal is one that is more meaningful at
    team scope, so operational churn does not read as data-team churn. No one
    signal type can move the score past ``max_per_type``, so repeated layoff
    rounds do not. And profitability is dropped when the employer is a
    government body or a nonprofit, where profit is not the relevant measure.
    """
    table = dict(DEFAULT_WEIGHTS)
    table.update(weights or {})
    today = today or date.today()
    kinds = {signal.type for signal in dossier.signals}
    noncommercial = bool(kinds & {"ownership_government", "ownership_nonprofit"})
    running: dict[str, float] = {}
    total = float(BASELINE)
    researched: list[Researched] = []
    for signal in dossier.signals:
        kind = "exec_departure" if signal.type == "exec_turnover" else signal.type
        if kind == "not_profitable" and noncommercial:
            continue
        if kind in DEPARTURE_TYPES and (signal.count or 0) < exec_turnover_min:
            continue
        points = table.get(kind, 0)
        if not points:
            continue
        worth = points * _decay(signal, today, horizon)
        if kind in SCOPED_TYPES and signal.scope == "company":
            worth *= company_scope_factor
        allowed = max_per_type - abs(running.get(kind, 0.0))
        capped = math.copysign(min(abs(worth), max(allowed, 0.0)), worth)
        running[kind] = running.get(kind, 0.0) + capped
        rounded = round(capped)
        total += rounded
        researched.append(
            Researched(
                kind,
                rounded,
                signal.source,
                signal.detail or signal.period or signal.date,
            )
        )
    return Stability(
        company=dossier.company,
        score=max(0, min(100, round(total))),
        researched=dossier.researched,
        verdict=dossier.verdict or "",
        verdict_reason=dossier.verdict_reason,
        signals=researched,
    )


def load(
    directory: Path,
    company: str,
    *,
    weights: dict[str, int] | None = None,
    today: date | None = None,
    horizon: int = HORIZON_YEARS,
    max_per_type: int = DEFAULT_MAX_PER_TYPE,
    exec_turnover_min: int = DEFAULT_EXEC_TURNOVER_MIN,
    company_scope_factor: float = DEFAULT_COMPANY_SCOPE_FACTOR,
) -> Stability | None:
    """The dossier score for a company, or None where none has been made.

    A missing dossier is not an error: most companies will not have been
    researched yet. A dossier that exists but does not parse is an error, and
    is raised rather than skipped, because a silently ignored file is how a
    stale or malformed research result gets mistaken for evidence.
    """
    if not company.strip():
        return None
    path = directory / f"{slug(company)}.md"
    if not path.is_file():
        return None
    try:
        dossier = parse(path.read_text(encoding="utf-8"))
    except (OSError, StabilityError) as exc:
        raise StabilityError(f"{path}: {exc}") from exc
    return score(
        dossier,
        weights=weights,
        today=today,
        horizon=horizon,
        max_per_type=max_per_type,
        exec_turnover_min=exec_turnover_min,
        company_scope_factor=company_scope_factor,
    )


def age_days(stability: Stability, today: date | None = None) -> int | None:
    """Days since the dossier was written, or None where there is none."""
    if not stability.researched:
        return None
    try:
        made = date.fromisoformat(stability.researched[:10])
    except ValueError:
        return None
    return ((today or date.today()) - made).days


def summary_line(stability: Stability) -> str:
    """One line for a CLI exit message."""
    if not stability.known:
        return "stability not researched"
    line = f"stability {stability.score}/100 ({stability.band})"
    if stability.verdict:
        line += f", verdict {stability.verdict}"
    return line
