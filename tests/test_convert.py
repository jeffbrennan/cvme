"""Reading a PDF back into the grammar.

The strongest assertion available here is a round trip: render the fixture,
convert the resulting PDF, and require the same intermediate representation
back. It exercises extraction, spacing, structure and emission at once, and it
fails loudly if the renderer and the converter ever disagree about what a
document looks like.

The unit tests around it cover the cases a rendered fixture cannot produce --
chiefly a PDF that carries no space glyphs at all, which is what word
processors emit and therefore what most real resumes are.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter
from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.convert import pdf_to_markdown
from cvme.convert.pdftext import Line, Run, _runs, read
from cvme.convert.structure import _inline, _split_right, _title, to_markdown
from cvme.errors import ConvertError
from cvme.md.parse import parse
from cvme.models import Block, Bullet, BulletList, Document, Paragraph

runner = CliRunner()


def _char(
    text: str,
    x0: float,
    *,
    width: float = 5.0,
    size: float = 11.0,
    font: str = "ABCDEF+Calibri",
    baseline: float = 700.0,
) -> dict:
    return {
        "text": text,
        "x0": x0,
        "x1": x0 + width,
        "size": size,
        "fontname": font,
        "top": 792 - baseline - size,
        "bottom": 792 - baseline,
        "matrix": (1, 0, 0, 1, x0, baseline),
    }


def _bullets(block: Block) -> list[Bullet]:
    assert isinstance(block, BulletList)
    return block.items


def _line(*runs: Run) -> Line:
    return Line(page=1, baseline=700.0, runs=runs)


def _run(text: str, x0: float, x1: float, **kwargs) -> Run:
    return Run(text=text, x0=x0, x1=x1, size=11.0, **kwargs)


@pytest.fixture(scope="session")
def converted(resume_pdf: Path) -> Document:
    return parse(pdf_to_markdown(resume_pdf))


def _facts_cleared(document: Document) -> Document:
    """A copy with fact ids dropped: comments leave no trace in a PDF."""
    copy = document.model_copy(deep=True)
    for section in copy.sections:
        for blocks in [section.blocks, *(e.blocks for e in section.entries)]:
            for block in blocks:
                if isinstance(block, Paragraph):
                    block.facts = []
                elif isinstance(block, BulletList):
                    for item in block.items:
                        item.facts = []
    return copy


def test_round_trip_reproduces_the_document(converted: Document, resume_doc: Document):
    assert converted.sections == _facts_cleared(resume_doc).sections


def test_round_trip_reproduces_the_letterhead(
    converted: Document, resume_doc: Document
) -> None:
    assert converted.name == resume_doc.name
    assert converted.contact == resume_doc.contact


def test_spaces_are_rebuilt_when_the_pdf_has_no_space_glyphs() -> None:
    """Word emits positioned glyphs and no spaces; the gaps are the spaces."""
    chars = []
    x = 57.6
    for word in ("Data", "Engineer", "at", "Medisolv"):
        for letter in word:
            chars.append(_char(letter, x))
            x += 5.0  # glyphs within a word butt up against each other
        x += 2.5  # a Calibri space at 11pt
    assert _runs(chars, [])[0].text == "Data Engineer at Medisolv"


def test_kerning_inside_a_word_is_not_read_as_a_space() -> None:
    chars = [_char("A", 57.6), _char("V", 62.4), _char("E", 67.1)]
    assert _runs(chars, [])[0].text == "AVE"


def test_weight_splits_a_run_and_keeps_the_space_between_them() -> None:
    chars = [
        *(
            _char(c, 57.6 + i * 5, font="ABCDEF+Calibri-Bold")
            for i, c in enumerate("Role")
        ),
        *(_char(c, 80.1 + i * 5) for i, c in enumerate("Org")),
    ]
    runs = _runs(chars, [])
    assert [(run.text, run.bold) for run in runs] == [("Role", True), (" Org", False)]


def test_emphasis_comes_from_the_font_weight() -> None:
    line = _line(_run("Python", 57.6, 90.0, bold=True), _run(" and R", 90.0, 120.0))
    assert _inline(line.runs) == "**Python** and R"


def test_a_labels_colon_sits_outside_its_emphasis() -> None:
    """`**Languages**:` is how the grammar writes a label, not `**Languages:**`."""
    line = _line(
        _run("Languages:", 57.6, 110.0, bold=True), _run(" Python", 110.0, 150.0)
    )
    assert _inline(line.runs) == "**Languages**: Python"


def test_a_right_aligned_cluster_splits_off_the_entry_head(standard) -> None:
    from cvme.convert.pdftext import Layout

    line = _line(_run("Data Engineer", 57.6, 200.0), _run("Jul 2023", 500.0, 554.4))
    layout = Layout(
        lines=(line,), body_size=11.0, left=57.6, right=554.4, line_height=13.4
    )
    left, right = _split_right(line, layout)
    assert (_inline(left), _inline(right)) == ("Data Engineer", "Jul 2023")


def test_a_wrapped_body_line_is_not_split(standard) -> None:
    from cvme.convert.pdftext import Layout

    line = _line(_run("a sentence that runs the full measure of the page", 57.6, 554.4))
    layout = Layout(
        lines=(line,), body_size=11.0, left=57.6, right=554.4, line_height=13.4
    )
    assert _split_right(line, layout)[1] == ()


def test_uppercase_headers_come_back_as_title_case() -> None:
    assert _title("PROFESSIONAL EXPERIENCE") == "Professional Experience"
    assert _title("Skills") == "Skills"


def test_a_pdf_without_text_is_reported_as_such(tmp_path: Path) -> None:
    blank = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with blank.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ConvertError, match="no extractable text"):
        read(blank)


def test_a_missing_file_is_reported_before_reading(tmp_path: Path) -> None:
    with pytest.raises(ConvertError, match="no such file"):
        read(tmp_path / "absent.pdf")


def test_the_converted_document_renders_and_stays_one_page(
    resume_pdf: Path, tmp_path: Path, standard
) -> None:
    """A conversion is a source file like any other: it has to render."""
    from cvme.render.engine import compile_document

    document = parse(pdf_to_markdown(resume_pdf))
    out = compile_document(document, standard, output=tmp_path / "again.pdf")
    assert read(out).lines


def test_convert_writes_markdown_beside_the_pdf(
    resume_pdf: Path, tmp_path: Path
) -> None:
    source = tmp_path / "resume.pdf"
    source.write_bytes(resume_pdf.read_bytes())
    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "resume.md").read_text().startswith("---\nname: Morgan Avery")
    assert "4 sections" in result.output


def test_convert_writes_to_stdout_on_request(resume_pdf: Path) -> None:
    result = runner.invoke(app, ["convert", str(resume_pdf), "--stdout"])
    assert result.exit_code == 0
    assert "## Experience" in result.stdout


def test_convert_rejects_a_file_that_is_not_a_pdf(tmp_path: Path) -> None:
    source = tmp_path / "resume.md"
    source.write_text("---\nname: Morgan Avery\n---\n")
    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 6
    assert "expected a PDF" in result.output


def test_bullets_survive_the_round_trip(converted: Document) -> None:
    experience = next(s for s in converted.sections if s.title == "Experience")
    first = experience.entries[0]
    assert first.head.role and first.head.org
    assert len(_bullets(first.blocks[0])) == 5


def test_nested_bullets_survive_the_round_trip(tmp_path: Path, standard) -> None:
    from cvme.render.engine import compile_document

    source = """---
name: Morgan Avery
---

## Skills

- Languages
  - Python
  - SQL
"""
    pdf = compile_document(parse(source), standard, output=tmp_path / "nested.pdf")
    document = parse(pdf_to_markdown(pdf))
    bullets = _bullets(document.sections[0].blocks[0])
    assert [child.text for child in bullets[0].children] == ["Python", "SQL"]


def test_converting_a_layout_directly_needs_no_file(resume_pdf: Path) -> None:
    assert to_markdown(read(resume_pdf)).startswith("---\n")
