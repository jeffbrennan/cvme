"""HTML to markdown, tuned for job descriptions.

Job description HTML is simple and badly formed in predictable ways: nested
lists, stray ``<br>``, and headings marked up as bold paragraphs. html2text
handles it, given settings that stop it introducing line wrapping and
reference-style links, both of which make the result harder to read and harder
to diff.
"""

from __future__ import annotations

import re

import html2text
from selectolax.parser import HTMLParser

_BLANKS = re.compile(r"\n{3,}")
#: Elements that never carry the posting itself.
_CHROME = "script, style, noscript, nav, header, footer, form, svg, iframe"


def _converter() -> html2text.HTML2Text:
    converter = html2text.HTML2Text()
    converter.body_width = 0  # no hard wrapping; let the file be diffable
    converter.ignore_images = True
    converter.ignore_emphasis = False
    converter.inline_links = True
    converter.protect_links = True
    converter.unicode_snob = True  # keep real characters rather than escapes
    converter.single_line_break = False
    return converter


def to_markdown(html: str) -> str:
    """Convert a fragment of description HTML to markdown."""
    if not html or not html.strip():
        return ""
    if "<" not in html:
        return html.strip()
    text = _converter().handle(html)
    return _BLANKS.sub("\n\n", text).strip()


def main_text(html: str) -> str:
    """Best-effort description from a whole saved page.

    Used for the manual path, where someone has saved a page that carries no
    JSON-LD. Picks the densest block-level element rather than guessing at
    site-specific selectors, which is crude but does not rot.
    """
    tree = HTMLParser(html)
    for node in tree.css(_CHROME):
        node.decompose()

    best, best_score = None, 0
    for node in tree.css("article, main, section, div"):
        text = node.text(separator=" ", strip=True) or ""
        # Favour long text that is mostly prose rather than link soup.
        links = len(node.css("a"))
        score = len(text) - links * 40
        if score > best_score:
            best, best_score = node, score

    chosen = best if best is not None else tree.body
    return to_markdown(chosen.html or "") if chosen is not None else ""
