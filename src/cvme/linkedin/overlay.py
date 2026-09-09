"""Layering ``linkedin.md`` over ``base.md``.

The resume is written to fit a page. The profile has no page, so the two want
different copy for the same job -- and keeping two whole documents in step by
hand is the problem this feature exists to avoid.

So the overlay is a patch, not a second resume. It is written in the same
grammar and holds only the parts that differ: a section, or one entry inside
one. Everything it does not mention comes from ``base.md``, which stays the
single source of truth for what is true.

Merging happens here, on the document IR, so that the projection in
``project`` is written once and neither file gets a special case.

The overlay adds and replaces. It cannot delete, because a one-way sync from a
document that no longer says something should stop saying it, and the way to
stop saying something is to remove it from ``base.md``.
"""

from __future__ import annotations

from cvme.linkedin.dates import parse_range
from cvme.linkedin.model import flatten
from cvme.models import Document, Entry, Section, to_plain_title


def merge(base: Document, extra: Document | None) -> Document:
    """``base`` with ``extra`` layered over it.

    Sections match on their title and entries on their identity, so an overlay
    can be as small as one entry with better bullets under it.
    """
    if extra is None:
        return base
    merged = base.model_copy(deep=True)
    merged.meta = {**merged.meta, **extra.meta}

    by_title = {to_plain_title(s.title): s for s in merged.sections}
    for section in extra.sections:
        if (target := by_title.get(to_plain_title(section.title))) is None:
            merged.sections.append(section.model_copy(deep=True))
            by_title[to_plain_title(section.title)] = merged.sections[-1]
        else:
            _merge_section(target, section)
    return merged


def _merge_section(target: Section, extra: Section) -> None:
    """Loose blocks are replaced wholesale; entries are matched one by one.

    Wholesale for blocks because the thing an overlay does to a summary is
    rewrite it, and a longer About merged into a shorter one would read as
    both.
    """
    if extra.blocks:
        target.blocks = [block.model_copy(deep=True) for block in extra.blocks]

    known = {entry_key(entry): index for index, entry in enumerate(target.entries)}
    for entry in extra.entries:
        replacement = entry.model_copy(deep=True)
        if (index := known.get(entry_key(entry))) is None:
            known[entry_key(entry)] = len(target.entries)
            target.entries.append(replacement)
        else:
            target.entries[index] = replacement


def entry_key(entry: Entry) -> str:
    """What makes two entries the same entry across the two files.

    The role, the organisation and the start date. Not the end date: the field
    most likely to change on any entry worth writing about twice is the one
    that reads "Present" today, and an overlay that stopped matching the day
    you left a job would silently append a duplicate role instead.

    The second line joins the key only for an entry with no organisation, which
    in practice means education: two degrees from one university are told apart
    by the degree and nothing else. Under a role it is the location, which one
    file may state and the other may not, so there it stays out.
    """
    head = entry.head
    dates = head.right or (entry.sub.right if entry.sub else "")
    start, _ = parse_range(flatten(dates))
    parts = [head.role or head.left, head.org or "", str(start or "")]
    if not head.org and entry.sub is not None:
        parts.append(entry.sub.left)
    return "|".join(" ".join(flatten(part).casefold().split()) for part in parts)
