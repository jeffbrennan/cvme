"""Recover document structure from positioned lines, and write it as markdown.

Every decision here is geometric, because a PDF records nothing else. A line
is a section header because it is bold and larger than the body; an entry
header because a date sits hard against the right margin; a bullet because a
marker glyph precedes text at a deeper indent; a continuation because it is
indented under the bullet it belongs to and carries no marker of its own.

The output is the grammar in ``cvme.md.GRAMMAR``, so a converted document is
an ordinary source file: editable, renderable, and verifiable.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field

from cvme.convert.pdftext import Layout, Line, Run

#: Markers a bullet may be drawn with, beyond any glyph from a symbol font.
BULLET_RE = re.compile(
    r"^\s*([\u2022\u00b7\u25aa\u25e6\u2023\u2219\u2043*+\u2013\u2014-])\s"
)

#: How far a right-aligned cluster may fall short of the right margin.
RIGHT_SLACK = 3.0

#: A gap this many times the font size opens a right-aligned cluster.
SPLIT_GAP = 1.5

#: The wider gap required to read a line as two columns without the help of
#: the right margin.
COLUMN_GAP = 3.0

#: Indent tolerance when comparing a line's start to the left margin.
INDENT_SLACK = 2.0

#: A marker starting this far right of the list's outermost marker is nested.
NEST_INDENT = 4.0

#: A following line spaced no further than this multiple of single spacing
#: belongs to the same block.
SAME_BLOCK = 1.35

_WRAP = 79
_SEPARATORS = "–—-|,·@:"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_URLISH = re.compile(r"^(?:https?://)?[\w.-]+\.[a-z]{2,}(?:/\S*)?$", re.I)
_PHONE = re.compile(r"^\+?[\d][\d().\s-]{6,}$")
#: Punctuation that marks prose rather than a contact detail.
_SENTENCE = re.compile(r"[.:;!?]")
_MD_SPECIAL = re.compile(r"([\\*_`\[\]])")


@dataclass
class _Contact:
    text: str
    url: str | None = None


@dataclass
class _Out:
    """The markdown being assembled, block by block."""

    name: str = ""
    contact: list[_Contact] = field(default_factory=list)
    body: list[str] = field(default_factory=list)
    kind: str = ""
    marker_x: float | None = None

    def add(self, kind: str, text: str, *, marker_x: float | None = None) -> None:
        self.body.append(text)
        self.kind = kind
        self.marker_x = marker_x

    def extend_last(self, text: str) -> None:
        self.body[-1] = f"{self.body[-1].rstrip()} {text}"


def to_markdown(layout: Layout) -> str:
    """Convert an extracted layout to a cvme markdown document."""
    out = _Out()
    lines = list(layout.lines)
    start = _read_header(out, lines, layout)
    previous: Line | None = None
    for line in lines[start:]:
        _emit(out, line, previous, layout)
        previous = line
    return _document(out)


def _read_header(out: _Out, lines: list[Line], layout: Layout) -> int:
    """Read the letterhead: the name, and any contact rows beneath it.

    The name is the top line, by position rather than by style: set large and
    bold, it is indistinguishable from a section header otherwise.

    The rows under it are taken only while they still read as contact details.
    Ending the letterhead at the first section header instead would be simpler,
    but a resume whose summary carries no heading -- which the grammar allows,
    and which is a common way to write one -- puts prose directly under the
    name, and folding that in yields a document with a paragraph for an email
    address.
    """
    if not lines:
        return 0
    left, right = _split_right(lines[0], layout, anywhere=True)
    out.name = _plain(left)
    end = 1
    while end < len(lines) and _is_contact_row(lines[end], layout):
        end += 1
    head = lines[:end]
    tail = [text for line in head[1:] for text in _contacts(line.runs)]
    for text in _contacts(right) + tail:
        out.contact.append(_Contact(text=text, url=_url(text)))
    for run in (run for line in head for run in line.runs):
        if run.url:  # a link annotation beats any guess made from the text
            for contact in out.contact:
                if contact.text in run.text or run.text.strip() in contact.text:
                    contact.url = run.url
    return end


def _is_contact_row(line: Line, layout: Layout) -> bool:
    """A second letterhead row: contact atoms, and nothing that is not one.

    At least one hard atom -- an address, a URL, a phone number -- is required,
    so that a date line or an opening sentence cannot pass on the strength of
    being short.
    """
    if _is_section(line, layout):
        return False
    parts = _contacts(line.runs)
    return (
        bool(parts)
        and all(_is_contact_atom(part) for part in parts)
        and any(_is_hard_contact(part) for part in parts)
    )


def _is_hard_contact(text: str) -> bool:
    return bool(_EMAIL.match(text) or _URLISH.match(text) or _PHONE.match(text))


def _is_contact_atom(text: str) -> bool:
    """A contact atom, or a short qualifier such as a city or a pronoun set."""
    if _is_hard_contact(text):
        return True
    return len(text) <= 40 and len(text.split()) <= 6 and not _SENTENCE.search(text)


def _contacts(runs: tuple[Run, ...]) -> list[str]:
    text = _plain(runs)
    return [part.strip() for part in re.split(r"\s*[|•·]\s*", text) if part.strip()]


def _url(text: str) -> str | None:
    if _EMAIL.match(text):
        return f"mailto:{text}"
    if _URLISH.match(text):
        return text if text.startswith("http") else f"https://{text}"
    return None


def _emit(out: _Out, line: Line, previous: Line | None, layout: Layout) -> None:
    if _is_section(line, layout):
        out.add("section", f"## {_title(_plain(line.runs))}")
        return

    marker, rest = _bullet(line)
    if marker is not None:
        outer = out.marker_x if out.marker_x is not None else marker
        nested = marker > outer + NEST_INDENT
        out.add(
            "bullet",
            ("  - " if nested else "- ") + _inline(rest),
            marker_x=min(outer, marker),
        )
        return

    if line.x0 > layout.left + INDENT_SLACK and out.kind in {"bullet", "paragraph"}:
        # Indented with no marker of its own: the tail of the block above.
        out.extend_last(_inline(line.runs))
        return

    left, right = _split_right(line, layout)
    if _is_entry(line, layout, left):
        head = _entry_head(left, right)
        if out.kind == "entry" and _adjacent(previous, line, layout):
            out.add("sub", f"#### {head}")
        else:
            out.add("entry", f"### {head}")
        return

    text = _inline(line.runs)
    if out.kind == "paragraph" and _adjacent(previous, line, layout):
        out.extend_last(text)
    else:
        out.add("paragraph", text)


def _adjacent(previous: Line | None, line: Line, layout: Layout) -> bool:
    """True when ``line`` sits directly under ``previous``, on one page."""
    if previous is None or previous.page != line.page or not layout.line_height:
        return False
    return previous.baseline - line.baseline <= layout.line_height * SAME_BLOCK


def _is_section(line: Line, layout: Layout) -> bool:
    """A section header: bold, at the margin, and set apart by case or size."""
    body = _plain(line.runs)
    return (
        line.x0 <= layout.left + INDENT_SLACK
        and all(run.bold for run in line.runs)
        and bool(body)
        and (line.size > layout.body_size + 0.4 or body == body.upper())
        and not _split_right(line, layout)[1]
    )


def _is_entry(line: Line, layout: Layout, left: tuple[Run, ...]) -> bool:
    """An entry header: a bold left side at the margin, dated or wholly bold."""
    return (
        line.x0 <= layout.left + INDENT_SLACK
        and bool(left)
        and left[0].bold
        and (len(left) < len(line.runs) or all(run.bold for run in line.runs))
    )


def _split_right(
    line: Line, layout: Layout, *, anywhere: bool = False
) -> tuple[tuple[Run, ...], tuple[Run, ...]]:
    """Split a line into its left content and any right-aligned cluster.

    ``anywhere`` drops the requirement that the cluster reach the right
    margin, for the letterhead: its contacts are right-aligned to the margin
    but a rendered underline or a trailing space can leave them short of it,
    and a gap that wide on the first line is a column either way.
    """
    if len(line.runs) < 2:
        return line.runs, ()
    if not anywhere and line.x1 < layout.right - RIGHT_SLACK:
        return line.runs, ()
    index = max(range(1, len(line.runs)), key=line.gap_before)
    threshold = (COLUMN_GAP if anywhere else SPLIT_GAP) * line.size
    if line.gap_before(index) < threshold:
        return line.runs, ()
    return line.runs[:index], line.runs[index:]


def _bullet(line: Line) -> tuple[float | None, tuple[Run, ...]]:
    """The marker's x position and the runs after it, if this is a bullet."""
    first = line.runs[0]
    if first.symbol or BULLET_RE.match(first.text + " "):
        if len(line.runs) > 1:
            return first.x0, line.runs[1:]
        return None, line.runs
    if match := BULLET_RE.match(first.text):
        stripped = Run(
            text=first.text[match.end() :],
            x0=first.x0,
            x1=first.x1,
            size=first.size,
            bold=first.bold,
            italic=first.italic,
            url=first.url,
        )
        return first.x0, (stripped, *line.runs[1:])
    return None, line.runs


def _entry_head(left: tuple[Run, ...], right: tuple[Run, ...]) -> str:
    """Write an entry header, splitting the role from its organisation.

    The split comes from weight, not punctuation: the template sets the role
    bold and the organisation regular, so the boundary between the two is
    exactly where the bold runs stop.
    """
    merged = _merge(left)
    role_runs = tuple(run for run in merged if run.bold)
    rest = tuple(merged[len(role_runs) :])
    dates = _head_text(right)
    if role_runs and rest:
        head = f"{_head_text(role_runs)} @ {_head_text(rest).lstrip(_SEPARATORS + ' ')}"
    else:
        head = _head_text(left)
    return f"{head} | {dates}" if dates else head


def _head_text(runs: tuple[Run, ...]) -> str:
    """Plain text for an entry header, escaped for the grammar.

    No emphasis: the template sets the role bold and the dates bold itself, so
    carrying the PDF's weights through would double them up.
    """
    text = _MD_SPECIAL.sub(r"\\\1", _plain(runs))
    return text.replace("|", "\\|").replace(" @ ", " \\@ ")


def _merge(runs: tuple[Run, ...]) -> list[Run]:
    """Join neighbouring runs that differ only in size or symbol font."""
    merged: list[Run] = []
    for run in runs:
        if merged and (merged[-1].bold, merged[-1].italic, merged[-1].url) == (
            run.bold,
            run.italic,
            run.url,
        ):
            last = merged[-1]
            merged[-1] = Run(
                text=last.text + run.text,
                x0=last.x0,
                x1=run.x1,
                size=max(last.size, run.size),
                bold=last.bold,
                italic=last.italic,
                url=last.url,
            )
        else:
            merged.append(run)
    return merged


def _inline(runs: tuple[Run, ...]) -> str:
    """Render runs as markdown inline content."""
    out: list[str] = []
    for run in _merge(runs):
        body = _MD_SPECIAL.sub(r"\\\1", run.text)
        stripped = body.strip()
        if not stripped:
            out.append(" " if body else "")
            continue
        lead = " " if body[:1].isspace() else ""
        tail = " " if body[-1:].isspace() else ""
        # A trailing colon belongs to the sentence, not to the label: keeping
        # it inside the emphasis reads as `**Languages:**` where every hand
        # written document in this grammar writes `**Languages**:`.
        punct = ""
        while run.bold and stripped[-1:] in ":;,.":
            punct = stripped[-1] + punct
            stripped = stripped[:-1]
        if run.url:
            stripped = f"[{stripped}]({run.url})"
        if run.bold and run.italic:
            stripped = f"***{stripped}***"
        elif run.bold:
            stripped = f"**{stripped}**"
        elif run.italic:
            stripped = f"*{stripped}*"
        out.append(f"{lead}{stripped}{punct}{tail}")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _plain(runs: tuple[Run, ...]) -> str:
    return re.sub(r"\s+", " ", "".join(run.text for run in runs)).strip()


def _title(text: str) -> str:
    """Recover title case from a header the template rendered uppercase."""
    if text != text.upper():
        return text
    return " ".join(
        word if len(word) == 1 and not word.isalpha() else word.capitalize()
        for word in text.split(" ")
    )


def _document(out: _Out) -> str:
    lines = ["---", f"name: {out.name}"]
    if out.contact:
        lines.append("contact:")
        for contact in out.contact:
            lines.append(f"  - text: {contact.text}")
            if contact.url:
                lines.append(f"    url: {contact.url}")
    lines += ["---", ""]

    previous = ""
    for block in out.body:
        bullets = previous.lstrip().startswith("- ") and block.lstrip().startswith("- ")
        if previous and not bullets:
            lines.append("")
        if block.startswith("#### "):
            lines.pop()  # a sub-header sits directly under its entry header
        lines.append(_wrap(block))
        previous = block
    return "\n".join(lines).rstrip() + "\n"


def _wrap(block: str) -> str:
    if block.startswith("#"):
        return block  # headings carry structure in their punctuation; never fold
    indent = "  " if block.startswith("- ") else "    " if block.startswith(" ") else ""
    return textwrap.fill(
        block,
        width=_WRAP,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    )
