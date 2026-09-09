"""What changed between two profiles.

The sync is one-way, so the interesting comparison is never "what does
LinkedIn say" -- it is "what have I written since the last time I pushed".
That makes the diff the centre of the feature rather than a convenience: it is
what turns an edit to one bullet in ``base.md`` into one field to update
instead of a whole profile to overwrite.

Changes are typed rather than textual because the changeset is composed from
the parts: which entity, which of its fields moved, and the before and after
of each. A unified diff would have to be re-parsed to say any of that, and it
would read like a diff rather than like a list of edits to make.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from cvme.linkedin.model import Education, Position, Profile, Skill

Action = Literal["set", "add", "update", "remove"]
Kind = Literal["headline", "summary", "position", "education", "skill"]


class Change(BaseModel):
    """One field or one entity, and what should happen to it."""

    action: Action
    kind: Kind
    #: The entity's identity, empty for the two scalar fields. Stable across
    #: runs, so a change can be matched to the thing it is about.
    key: str = ""
    #: How to name the entity to a person.
    label: str = ""
    #: Which of the entity's own fields differ, for an update.
    fields: list[str] = Field(default_factory=list)
    #: The entity's short fields, one per line, for a person to compare.
    before: str = ""
    after: str = ""
    #: The one long field -- a position's or education's description -- kept
    #: apart from the others so the changeset can offer it as its own block to
    #: copy. Pasting a description with "title:" glued to the front of it is
    #: exactly the kind of small mess this file exists to avoid.
    before_body: str = ""
    after_body: str = ""

    def __str__(self) -> str:
        if self.action == "set":
            return f"set {self.kind}"
        return f"{self.action} {self.kind} '{self.label}'"


class Changeset(BaseModel):
    """Everything the next sync would do."""

    changes: list[Change] = Field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.changes)

    def of(self, *kinds: Kind) -> list[Change]:
        return [c for c in self.changes if c.kind in kinds]

    def summary(self) -> str:
        """A one-line count, for the end of a command that did the work."""
        if not self.changes:
            return "no changes"
        counts: dict[Action, int] = {}
        for change in self.changes:
            counts[change.action] = counts.get(change.action, 0) + 1
        order: tuple[Action, ...] = ("set", "add", "update", "remove")
        return ", ".join(f"{counts[a]} to {a}" for a in order if a in counts)


def diff(current: Profile, previous: Profile) -> Changeset:
    """What would have to happen to ``previous`` to make it ``current``."""
    changes: list[Change] = []
    for kind in ("headline", "summary"):
        before, after = getattr(previous, kind), getattr(current, kind)
        if before != after:
            changes.append(Change(action="set", kind=kind, before=before, after=after))

    changes += _entities("position", current.positions, previous.positions)
    changes += _entities("education", current.educations, previous.educations)
    changes += _skills(current.skills, previous.skills)
    return Changeset(changes=changes)


def _entities(
    kind: Kind,
    current: list[Position] | list[Education],
    previous: list[Position] | list[Education],
) -> list[Change]:
    """Match on identity, then compare field by field.

    Removals come last so a reader working down the changeset sees what the
    profile gains before what it loses, and never deletes an entry that a
    later line was going to edit.
    """
    mine = {entity.key: entity for entity in current}
    theirs = {entity.key: entity for entity in previous}
    changes: list[Change] = []

    for key, entity in mine.items():
        if (was := theirs.get(key)) is None:
            changes.append(
                Change(
                    action="add",
                    kind=kind,
                    key=key,
                    label=_label(entity),
                    after=_render(entity),
                    after_body=entity.description,
                )
            )
        elif fields := _differing(entity, was):
            changes.append(
                Change(
                    action="update",
                    kind=kind,
                    key=key,
                    label=_label(entity),
                    fields=fields,
                    before=_render(was),
                    after=_render(entity),
                    before_body=was.description,
                    after_body=entity.description,
                )
            )

    changes += [
        Change(
            action="remove",
            kind=kind,
            key=key,
            label=_label(entity),
            before=_render(entity),
            before_body=entity.description,
        )
        for key, entity in theirs.items()
        if key not in mine
    ]
    return changes


def _skills(current: list[Skill], previous: list[Skill]) -> list[Change]:
    """Skills are a set, so they are only ever added or removed.

    Order is not compared. LinkedIn keeps its own order -- pinned skills first,
    then endorsement count -- and a sync that fought it would produce a change
    on every run and never converge.
    """
    mine = {skill.key: skill for skill in current}
    theirs = {skill.key: skill for skill in previous}
    return [
        *(
            Change(action="add", kind="skill", key=key, label=s.name, after=s.name)
            for key, s in mine.items()
            if key not in theirs
        ),
        *(
            Change(action="remove", kind="skill", key=key, label=s.name, before=s.name)
            for key, s in theirs.items()
            if key not in mine
        ),
    ]


def _differing(current: BaseModel, previous: BaseModel) -> list[str]:
    mine, theirs = current.model_dump(), previous.model_dump()
    return sorted(name for name in mine if mine[name] != theirs.get(name))


def _label(entity: Position | Education) -> str:
    if isinstance(entity, Position):
        return f"{entity.title} @ {entity.company}" if entity.company else entity.title
    return f"{entity.degree} @ {entity.school}" if entity.degree else entity.school


#: Rendered as one "dates" line rather than two fields, and the description
#: is carried separately, so what is left is the entity's identity at a glance.
_DATES = ("start", "end")


def _render(entity: Position | Education) -> str:
    """The entity's short fields, as the text a person compares."""
    lines = [
        f"{name}: {value}"
        for name, value in entity.model_dump().items()
        if name not in (*_DATES, "description") and value not in (None, "", [])
    ]
    if dates := _dates(entity):
        lines.append(f"dates: {dates}")
    return "\n".join(lines)


def _dates(entity: Position | Education) -> str:
    """``Jul 2023 - Present``, with an absent end meaning current."""
    if entity.start is None and entity.end is None:
        return ""
    start = str(entity.start) if entity.start else "?"
    return f"{start} \u2013 {entity.end if entity.end else 'Present'}"
