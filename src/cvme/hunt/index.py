"""What changed between two versions, and the index that records it.

Three tailored resumes for one company look identical at a glance and are not,
and the version you sent is the one you have to speak to in the interview. The
comparison is made on the parsed document rather than on the text, so
rewrapping a bullet is not reported as a change and moving a section is.
"""

from __future__ import annotations

import re
from pathlib import Path

from cvme.errors import ParseError
from cvme.hunt.store import Round
from cvme.md.parse import parse_file
from cvme.models import BulletList, Document, Paragraph

BEGIN = "<!-- cvme:index -->"
END = "<!-- /cvme:index -->"

_OPENING = re.compile(r"^\W*(\w+(?:\s+\w+){0,4})")


def _bullets(document: Document) -> list[str]:
    found: list[str] = []
    for section in document.sections:
        groups = [section.blocks] + [entry.blocks for entry in section.entries]
        for blocks in groups:
            for block in blocks:
                if isinstance(block, BulletList):
                    stack = list(block.items)
                    while stack:
                        item = stack.pop(0)
                        found.append(item.text.strip())
                        stack = list(item.children) + stack
                elif isinstance(block, Paragraph):
                    found.append(block.text.strip())
    return found


def _opening(text: str) -> str:
    match = _OPENING.match(text)
    return match.group(1) if match else text[:40]


def summarise(previous: Path | None, current: Path) -> str:
    """One line describing how ``current`` differs from ``previous``."""
    if previous is None or not previous.is_file():
        return "first version"
    try:
        before, after = parse_file(previous), parse_file(current)
    except ParseError:
        return "unparsed; compare by hand"

    notes: list[str] = []

    old_sections = [s.title for s in before.sections]
    new_sections = [s.title for s in after.sections]
    if added := [t for t in new_sections if t not in old_sections]:
        notes.append(f"added section {', '.join(added)}")
    if dropped := [t for t in old_sections if t not in new_sections]:
        notes.append(f"dropped section {', '.join(dropped)}")
    shared_before = [t for t in old_sections if t in new_sections]
    shared_after = [t for t in new_sections if t in old_sections]
    if shared_before != shared_after:
        notes.append(f"reordered to {', '.join(shared_after)}")

    old_bullets, new_bullets = _bullets(before), _bullets(after)
    gained = [b for b in new_bullets if b not in old_bullets]
    lost = [b for b in old_bullets if b not in new_bullets]
    if gained:
        notes.append(f"+{len(gained)} lines (from '{_opening(gained[0])}')")
    if lost:
        notes.append(f"-{len(lost)} lines (dropped '{_opening(lost[0])}')")

    old_keywords = before.meta.get("keywords", "")
    new_keywords = after.meta.get("keywords", "")
    if old_keywords != new_keywords:
        notes.append("keywords rewritten")

    return "; ".join(notes) or "no structural change"


def render(slug: str, title: str, rounds: list[Round]) -> str:
    """The generated block of an ``apps/index.md``."""
    lines = [
        BEGIN,
        f"# {title or slug}",
        "",
        "Every version prepared for this posting, newest last. `changes` compares",
        "each version to the one before it.",
        "",
        "| # | prepared | documents | pages | fit | changes | note |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in rounds:
        lines.append(
            f"| {entry.number} | {entry.created_at[:10]} | {entry.documents} "
            f"| {entry.pages} | {entry.fit} | {entry.changes} | {entry.note} |"
        )
    if not rounds:
        lines.append("| _none yet_ | | | | | | |")
    lines += ["", END]
    return "\n".join(lines) + "\n"


def write(path: Path, slug: str, title: str, rounds: list[Round]) -> Path:
    """Refresh the generated block, leaving anything written around it alone."""
    block = render(slug, title, rounds)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if BEGIN in existing and END in existing:
        head, _, rest = existing.partition(BEGIN)
        _, _, tail = rest.partition(END)
        text = f"{head}{block.rstrip()}{tail}"
    else:
        text = f"{block}{existing}" if existing.strip() else block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return path
