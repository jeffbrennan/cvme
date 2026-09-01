"""The typed intermediate representation.

This is the seam between parsing and rendering: the parser never knows about
fonts, and the renderer never knows about markdown. Adding a document type
means adding a template, not a parser.

Every string field below holds **Typst markup**, not markdown. Inline
conversion happens during parsing (see ``cvme.md.inline``) so that the
renderer can interpolate values without re-escaping them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Contact(BaseModel):
    """One item in the contact line."""

    text: str
    url: str | None = None


class Bullet(BaseModel):
    """A list item, possibly with one level of nesting beneath it."""

    text: str
    children: list[Bullet] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class Paragraph(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    text: str
    facts: list[str] = Field(default_factory=list)


class BulletList(BaseModel):
    kind: Literal["bullets"] = "bullets"
    items: list[Bullet] = Field(default_factory=list)


class PageBreak(BaseModel):
    kind: Literal["pagebreak"] = "pagebreak"


Block = Paragraph | BulletList | PageBreak


class EntryLine(BaseModel):
    """One line of an entry header: content left, content hard right.

    ``role``/``org`` are set when the left side used the ``Role @ Org`` form,
    which lets the template set the role bold and the organisation regular.
    ``left`` always holds the whole left side, so a template that does not care
    about the split can ignore the other two.
    """

    left: str
    right: str = ""
    role: str | None = None
    org: str | None = None


class Entry(BaseModel):
    """A job, a degree, a project: a headed group of content."""

    head: EntryLine
    sub: EntryLine | None = None
    blocks: list[Block] = Field(default_factory=list)


class Section(BaseModel):
    """A ``##`` section: a header plus loose blocks and/or entries."""

    title: str
    blocks: list[Block] = Field(default_factory=list)
    entries: list[Entry] = Field(default_factory=list)


class Document(BaseModel):
    """A whole resume or cover letter."""

    name: str = ""
    contact: list[Contact] = Field(default_factory=list)
    meta: dict[str, str] = Field(default_factory=dict)
    sections: list[Section] = Field(default_factory=list)

    def facts(self) -> list[str]:
        """Every fact id cited anywhere in the document.

        Used by ``cvme verify`` to check provenance; collected here because
        the IR is the only place that sees the whole document at once.
        """
        found: list[str] = []

        def walk(blocks: list[Block]) -> None:
            for block in blocks:
                if isinstance(block, Paragraph):
                    found.extend(block.facts)
                elif isinstance(block, BulletList):
                    stack = list(block.items)
                    while stack:
                        item = stack.pop()
                        found.extend(item.facts)
                        stack.extend(item.children)

        for section in self.sections:
            walk(section.blocks)
            for entry in section.entries:
                walk(entry.blocks)
        return found
