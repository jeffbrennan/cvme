"""Convert markdown inline content to Typst markup.

Kept separate from the block parser because escaping is the fiddly part: Typst
gives syntactic meaning to characters that appear routinely in resume prose
(``#``, ``@``, ``*``, ``_``, ``$``), and any of them arriving unescaped either
corrupts the layout or fails the compile.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

#: Characters Typst treats as markup and which therefore must be escaped in
#: text taken from the source document.
_SPECIAL = set("\\#$*_`<>@[]~")

_FACT_RE = re.compile(r"<!--\s*fact:\s*([A-Za-z0-9_.-]+)\s*-->")

_md = MarkdownIt("commonmark")


def escape(text: str) -> str:
    """Escape Typst markup characters in a run of literal text."""
    return "".join(f"\\{c}" if c in _SPECIAL else c for c in text)


def extract_facts(source: str) -> tuple[str, list[str]]:
    """Strip ``<!-- fact: id -->`` comments, returning the text and the ids."""
    facts = _FACT_RE.findall(source)
    return _FACT_RE.sub("", source).strip(), facts


def _render(tokens: list[Token]) -> str:
    out: list[str] = []
    for token in tokens:
        match token.type:
            case "text":
                out.append(escape(token.content))
            case "code_inline":
                out.append(f"`{token.content}`")
            case "softbreak":
                out.append(" ")
            case "hardbreak":
                out.append(" \\ ")
            case "strong_open":
                out.append("#strong[")
            case "em_open":
                out.append("#emph[")
            case "strong_close" | "em_close":
                out.append("]")
            case "link_open":
                href = token.attrGet("href") or ""
                out.append(f'#link("{href}")[')
            case "link_close":
                out.append("]")
            case "html_inline":
                pass  # fact comments are stripped before we get here
            case _:
                if token.children:
                    out.append(_render(token.children))
                elif token.content:
                    out.append(escape(token.content))
    return "".join(out)


def to_typst(source: str) -> tuple[str, list[str]]:
    """Render one run of markdown inline content, returning markup and facts."""
    text, facts = extract_facts(source)
    tokens = _md.parseInline(text)
    body = "".join(_render(t.children or []) for t in tokens)
    return body.strip(), facts


def render_tokens(inline: Token | None) -> str:
    """Render an already-tokenised ``inline`` token."""
    return _render(inline.children or []).strip() if inline is not None else ""


_MARKUP_OPEN = re.compile(r'#(?:strong|emph)\[|#link\("[^"]*"\)\[')


def to_plain(markup: str) -> str:
    """Recover readable text from Typst markup, for diagnostics and metadata."""
    text = _MARKUP_OPEN.sub("", markup).replace("]", "")
    return re.sub(r"\\(.)", r"\1", text).replace("`", "")


def split_pipe(source: str) -> tuple[str, str]:
    """Split on the first unescaped ``|`` into left and right halves."""
    return _split(source, "|")


def split_at(source: str) -> tuple[str, str | None]:
    """Split on the first unescaped `` @ `` into role and organisation."""
    left, right = _split(source, "@", require_spaces=True)
    return (left, right) if right else (left, None)


def _split(source: str, char: str, *, require_spaces: bool = False) -> tuple[str, str]:
    i = 0
    while i < len(source):
        if source[i] == "\\":
            i += 2
            continue
        if source[i] == char:
            spaced = source[i - 1 : i] == " " and source[i + 1 : i + 2] == " "
            if not require_spaces or spaced:
                return source[:i].strip(), source[i + 1 :].strip()
        i += 1
    return source.strip(), ""


def unescape_source(source: str) -> str:
    """Undo the grammar's own escapes (``\\|``, ``\\@``) before inline parsing."""
    return re.sub(r"\\([|@])", r"\1", source)
