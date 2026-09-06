"""User-authored preferences, applied once per rule to the overall fit."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from cvme.errors import ConfigError
from cvme.jobs.models import JobPosting


class Rule(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    weight: int = Field(ge=-40, le=40, strict=True)
    reason: str = Field(min_length=1)
    any_of: list[str] = Field(min_length=1)
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
    rules: list[Rule] = Field(default_factory=list)

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


@dataclass(frozen=True)
class Preferences:
    adjustment: int = 0
    signals: list[Signal] = field(default_factory=list)
    max_adjustment: int = 40


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
        signals.append(Signal(rule.name, rule.weight, rule.reason, evidence))
    total = sum(signal.weight for signal in signals)
    limit = profile.max_adjustment
    return Preferences(max(-limit, min(limit, total)), signals, limit)
