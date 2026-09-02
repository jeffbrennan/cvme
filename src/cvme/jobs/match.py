"""Deterministic filtering and ranking for discovered jobs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cvme.config import SearchConfig
from cvme.jobs.models import JobPosting

_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Match:
    accepted: bool
    score: int
    reason: str


def normalise(value: str) -> str:
    return _NON_WORD.sub(" ", value.casefold()).strip()


def blocked_company(company: str, config: SearchConfig) -> str | None:
    actual = normalise(company)
    for blocked in config.blocked_companies:
        wanted = normalise(blocked)
        if wanted and wanted in actual:
            return f"blocked company: {blocked}"
    return None


def evaluate(posting: JobPosting, config: SearchConfig) -> Match:
    if reason := blocked_company(posting.company, config):
        return Match(False, 0, reason)

    title = normalise(posting.title)
    haystack = normalise(
        " ".join(
            (posting.title, posting.company, posting.location, posting.description)
        )
    )
    for phrase in config.excluded_titles:
        if (wanted := normalise(phrase)) and wanted in title:
            return Match(False, 0, f"excluded title: {phrase}")
    for phrase in config.exclude_keywords:
        if (wanted := normalise(phrase)) and wanted in haystack:
            return Match(False, 0, f"excluded keyword: {phrase}")

    is_remote = posting.remote is True or "remote" in normalise(posting.location)
    if config.remote_only and not is_remote:
        return Match(False, 0, "not remote")
    if config.locations and not is_remote:
        allowed = [normalise(location) for location in config.locations]
        actual = normalise(posting.location)
        if not any(location in actual for location in allowed if location):
            return Match(
                False, 0, f"location not allowed: {posting.location or 'unknown'}"
            )

    score = 0
    reasons: list[str] = []
    for phrase in config.preferred_titles:
        if (wanted := normalise(phrase)) and wanted in title:
            score += 3
            reasons.append(f"title {phrase}")
    for phrase in config.include_keywords:
        if (wanted := normalise(phrase)) and wanted in haystack:
            score += 1
            reasons.append(phrase)
    if config.locations and (
        is_remote
        or any(
            normalise(place) in normalise(posting.location)
            for place in config.locations
        )
    ):
        score += 1
        reasons.append("preferred location")
    if is_remote:
        score += 1
        reasons.append("remote")

    if score < config.minimum_score:
        return Match(False, score, f"score {score} below {config.minimum_score}")
    return Match(True, score, ", ".join(reasons) or "passes all filters")
