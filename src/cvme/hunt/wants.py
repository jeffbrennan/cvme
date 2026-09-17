"""User-authored preferences, grouped into the axes they score.

A preference does not move one number. It moves the axis it belongs to:
whether the work is doable (skills), what the seat is (role), whether the week
is shaped the way I want (culture), or whether the cause is one I want to serve
(domain). Each axis is scored and reported on its own, and a weighted composite
with a gate decides the ranking, so a posting that is wrong on domain cannot
rank at the top on skills alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, get_args

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from cvme.errors import ConfigError
from cvme.jobs.models import JobPosting

#: The axes a preference can score. Skills asks whether the work is doable,
#: role what the seat is, culture how the week is shaped, domain whose cause
#: the engineering serves, and stability whether the employer is built to last.
Axis = Literal["skills", "role", "culture", "domain", "stability"]
AXES: tuple[str, ...] = get_args(Axis)

#: Axis weights for the composite, out of 100. Skills and domain lead because
#: they are the two that decide whether an application is worth an evening.
#: The sum need not be 100; the composite normalises by the total.
DEFAULT_WEIGHTS: dict[str, int] = {
    "skills": 30,
    "role": 15,
    "domain": 30,
    "culture": 10,
    "stability": 15,
}

#: Axes with a floor. A score below its floor caps the composite at that score,
#: so a posting that is wrong where it matters cannot be carried by the rest.
DEFAULT_GATE: dict[str, int] = {"domain": 30, "culture": 25, "stability": 25}


class Rule(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    weight: int = Field(ge=-40, le=40, strict=True)
    reason: str = Field(min_length=1)
    any_of: list[str] = Field(min_length=1)
    #: Which axis this rule moves. Untagged rules keep the historic behaviour
    #: by landing on role, the closest thing to the old single pool.
    axis: Axis = "role"
    scope: Literal["posting", "company", "title", "description"] = "posting"
    when: Literal["present", "absent"] = "present"
    requires_any: list[str] = Field(default_factory=list)
    unless_any: list[str] = Field(default_factory=list)

    @field_validator("any_of", "requires_any", "unless_any")
    @classmethod
    def valid_phrases(cls, phrases: list[str]) -> list[str]:
        from cvme.hunt.score import normalise

        if any(not normalise(phrase) for phrase in phrases):
            raise ValueError("phrases must contain words")
        return phrases

    @field_validator("weight")
    @classmethod
    def nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("weight must be nonzero")
        return value


class Profile(BaseModel):
    model_config = {"extra": "forbid"}

    version: Literal[1] = 1
    max_adjustment: int = Field(default=40, ge=1, le=100, strict=True)
    #: Axis weights for the composite, normalised by their sum. Defaults match
    #: :data:`DEFAULT_WEIGHTS`; a project overrides only what it wants.
    weights: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    #: Axis -> floor. A score below its floor caps the composite at that score.
    gate: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_GATE))
    rules: list[Rule] = Field(default_factory=list)

    @field_validator("weights")
    @classmethod
    def valid_weights(cls, values: dict[str, int]) -> dict[str, int]:
        unknown = sorted(set(values) - set(AXES))
        if unknown:
            raise ValueError(f"unknown axes in weights: {', '.join(unknown)}")
        if any(value <= 0 for value in values.values()):
            raise ValueError("axis weights must be positive")
        return values

    @field_validator("gate")
    @classmethod
    def valid_gate(cls, values: dict[str, int]) -> dict[str, int]:
        unknown = sorted(set(values) - set(AXES))
        if unknown:
            raise ValueError(f"unknown axes in gate: {', '.join(unknown)}")
        if any(not 0 <= value <= 100 for value in values.values()):
            raise ValueError("gate floors must be between 0 and 100")
        return values

    @model_validator(mode="after")
    def unique_names(self) -> Profile:
        if len({rule.name for rule in self.rules}) != len(self.rules):
            raise ValueError("rule names must be unique")
        return self


@dataclass(frozen=True)
class Signal:
    name: str
    weight: int
    reason: str
    evidence: str
    axis: str = "role"


@dataclass(frozen=True)
class Preferences:
    adjustment: int = 0
    signals: list[Signal] = field(default_factory=list)
    max_adjustment: int = 40

    @property
    def by_axis(self) -> dict[str, int]:
        """The sum of weights on each axis, axes with no signals at zero."""
        totals = dict.fromkeys(AXES, 0)
        for signal in self.signals:
            totals[signal.axis] += signal.weight
        return totals

    def signals_on(self, axis: str) -> list[Signal]:
        return [signal for signal in self.signals if signal.axis == axis]


def load(path: Path | None) -> Profile | None:
    if path is None:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0] != "---":
            raise ValueError("expected YAML frontmatter beginning with ---")
        end = lines.index("---", 1)
        return Profile.model_validate(yaml.safe_load("\n".join(lines[1:end])))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: invalid WANTS profile: {exc}") from exc


def evaluate(posting: JobPosting, profile: Profile) -> Preferences:
    from cvme.hunt.score import mentions

    fields = {
        "company": posting.company,
        "title": posting.title,
        "description": posting.description,
    }
    fields["posting"] = "\n".join(fields.values())
    signals: list[Signal] = []
    for rule in profile.rules:
        text = fields[rule.scope]
        # Missing capture data is unknown, not evidence of an absent phrase.
        if not text.strip() or (
            rule.scope == "posting" and not posting.description.strip()
        ):
            continue

        def found(phrases: list[str], text: str = text) -> list[str]:
            return sorted(mentions(text, {p: [p] for p in phrases}))

        required = found(rule.requires_any)
        if (rule.requires_any and not required) or found(rule.unless_any):
            continue
        matched = found(rule.any_of)
        if bool(matched) != (rule.when == "present"):
            continue
        evidence = (
            f"{rule.scope}: " + ", ".join(matched)
            if matched
            else f"{rule.scope}: none mentioned: " + ", ".join(rule.any_of)
        )
        if required:
            evidence += "; also mentions: " + ", ".join(required)
        signals.append(Signal(rule.name, rule.weight, rule.reason, evidence, rule.axis))
    total = sum(signal.weight for signal in signals)
    limit = profile.max_adjustment
    return Preferences(max(-limit, min(limit, total)), signals, limit)
