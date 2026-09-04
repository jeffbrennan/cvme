"""Convert an existing PDF resume into the cvme markdown grammar.

The pipeline is the render pipeline read backwards: glyphs and their positions
become styled lines (``pdftext``), styled lines become document structure
(``structure``), and structure is written back out as the grammar the parser
already accepts. Converting is therefore only ever a starting point -- a PDF
does not record what its author meant -- but the result parses, renders and
verifies like any hand-written source.
"""

from __future__ import annotations

from pathlib import Path

from cvme.convert.pdftext import Layout, read
from cvme.convert.structure import to_markdown
from cvme.errors import ConvertError, ParseError
from cvme.md.parse import parse

__all__ = ["ConvertError", "Layout", "convert_file", "pdf_to_markdown", "read"]


def pdf_to_markdown(path: Path) -> str:
    """Read a PDF and return it as cvme markdown."""
    return to_markdown(read(path))


def convert_file(source: Path, output: Path) -> str:
    """Convert ``source`` to markdown at ``output``, checking it parses."""
    markdown = pdf_to_markdown(source)
    try:
        parse(markdown, path=str(output))
    except ParseError as exc:  # a converter bug, not bad input from the user
        raise ConvertError(
            f"converted {source} into a document that will not parse: {exc}"
        ) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    return markdown
