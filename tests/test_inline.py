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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # The case that put " ," on a rendered page: the citation sits between
        # the word and its punctuation.
        ("30+ analysts <!-- fact: m-one -->, covering", "30+ analysts, covering"),
        ("matched a client <!-- fact: m-one -->; rebuilt", "matched a client; rebuilt"),
        ("about five minutes <!-- fact: m-one -->.", "about five minutes."),
        # Mid-sentence, the space is still one space.
        ("7B rows <!-- fact: m-one --> rewritten", "7B rows rewritten"),
        # Wrapped across a line, the softbreak supplies the space.
        ("30 sources <!-- fact: m-one -->\nand more", "30 sources\nand more"),
        # A leading citation leaves no indent behind.
        ("<!-- fact: m-one --> claim", "claim"),
    ],
)
def test_removing_a_citation_closes_the_gap(source: str, expected: str) -> None:
    text, facts = extract_facts(source)
    assert text == expected
    assert facts == ["m-one"]


def test_a_hardbreak_away_from_a_citation_survives() -> None:
    text, _ = extract_facts("a claim <!-- fact: m-one --> here  \nnext line")
    assert text == "a claim here  \nnext line"
