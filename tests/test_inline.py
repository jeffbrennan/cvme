from __future__ import annotations

import pytest

from cvme.md.inline import escape, extract_facts, split_at, split_pipe, to_typst


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("plain text", "plain text"),
        ("**bold**", "#strong[bold]"),
        ("*em*", "#emph[em]"),
        ("`code`", "`code`"),
        ("[label](https://x.example)", '#link("https://x.example")[label]'),
    ],
)
def test_inline_markdown_becomes_typst(source: str, expected: str) -> None:
    assert to_typst(source)[0] == expected


@pytest.mark.parametrize("char", list("\\#$*_`<>@[]~"))
def test_typst_special_characters_are_escaped(char: str) -> None:
    """Unescaped specials either corrupt layout or fail the compile outright.

    An address like ``a@b.com`` is the case that bites: Typst reads ``@b`` as a
    label reference and refuses to compile.
    """
    assert escape(f"x{char}y") == f"x\\{char}y"


def test_pipe_splits_once_and_trims() -> None:
    assert split_pipe("Role @ Org | Jan 2020") == ("Role @ Org", "Jan 2020")


def test_escaped_pipe_is_not_a_split() -> None:
    assert split_pipe(r"a \| b") == (r"a \| b", "")


def test_at_split_requires_surrounding_spaces() -> None:
    assert split_at("Role @ Org") == ("Role", "Org")
    assert split_at("a@b.com") == ("a@b.com", None)


def test_facts_are_extracted_and_removed() -> None:
    text, facts = extract_facts("claim <!-- fact: m-one --> more <!-- fact: m-two -->")
    assert facts == ["m-one", "m-two"]
    assert "fact:" not in text
