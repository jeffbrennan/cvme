from __future__ import annotations

from pathlib import Path

import pytest

from cvme.md.parse import parse_file
from cvme.models import Document
from cvme.render.engine import compile_document
from cvme.style.schema import Style, resolve

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def resume_source() -> Path:
    return FIXTURES / "resume.md"


@pytest.fixture(scope="session")
def resume_doc(resume_source: Path) -> Document:
    return parse_file(resume_source)


@pytest.fixture(scope="session")
def standard() -> Style:
    return resolve("standard")


@pytest.fixture(scope="session")
def resume_pdf(resume_doc: Document, standard: Style, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("render") / "resume.pdf"
    return compile_document(resume_doc, standard, output=out)
