"""Checking the live profile against the source documents.

The comparison is the one in ``diff``, read the other way round. Diffing the
projected profile against the live one gives exactly the three findings an
audit wants, so there is one comparison engine and not two:

======================  =============================================
``diff`` action         Audit finding
======================  =============================================
``add``                 ``missing``  -- in the documents, not on LinkedIn
``update`` / ``set``    ``stale``    -- on LinkedIn, but out of date
``remove``              ``extra``    -- on LinkedIn, not in the documents
======================  =============================================

Only the first two fail by default, and that is a deliberate reading of what a
one-way sync promises. The contract is "everything base.md says is on the
profile", not "the profile says nothing else": a resume drops an old job for
space, and the profile keeping it is correct rather than drift. Endorsed
skills you never listed are the same story. ``--strict`` is for anyone who
wants the profile to be exactly the document and nothing more.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from cvme.errors import CvmeError
from cvme.linkedin.diff import Change, diff
from cvme.linkedin.live import Source
from cvme.linkedin.model import Profile

Severity = Literal["missing", "stale", "extra"]

#: Which finding each diff action becomes, from the audit's point of view.
_FINDING: dict[str, Severity] = {
    "add": "missing",
    "set": "stale",
    "update": "stale",
    "remove": "extra",
}

_EXPLAIN: dict[Severity, str] = {
    "missing": "in your documents, not on LinkedIn",
    "stale": "on LinkedIn, but not what your documents say",
    "extra": "on LinkedIn, not in your documents",
}


class DriftError(CvmeError):
    """The live profile does not match the source documents."""

    exit_code = 9


class Finding(BaseModel):
    """One way in which the profile and the documents disagree."""

    severity: Severity
    change: Change

    @property
    def where(self) -> str:
        change = self.change
        return (
            change.kind if change.action == "set" else f"{change.kind} '{change.label}'"
        )

    def __str__(self) -> str:
        return f"{self.severity:<8}{self.where}"


class Audit(BaseModel):
    """Everything the export and the documents disagree about."""

    findings: list[Finding] = Field(default_factory=list)
    #: The profile as the source reports it, kept so a caller can record it.
    live: Profile = Field(default_factory=Profile)
    #: Where it came from, and what it could vouch for.
    source: Source = Field(default_factory=lambda: Source(profile=Profile()))

    def of(self, *severities: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity in severities]

    def failed(self, *, strict: bool) -> bool:
        wanted: tuple[Severity, ...] = (
            ("missing", "stale", "extra") if strict else ("missing", "stale")
        )
        return bool(self.of(*wanted))

    def lines(self) -> list[str]:
        """The findings as a person reads them, one per line.

        Skills are rolled up per severity rather than listed one to a line.
        A profile behind on skills is behind on a dozen of them at once, and
        twelve lines of "missing skill" bury the one stale position that
        actually needs rewriting.
        """
        out = [str(f) for f in self.findings if f.change.kind != "skill"]
        for severity in ("missing", "stale", "extra"):
            named = sorted(
                f.change.label for f in self.of(severity) if f.change.kind == "skill"
            )
            if named:
                out.append(f"{severity:<8}skills: {', '.join(named)}")
        return out

    def summary(self) -> str:
        if not self.findings:
            return "the profile matches your documents"
        counts = [
            f"{len(self.of(name))} {name}"
            for name in ("missing", "stale", "extra")
            if self.of(name)
        ]
        return ", ".join(counts)


def audit(projected: Profile, source: Source) -> Audit:
    """Compare the documents against what the source says LinkedIn holds.

    Restricted to the parts the source vouches for. A profile PDF prints three
    "Top Skills" and a partial export may hold one table; comparing against
    what such a source never reported would call the whole of it missing,
    which is a fact about the source dressed up as drift in the profile.

    A ``set`` change where LinkedIn holds nothing at all is a missing field
    rather than a stale one: "your headline is out of date" reads badly when
    there is no headline.
    """
    mine = projected.only(source.covers)
    theirs = source.profile.only(source.covers)
    findings = [
        Finding(severity=_severity(change), change=change)
        for change in diff(mine, theirs).changes
    ]
    return Audit(findings=findings, live=source.profile, source=source)


def recordable(
    projected: Profile, source: Source, previous: Profile, *, strict: bool
) -> Profile:
    """The live profile, reduced to the part cvme should consider its own.

    An export carries entries cvme never put there -- the job the resume drops
    for space, the endorsed skill you would not claim in print. Recording them
    verbatim would make every later changeset propose deleting them, and a
    standing instruction to remove something you meant to keep is worse than
    not tracking it at all. So under the default reading they are left out of
    the state, which is the same stance ``audit`` takes in not failing on them.

    ``--strict`` means the profile should be exactly the documents, so there
    the extras are kept and the next changeset does say to remove them.

    Parts the source could not vouch for keep whatever was already recorded.
    A profile PDF says nothing about your skills, and letting it blank them
    would turn "this source does not list skills" into "LinkedIn has none of
    your skills" the moment it was written down.
    """
    live = source.profile
    if not strict:
        mine = {entity.key for entity in (*projected.positions, *projected.educations)}
        skills = {skill.key for skill in projected.skills}
        live = live.model_copy(
            update={
                "positions": [p for p in live.positions if p.key in mine],
                "educations": [e for e in live.educations if e.key in mine],
                "skills": [s for s in live.skills if s.key in skills],
            },
            deep=True,
        )
    kept = live.only(source.covers)
    return kept.model_copy(
        update={
            part: getattr(previous, part)
            for part in Profile.PARTS
            if part not in source.covers
        },
        deep=True,
    )


def _severity(change: Change) -> Severity:
    if change.action == "set" and not change.before:
        return "missing"
    return _FINDING[change.action]


def explain(severity: Severity) -> str:
    return _EXPLAIN[severity]
