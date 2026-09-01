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

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from cvme.errors import FitError
from cvme.md.inline import to_plain
from cvme.models import BulletList, Document
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

    Always leaves ``output`` holding the best result achieved.
    """
    from cvme.render.engine import compile_document

    compile_document(doc, style, output=output, template=template)
    pages = page_count(output)
    if pages <= style.max_pages or not style.autofit:
        return FitResult(style, pages, [])

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
            compile_document(doc, current, output=output, template=template)
            pages = page_count(output)
            if pages <= current.max_pages:
                return FitResult(current, pages, _summarise(applied))
        if not progressed:
            break

    raise FitError(_diagnose(doc, pages, style.max_pages))


def _summarise(applied: list[str]) -> list[str]:
    """Collapse repeats into 'leading x3' while keeping ladder order."""
    counts: dict[str, int] = {}
    for name in applied:
        counts[name] = counts.get(name, 0) + 1
    return [n if c == 1 else f"{n} x{c}" for n, c in counts.items()]


def _diagnose(doc: Document, pages: int, budget: int) -> str:
    """Explain what to cut, rather than just reporting failure."""
    weights: list[tuple[int, str]] = []
    longest: list[tuple[int, str]] = []
    for section in doc.sections:
        size = 0
        for entry in section.entries:
            for block in entry.blocks:
                if isinstance(block, BulletList):
                    size += len(block.items)
                    longest.extend((len(b.text), b.text) for b in block.items)
        for block in section.blocks:
            if isinstance(block, BulletList):
                size += len(block.items)
                longest.extend((len(b.text), b.text) for b in block.items)
        weights.append((size, section.title))

    weights.sort(reverse=True)
    longest.sort(reverse=True)
    lines = [
        f"document needs {pages} pages but the budget is {budget}, "
        "and every density step has reached its floor.",
        "",
        "largest sections: "
        + ", ".join(f"{title} ({size} bullets)" for size, title in weights[:3] if size),
        "",
        "longest bullets, as candidates to cut or shorten:",
    ]
    lines += [f"  - {to_plain(text)[:96]}" for _, text in longest[:3]]
    lines.append("")
    lines.append("or raise the budget with --max-pages, or use --style compact.")
    return "\n".join(lines)
