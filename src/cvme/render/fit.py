"""Fit a document to its page budget.

``max_pages`` is enforced, not suggested. When a document overflows, the
renderer walks a bounded ladder of density adjustments -- leading first, then
the gaps between blocks, then type size, then margins -- recompiling after each
step. Every step has a floor declared alongside it, so the document can get
tighter but never illegible.

If the floors are reached and it still overflows, that is a hard failure with a
diagnostic naming the longest material. Silently shrinking a resume to 7pt to
make it "fit" is worse than saying it does not.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader

from cvme.errors import FitError
from cvme.md.inline import to_plain
from cvme.models import Block, BulletList, Document, Paragraph
from cvme.style.schema import Style

#: Hard stop on ladder iterations, so a pathological style cannot spin.
MAX_ITERATIONS = 60


@dataclass(frozen=True)
class Step:
    """One rung of the density ladder."""

    name: str
    apply: Callable[[Style], Style | None]


def _shrink(field: str, delta: float, floor: float) -> Callable[[Style], Style | None]:
    def step(style: Style) -> Style | None:
        current = float(getattr(style, field))
        if current - delta < floor:
            return None
        return style.model_copy(update={field: round(current - delta, 3)})

    return step


def _scale_type(factor: float, floor: float) -> Callable[[Style], Style | None]:
    """Scale every type size together, so the hierarchy stays proportional."""

    def step(style: Style) -> Style | None:
        if style.body_size * factor < floor:
            return None
        return style.model_copy(
            update={
                field: round(getattr(style, field) * factor, 3)
                for field in (
                    "body_size",
                    "contact_size",
                    "date_size",
                    "section_size",
                    "name_size",
                )
            }
        )

    return step


#: Ordered by how little each costs the reader. Leading tightens invisibly;
#: margins are the last thing to give.
LADDER: list[Step] = [
    Step("leading", _shrink("leading", 0.3, floor=4.8)),
    Step("entry gaps", _shrink("entry_gap_before", 0.7, floor=3.0)),
    Step("section gap above", _shrink("section_gap_before", 0.7, floor=3.5)),
    Step("section gap below", _shrink("section_gap_after", 0.8, floor=7.0)),
    Step("header gap", _shrink("header_gap", 1.0, floor=4.0)),
    Step("type size", _scale_type(0.98, floor=9.0)),
    Step("vertical margins", _shrink("margin_y", 3.6, floor=21.6)),
    Step("horizontal margins", _shrink("margin_x", 3.6, floor=43.2)),
]


@dataclass(frozen=True)
class FitResult:
    style: Style
    pages: int
    applied: list[str]


def page_count(pdf: Path) -> int:
    return len(PdfReader(pdf).pages)


def fit(
    doc: Document,
    style: Style,
    *,
    output: Path,
    template: str = "resume",
) -> FitResult:
    """Compile, and tighten until the page budget is met.

    Publishes ``output`` only after the page budget is met. Failed attempts are
    compiled beside it and removed, so a rejected PDF cannot be mistaken for a
    valid result.
    """
    from cvme.render.engine import compile_document

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    attempt = output.with_name(f".{output.stem}.{uuid4().hex}.pdf")

    def publish(result: FitResult) -> FitResult:
        os.replace(attempt, output)
        return result

    try:
        compile_document(doc, style, output=attempt, template=template)
        pages = page_count(attempt)
        if pages <= style.max_pages:
            return publish(FitResult(style, pages, []))
        if style.on_overflow == "warn":
            return publish(FitResult(style, pages, []))
        if style.on_overflow == "error":
            raise FitError(_diagnose(doc, pages, style.max_pages, tightened=False))

        applied: list[str] = []
        current = style
        for _ in range(MAX_ITERATIONS):
            progressed = False
            for step in LADDER:
                tightened = step.apply(current)
                if tightened is None:
                    continue
                progressed = True
                current = tightened
                applied.append(step.name)
                compile_document(doc, current, output=attempt, template=template)
                pages = page_count(attempt)
                if pages <= current.max_pages:
                    return publish(FitResult(current, pages, _summarise(applied)))
            if not progressed:
                break

        raise FitError(_diagnose(doc, pages, style.max_pages, tightened=True))
    finally:
        attempt.unlink(missing_ok=True)


def _summarise(applied: list[str]) -> list[str]:
    """Collapse repeats into 'leading x3' while keeping ladder order."""
    counts: dict[str, int] = {}
    for name in applied:
        counts[name] = counts.get(name, 0) + 1
    return [n if c == 1 else f"{n} x{c}" for n, c in counts.items()]


def _diagnose(doc: Document, pages: int, budget: int, *, tightened: bool) -> str:
    """Explain what to cut, rather than just reporting failure."""
    weights: list[tuple[int, str]] = []
    bullets: list[tuple[int, str]] = []
    paragraphs: list[tuple[int, str]] = []

    def scan(blocks: list[Block]) -> int:
        count = 0
        for block in blocks:
            if isinstance(block, BulletList):
                count += len(block.items)
                bullets.extend((len(b.text), b.text) for b in block.items)
            elif isinstance(block, Paragraph):
                paragraphs.append((len(block.text.split()), block.text))
        return count

    for section in doc.sections:
        size = scan(section.blocks)
        for entry in section.entries:
            size += scan(entry.blocks)
        weights.append((size, section.title))

    weights.sort(reverse=True)
    bullets.sort(reverse=True)
    paragraphs.sort(reverse=True)

    reason = (
        "and every density step has reached its floor"
        if tightened
        else "and this document type does not tighten to fit"
    )
    lines = [f"document needs {pages} pages but the budget is {budget}, {reason}."]

    if bullets:
        named = ", ".join(
            f"{title or 'untitled'} ({size} bullets)"
            for size, title in weights[:3]
            if size
        )
        lines += ["", f"largest sections: {named}", "", "longest bullets to cut:"]
        lines += [f"  - {to_plain(text)[:96]}" for _, text in bullets[:3]]
    if paragraphs:
        total = sum(words for words, _ in paragraphs)
        lines += [
            "",
            f"{len(paragraphs)} paragraphs, {total} words. Longest:",
        ]
        lines += [
            f"  - {words} words: {to_plain(text)[:72]}..."
            for words, text in paragraphs[:3]
        ]

    lines += ["", "raise the budget with --max-pages, or shorten the document."]
    if tightened:
        lines[-1] = "raise the budget with --max-pages, or use --style compact."
    return "\n".join(lines)
