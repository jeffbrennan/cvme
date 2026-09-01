from __future__ import annotations

import pytest

from cvme.errors import ParseError
from cvme.md.parse import parse
from cvme.models import BulletList, Document, Paragraph


def test_frontmatter_populates_header(resume_doc: Document) -> None:
    assert resume_doc.name == "Morgan Avery"
    assert [c.text for c in resume_doc.contact] == [
        "morgan.avery\\@example.com",
        "morganavery.example",
    ]
    assert resume_doc.contact[0].url == "mailto:morgan.avery@example.com"


def test_sections_are_captured_in_order(resume_doc: Document) -> None:
    assert [s.title for s in resume_doc.sections] == [
        "Summary",
        "Experience",
        "Education",
        "Skills",
    ]


def test_pipe_splits_left_from_right(resume_doc: Document) -> None:
    entry = resume_doc.sections[1].entries[0]
    assert entry.head.right == "Jul 2023 – Present"


def test_at_sign_splits_role_from_organisation(resume_doc: Document) -> None:
    entry = resume_doc.sections[1].entries[0]
    assert entry.head.role == "Staff Data Engineer"
    assert entry.head.org == "Northwind Analytics"


def test_entry_without_at_sign_leaves_role_unset(resume_doc: Document) -> None:
    education = resume_doc.sections[2].entries[0]
    assert education.head.role is None
    assert education.head.left == "Ridgeway University"
    assert education.sub is not None
    assert education.sub.right == "May 2020"


def test_paragraph_under_an_entry_is_a_follow_on_line(resume_doc: Document) -> None:
    blocks = resume_doc.sections[2].entries[0].blocks
    paragraph = next(b for b in blocks if isinstance(b, Paragraph))
    assert paragraph.text == "Certificate: Data Science"


def test_bullets_are_collected(resume_doc: Document) -> None:
    bullets = resume_doc.sections[1].entries[0].blocks[0]
    assert isinstance(bullets, BulletList)
    assert len(bullets.items) == 5


def test_inline_markup_is_converted_to_typst(resume_doc: Document) -> None:
    skills = resume_doc.sections[3].blocks[0]
    assert isinstance(skills, BulletList)
    assert skills.items[0].text.startswith("#strong[Languages]")


def test_fact_comments_are_stripped_and_collected() -> None:
    doc = parse(
        "## Experience\n\n### A @ B | 2020\n\n- did a thing <!-- fact: m-thing -->\n"
    )
    bullets = doc.sections[0].entries[0].blocks[0]
    assert isinstance(bullets, BulletList)
    assert bullets.items[0].text == "did a thing"
    assert doc.facts() == ["m-thing"]


def test_prose_before_any_heading_opens_an_untitled_section() -> None:
    """A cover letter is a body with no sections at all."""
    doc = parse("First paragraph.\n\nSecond paragraph.\n")
    assert [s.title for s in doc.sections] == [""]
    assert len(doc.sections[0].blocks) == 2


def test_entry_before_a_section_is_an_error() -> None:
    with pytest.raises(ParseError, match="before the first"):
        parse("### Role @ Org | 2020\n")


def test_unclosed_frontmatter_is_an_error() -> None:
    with pytest.raises(ParseError, match="never closed"):
        parse("---\nname: X\n")
