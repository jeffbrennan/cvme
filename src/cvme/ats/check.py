"""Read a rendered PDF back and report what a parser would make of it.

`cvme verify` checks the source. This checks the artefact, which is the only
thing an applicant tracking system ever sees, and it can do so because the
converter already recovers structure from a PDF: run that recovery over your
own output and any place where the machine reading differs from the document
you wrote is a finding.

Every check answers a question a parser asks. Is there text at all. Does the
letterhead yield an address. Does each role carry dates it can parse. Do the
bullets separate. Are the sections named things it recognises. And, when the
source is available, does the structure it recovers match the structure you
wrote -- which is the whole question, asked once.
"""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from cvme.convert.pdftext import Layout, read
from cvme.convert.structure import to_markdown
from cvme.md.inline import to_plain
from cvme.md.parse import parse
from cvme.models import BulletList, Document
from cvme.verify.report import Finding, Report

#: Section names parsers are known to recognise. Anything else still extracts,
#: but is unlikely to be mapped to a field.
STANDARD_SECTIONS = {
    "summary",
    "professional summary",
    "objective",
    "experience",
    "professional experience",
    "work experience",
    "employment",
    "education",
    "skills",
    "technical skills",
    "projects",
    "certifications",
    "certificates",
    "publications",
    "awards",
    "volunteer",
}

#: `Mon YYYY`, optionally to another such date or to Present. Numeric formats
#: are deliberately not accepted: `07/23` is ambiguous across locales.
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_POINT = rf"(?:{_MONTH}\s+)?\d{{4}}"
_DATES = re.compile(rf"^{_POINT}(?:\s*[–—-]\s*(?:{_POINT}|Present|Current))?$", re.I)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I)
#: A proficiency in parentheses, as in `Python (advanced)`. Tool lists in
#: parentheses are fine: it is the qualifier attached to a keyword that some
#: parsers keep as part of the token.
_PROFICIENCY = re.compile(
    r"\w\s*\(\s*(?:advanced|intermediate|beginner|basic|expert|fluent|learning|"
    r"proficient|novice|working|familiar|\d+\+?\s*(?:yrs?|years))\b[^)]*\)",
    re.I,
)


def check_pdf(
    pdf: Path, *, source: Document | None = None, max_pages: int = 1
) -> Report:
    """Check what a parser recovers from ``pdf``.

    ``source`` is the document as authored. Given one, the structure the PDF
    yields is compared against it; without one, the checks that do not need it
    still run, so a PDF from anywhere can be checked.

    Findings carry a page number where a source check would carry a line.
    """
    layout = read(pdf)
    recovered = parse(to_markdown(layout))
    findings: list[Finding] = [
        *_metadata(pdf),
        *_glyphs(layout),
        *_letterhead(recovered),
        *_sections(recovered),
        *_dates(recovered),
        *_bullets(recovered),
        *_pages(layout, max_pages),
    ]
    if source is not None:
        findings += _structure(recovered, source)
    findings.sort(key=lambda f: (f.line, f.rule))
    return Report(path=pdf, findings=findings)


def _metadata(pdf: Path) -> list[Finding]:
    info = PdfReader(pdf).metadata or {}
    findings = []
    for key, rule, what in (
        ("/Title", "ats:title", "a title"),
        ("/Author", "ats:author", "an author"),
        ("/Keywords", "ats:keywords", "keywords"),
    ):
        if not str(info.get(key) or "").strip():
            findings.append(
                Finding(
                    rule=rule,
                    severity="warning",
                    message=f"the PDF carries no {what}",
                    line=1,
                    suggestion=(
                        "set it in frontmatter; many parsers read metadata first"
                    ),
                )
            )
    return findings


def _glyphs(layout: Layout) -> list[Finding]:
    """Symbol-font glyphs extract as junk, or as nothing at all."""
    findings = []
    for line in layout.lines:
        for run in line.runs:
            if run.symbol:
                findings.append(
                    Finding(
                        rule="ats:symbol-font",
                        severity="error",
                        message=(
                            f"{run.text.strip()!r} is drawn from a symbol font and "
                            f"extracts as junk"
                        ),
                        line=line.page,
                        excerpt=line.text[:72],
                        suggestion="use a real character, such as U+2022 for bullets",
                    )
                )
    return findings


def _letterhead(recovered: Document) -> list[Finding]:
    findings = []
    if not recovered.name.strip():
        findings.append(
            Finding(
                rule="ats:name",
                severity="error",
                message="no name is recoverable from the letterhead",
                line=1,
                suggestion="put the name first, as text rather than an image",
            )
        )
    contacts = " ".join(to_plain(c.text) for c in recovered.contact)
    if not _EMAIL.search(contacts):
        findings.append(
            Finding(
                rule="ats:email",
                severity="error",
                message="no email address is recoverable from the letterhead",
                line=1,
                suggestion="write the address as text; an icon extracts as nothing",
            )
        )
    return findings


def _sections(recovered: Document) -> list[Finding]:
    findings = []
    for section in recovered.sections:
        title = to_plain(section.title).strip()
        if title and title.lower() not in STANDARD_SECTIONS:
            findings.append(
                Finding(
                    rule="ats:section-name",
                    severity="warning",
                    message=f"'{title}' is not a section name parsers map to a field",
                    line=1,
                    suggestion=f"one of: {', '.join(sorted(STANDARD_SECTIONS)[:6])}, …",
                )
            )
    return findings


def _dates(recovered: Document) -> list[Finding]:
    findings = []
    for section in recovered.sections:
        for entry in section.entries:
            for part in (entry.head, entry.sub):
                if part is None or not part.right.strip():
                    continue
                dates = to_plain(part.right).strip()
                if not _DATES.match(dates):
                    findings.append(
                        Finding(
                            rule="ats:dates",
                            severity="warning",
                            message=f"'{dates}' does not read as a date range",
                            line=1,
                            excerpt=to_plain(part.left)[:72],
                            suggestion="write 'Mon YYYY - Mon YYYY', or 'Present'",
                        )
                    )
    return findings


def _bullets(recovered: Document) -> list[Finding]:
    """Bullets have to separate, and skills lines have to keep their labels."""
    findings = []
    lists = [
        block
        for section in recovered.sections
        for blocks in [section.blocks, *(e.blocks for e in section.entries)]
        for block in blocks
        if isinstance(block, BulletList)
    ]
    if not lists:
        findings.append(
            Finding(
                rule="ats:bullets",
                severity="warning",
                message="no bullet list is recoverable",
                line=1,
                suggestion="a marker that extracts leaves each point separable",
            )
        )
    for block in lists:
        for item in block.items:
            text = to_plain(item.text)
            if _PROFICIENCY.search(text):
                findings.append(
                    Finding(
                        rule="ats:skill-parenthetical",
                        severity="warning",
                        message="a skill carries its proficiency in parentheses",
                        line=1,
                        excerpt=text[:72],
                        suggestion=(
                            "some parsers keep '(advanced)' as part of the token; "
                            "weigh that against how it reads to a person"
                        ),
                    )
                )
    return findings


def _pages(layout: Layout, max_pages: int) -> list[Finding]:
    pages = max(line.page for line in layout.lines)
    if pages <= max_pages:
        return []
    return [
        Finding(
            rule="ats:pages",
            severity="warning",
            message=f"{pages} pages, over a budget of {max_pages}",
            line=pages,
            suggestion="cvme render --max-pages tightens until it fits",
        )
    ]


def _structure(recovered: Document, source: Document) -> list[Finding]:
    """Compare what the PDF yields against what was written."""
    findings = []
    got = [to_plain(s.title).strip().lower() for s in recovered.sections]
    want = [to_plain(s.title).strip().lower() for s in source.sections]
    if got != want:
        return [
            Finding(
                rule="ats:structure",
                severity="error",
                message=(f"the PDF yields sections {got} where the source has {want}"),
                line=1,
                suggestion="the layout is hiding structure a parser needs",
            )
        ]
    for mine, theirs in zip(recovered.sections, source.sections, strict=True):
        if len(mine.entries) != len(theirs.entries):
            findings.append(
                Finding(
                    rule="ats:structure",
                    severity="error",
                    message=(
                        f"'{to_plain(theirs.title)}' yields {len(mine.entries)} "
                        f"entries where the source has {len(theirs.entries)}"
                    ),
                    line=1,
                )
            )
            continue
        for entry, written in zip(mine.entries, theirs.entries, strict=True):
            if _count(entry.blocks) != _count(written.blocks):
                findings.append(
                    Finding(
                        rule="ats:structure",
                        severity="error",
                        message=(
                            f"'{to_plain(written.head.left)}' yields "
                            f"{_count(entry.blocks)} bullets where the source has "
                            f"{_count(written.blocks)}"
                        ),
                        line=1,
                        suggestion="a wrapped line is reading as a new point",
                    )
                )
    return findings


def _count(blocks: list) -> int:
    return sum(len(b.items) for b in blocks if isinstance(b, BulletList))
