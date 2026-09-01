"""Turn a parsed document into a PDF.

The whole job is assembled in memory as a virtual filesystem and handed to the
Typst compiler in one call: no temp directories, and the exact inputs are
available to tests as bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import typst

from cvme.errors import RenderError
from cvme.md.inline import to_plain
from cvme.models import Document
from cvme.render.fonts import font_paths
from cvme.style.schema import Style

TEMPLATE_DIR = Path(__file__).parent / "templates"

# typst-py's stub types `input` and `output` with a single constrained TypeVar,
# so it rejects the dict-of-files form that the runtime accepts and that this
# module relies on. Narrow the discrepancy to one place rather than scattering
# ignores over every call site.
_typst_compile = cast(Any, typst.compile)

#: Fixed timestamp so that identical input yields byte-identical output, which
#: is what makes golden-file comparison possible.
REPRODUCIBLE_TIMESTAMP = 0


def document_payload(doc: Document) -> dict[str, Any]:
    """Serialise the IR into the shape the template expects."""
    payload = doc.model_dump()
    # PDF metadata is literal text, so recover it from the markup.
    payload["name_plain"] = to_plain(doc.name)
    payload["title"] = doc.meta.get("title") or payload["name_plain"]
    payload["keywords"] = [
        k.strip() for k in doc.meta.get("keywords", "").split(",") if k.strip()
    ]
    return payload


def build_sources(
    doc: Document, style: Style, template: str = "resume"
) -> dict[str, bytes]:
    """Build the virtual filesystem handed to the compiler."""
    path = TEMPLATE_DIR / f"{template}.typ"
    if not path.exists():
        raise RenderError(f"no template named '{template}'")
    return {
        "main.typ": path.read_bytes(),
        "document.json": json.dumps(document_payload(doc)).encode(),
        "style.json": json.dumps(style.dump()).encode(),
    }


def compile_document(
    doc: Document,
    style: Style,
    *,
    output: Path,
    template: str = "resume",
    fmt: str = "pdf",
    ppi: float | None = None,
) -> Path:
    """Compile to ``output``. Returns the path written."""
    sources = build_sources(doc, style, template)
    kwargs: dict[str, Any] = {
        "root": ".",
        "font_paths": font_paths(),
        "ignore_system_fonts": True,
        "timestamp": REPRODUCIBLE_TIMESTAMP,
    }
    if style.pdf_standard:
        kwargs["pdf_standards"] = [style.pdf_standard]
    if fmt != "pdf":
        kwargs["format"] = fmt
        if ppi is not None:
            kwargs["ppi"] = ppi
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        _typst_compile(sources, output=str(output), **kwargs)
    except Exception as exc:  # typst raises its own error type
        raise RenderError(str(exc)) from exc
    return output
