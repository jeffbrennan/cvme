"""Parse a cvme markdown document into the typed IR.

The grammar is documented in ``GRAMMAR.md`` and is deliberately small: an LLM
writes these documents, so anything it writes unreliably breaks the pipeline.
Beyond YAML frontmatter there is exactly one invention -- a pipe splits
left-aligned from right-aligned content -- plus ``@`` as a convenience inside
it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

from cvme.errors import ParseError
from cvme.md import inline as il
from cvme.models import (
    Block,
    Bullet,
    BulletList,
    Contact,
    Document,
    Entry,
    EntryLine,
    PageBreak,
    Paragraph,
    Section,
)

_md = MarkdownIt("commonmark")


def parse_file(path: Path) -> Document:
    """Parse a document from disk."""
    return parse(path.read_text(encoding="utf-8"), path=str(path))


def parse(source: str, *, path: str | None = None) -> Document:
    """Parse a document from a string."""
    front, body = _split_frontmatter(source, path)
    doc = Document(**_document_fields(front, path))
    _parse_body(doc, body, path)
    return doc


def _split_frontmatter(source: str, path: str | None) -> tuple[dict[str, Any], str]:
    text = source.lstrip("﻿")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        raise ParseError("frontmatter opened with --- but never closed", path=path)
    raw = text[text.find("\n") + 1 : end]
    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ParseError(f"frontmatter is not valid YAML: {exc}", path=path) from exc
    if not isinstance(loaded, dict):
        raise ParseError("frontmatter must be a mapping", path=path)
    rest = text[end + 4 :]
    return loaded, rest.lstrip("\n")


def _document_fields(front: dict[str, Any], path: str | None) -> dict[str, Any]:
    contact: list[Contact] = []
    for item in front.get("contact") or []:
        # Frontmatter is plain text from the author, but the IR's contract is
        # that every string is Typst markup. Without conversion an address like
        # "a@b.com" reaches the template as a label reference and fails the
        # compile.
        if isinstance(item, str):
            contact.append(Contact(text=il.to_typst(item)[0]))
        elif isinstance(item, dict) and "text" in item:
            contact.append(
                Contact(text=il.to_typst(str(item["text"]))[0], url=item.get("url"))
            )
        else:
            raise ParseError(
                "each contact must be a string or a mapping with a 'text' key",
                path=path,
            )
    meta = {
        str(k): str(v)
        for k, v in front.items()
        if k not in {"name", "contact"} and v is not None
    }
    name = il.to_typst(str(front.get("name", "")))[0]
    return {"name": name, "contact": contact, "meta": meta}


def _entry_line(raw: str, *, split_org: bool) -> EntryLine:
    left_raw, right_raw = il.split_pipe(raw)
    role = org = None
    if split_org:
        role_raw, org_raw = il.split_at(left_raw)
        if org_raw is not None:
            role, _ = il.to_typst(il.unescape_source(role_raw))
            org, _ = il.to_typst(il.unescape_source(org_raw))
    left, _ = il.to_typst(il.unescape_source(left_raw))
    right, _ = il.to_typst(il.unescape_source(right_raw))
    return EntryLine(left=left, right=right, role=role, org=org)


def _parse_body(doc: Document, body: str, path: str | None) -> None:
    tokens = _md.parse(body)
    section: Section | None = None
    entry: Entry | None = None
    i = 0

    def target() -> list[Block]:
        if entry is not None:
            return entry.blocks
        if section is not None:
            return section.blocks
        raise ParseError("content appears before the first '## Section'", path=path)

    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            content = tokens[i + 1].content
            level = token.tag
            if level == "h2":
                section = Section(title=il.to_typst(content)[0])
                doc.sections.append(section)
                entry = None
            elif level == "h3":
                if section is None:
                    raise ParseError(
                        "'### Entry' appears before the first '## Section'", path=path
                    )
                entry = Entry(head=_entry_line(content, split_org=True))
                section.entries.append(entry)
            elif level == "h4":
                if entry is None:
                    raise ParseError(
                        "'#### Line' appears before the first '### Entry'", path=path
                    )
                entry.sub = _entry_line(content, split_org=False)
            else:
                raise ParseError(
                    f"unsupported heading level '{level}'; use ##, ### or ####",
                    path=path,
                )
            i += 3
            continue

        if token.type == "paragraph_open":
            text, facts = il.extract_facts(tokens[i + 1].content)
            rendered = il.render_tokens(_md.parseInline(text)[0])
            if rendered:
                target().append(Paragraph(text=rendered, facts=facts))
            i += 3
            continue

        if token.type == "bullet_list_open":
            items, i = _parse_list(tokens, i)
            target().append(BulletList(items=items))
            continue

        if token.type == "hr":
            target().append(PageBreak())

        i += 1


def _parse_list(tokens: list[Token], start: int) -> tuple[list[Bullet], int]:
    """Parse one bullet list, returning its items and the index just past it."""
    items: list[Bullet] = []
    depth = 0
    i = start
    while i < len(tokens):
        token = tokens[i]
        if token.type == "bullet_list_open":
            depth += 1
            if depth > 1:
                children, i = _parse_list(tokens, i)
                if items:
                    items[-1].children = children
                depth -= 1
                continue
        elif token.type == "bullet_list_close":
            depth -= 1
            if depth == 0:
                return items, i + 1
        elif token.type == "paragraph_open" and depth == 1:
            text, facts = il.extract_facts(tokens[i + 1].content)
            rendered = il.render_tokens(_md.parseInline(text)[0])
            if rendered:
                items.append(Bullet(text=rendered, facts=facts))
            i += 3
            continue
        i += 1
    return items, i
