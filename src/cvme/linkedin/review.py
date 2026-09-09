"""The changeset: what to change on the profile, written for a person.

LinkedIn's Profile Edit API is partner-gated, so the realistic shape of "keep
my profile in step with base.md" is not an automated push. It is knowing
exactly which fields drifted since the last time you looked, and having the
new text ready to paste rather than re-typed from a PDF.

The first run lists everything, because cvme has not recorded a profile yet.
After ``cvme linkedin record`` it lists only what changed, which is usually
one field or none.

So the file is written to be worked through top to bottom and thrown away: one
section per edit, in the order LinkedIn's own editor presents them, with the
new value in a fenced block that copies cleanly and the old value only where
seeing it helps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cvme.linkedin.diff import Change, Changeset
from cvme.linkedin.model import Violation

#: Where in LinkedIn's editor each kind of change is applied, and the order to
#: work through them. The order is the profile's own, top to bottom, so the
#: file reads as one pass down the page rather than a jump per item.
PLACES: dict[str, tuple[str, str]] = {
    "headline": ("Headline", "Edit intro > Headline"),
    "summary": ("About", "About > Edit"),
    "position": ("Experience", "Experience > the role > Edit"),
    "education": ("Education", "Education > the entry > Edit"),
    "skill": ("Skills", "Skills > Add or remove"),
}
_ORDER = list(PLACES)


def render(
    changeset: Changeset, *, violations: list[Violation], unmapped: list[str]
) -> str:
    """The changeset as a document to work through."""
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# LinkedIn changeset",
        "",
        f"Generated {when} from the cvme source documents.",
        "",
    ]

    if violations:
        lines += [
            "## Fix these first",
            "",
            "LinkedIn will reject these fields at their current length.",
            "",
            *(f"- {violation}" for violation in violations),
            "",
        ]

    if not changeset:
        lines += ["Nothing has changed since the last recorded sync.", ""]
        return "\n".join(lines)

    lines += [f"{changeset.summary()}.", ""]
    for kind in _ORDER:
        if not (changes := changeset.of(kind)):  # type: ignore[arg-type]
            continue
        heading, where = PLACES[kind]
        lines += [f"## {heading}", "", f"*{where}*", ""]
        lines += _skills(changes) if kind == "skill" else _entries(changes)

    if unmapped:
        lines += [
            "## Not synced",
            "",
            "cvme has no LinkedIn field for these sections, so they are left to you:",
            "",
            *(f"- {name}" for name in unmapped),
            "",
        ]

    lines += [
        "---",
        "",
        "Once these are applied, record them so the next run only shows what "
        "changed after today:",
        "",
        "```",
        "cvme linkedin record",
        "```",
        "",
    ]
    return "\n".join(lines)


def _entries(changes: list[Change]) -> list[str]:
    lines: list[str] = []
    for change in changes:
        if change.action == "set":
            lines += _value(change.after, change.before)
            continue

        verb = {"add": "Add", "update": "Update", "remove": "Remove"}[change.action]
        lines += [f"### {verb}: {change.label}", ""]
        if change.action == "remove":
            lines += ["Delete this entry. It was:", "", *_fenced(change.before)]
            continue
        if change.fields:
            lines += [f"Changed: {', '.join(change.fields)}.", ""]
        lines += [_bullets(change.after), ""]
        if change.after_body:
            lines += ["Description:", "", *_fenced(change.after_body)]
        if change.before_body and change.before_body != change.after_body:
            lines += _was(change.before_body)
    return lines


def _value(after: str, before: str) -> list[str]:
    """A scalar field: the new text to paste, and the old only if there was one."""
    return [*_fenced(after), *(_was(before) if before else [])]


def _was(text: str) -> list[str]:
    """The previous value, folded away. It is context, not the thing to copy."""
    return ["<details><summary>was</summary>", "", *_fenced(text), "</details>", ""]


def _fenced(text: str) -> list[str]:
    return ["```", text, "```", ""]


def _bullets(rendered: str) -> str:
    """The compact fields as a markdown list, so the block above stays copyable."""
    return "\n".join(f"- {line}" for line in rendered.splitlines() if line)


def _skills(changes: list[Change]) -> list[str]:
    """Skills as two lists, because that is how the editor takes them.

    One line per skill and a heading per action, rather than a section each:
    thirty skills as thirty sections is a worse file than the profile it is
    describing.
    """
    lines: list[str] = []
    for action, heading in (("add", "Add"), ("remove", "Remove")):
        if named := [c.label for c in changes if c.action == action]:
            lines += [f"{heading}:", ""]
            lines += [f"- {name}" for name in named]
            lines.append("")
    return lines


def write(
    path: Path,
    changeset: Changeset,
    *,
    violations: list[Violation],
    unmapped: list[str],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render(changeset, violations=violations, unmapped=unmapped), encoding="utf-8"
    )
    return path
