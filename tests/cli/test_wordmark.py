"""The wordmark as the script generated it: block letters of one font,
every line as wide as the others, nothing in it but the strokes of that
font — and the name in one line for a window that has no room for them."""

from __future__ import annotations

from cli import wordmark

# The size the letters are set at, and the strokes the font is made of.
WIDTH = 55
HEIGHT = 6
STROKES = set("█╗╔╝╚║═ ")


def test_the_letters_have_their_size_and_every_line_is_as_wide_as_the_others():
    assert len(wordmark.WORDMARK) == HEIGHT
    assert {len(line) for line in wordmark.WORDMARK} == {WIDTH}
    assert (wordmark.WIDTH, wordmark.HEIGHT) == (WIDTH, HEIGHT)


def test_the_letters_are_made_of_the_fonts_strokes_alone():
    for line in wordmark.WORDMARK:
        assert set(line) <= STROKES, line
    # No line is empty, and the first and the last column are both used:
    # nothing of the margin is part of the letters themselves.
    assert all(line.strip() for line in wordmark.WORDMARK)
    assert any(line[0] != " " for line in wordmark.WORDMARK)
    assert any(line[-1] != " " for line in wordmark.WORDMARK)


def test_the_name_in_one_line_is_the_prompt_and_the_name():
    assert wordmark.WORDMARK_PLAIN == ">_ Exe AI"


def test_the_module_says_it_is_generated():
    source = " ".join(open(wordmark.__file__, encoding="utf-8").read().split())
    assert "never edited by hand" in source
