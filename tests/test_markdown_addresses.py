"""A bare address in an answer is a link, like one written with brackets.

The real renderer (`lib/markdown.js`) is run in node, the way
``tests/test_markdown_bilder.py`` runs it. The cut of the address — sentence
marks behind it stay out — is the rule of the own message (`adressTeile`),
used here once more, not written a second time.
"""

from __future__ import annotations

import json
import shutil

import pytest

from tests.test_hintergrundmeldung import _modul, _node

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

STAND_IN = """
globalThis.location = { origin: 'http://127.0.0.1:8273' };
const hervorheben = (code) => String(code);
const t = () => 'Copy';
const dateiart = () => null;
const dateiname = (sprache, nummer) => sprache + '-' + nummer;
"""

LINK = '<a href="{0}" target="_blank" rel="noopener noreferrer">{1}</a>'


def _drawn(text: str) -> str:
    return _node(f"{_modul(STAND_IN)}\nconsole.log(rendern({json.dumps(text)}))")


@needs_node
def test_a_bare_address_with_a_full_stop_behind_it_is_a_link_without_the_stop():
    html = _drawn("See https://example.com.")
    assert LINK.format("https://example.com", "https://example.com") + "." in html


@needs_node
def test_an_address_with_a_query_and_a_path_keeps_them_and_masks_the_ampersand():
    html = _drawn("Open http://example.com/a/b?x=1&y=2 now")
    assert LINK.format("http://example.com/a/b?x=1&amp;y=2", "http://example.com/a/b?x=1&amp;y=2") in html


@needs_node
def test_an_address_in_angle_brackets_or_quotes_is_cut_at_them():
    html = _drawn('See <https://example.com/x> and "https://example.org/y" there.')
    assert LINK.format("https://example.com/x", "https://example.com/x") in html
    assert LINK.format("https://example.org/y", "https://example.org/y") in html
    assert "&gt;" in html and "&quot;" in html


@needs_node
def test_an_address_in_bold_text_or_a_list_or_a_table_is_a_link():
    assert LINK.format("https://example.com", "https://example.com") in _drawn("**Go to https://example.com now**")
    assert LINK.format("https://example.com", "https://example.com") in _drawn("- https://example.com")
    table = _drawn("| name | page |\n| --- | --- |\n| a | https://example.com |")
    assert "<td>" + LINK.format("https://example.com", "https://example.com") + "</td>" in table


@needs_node
def test_a_closing_bracket_is_part_of_the_address_only_with_its_opening_one():
    wiki = _drawn("https://en.wikipedia.org/wiki/Heat_(film)")
    assert LINK.format("https://en.wikipedia.org/wiki/Heat_(film)", "https://en.wikipedia.org/wiki/Heat_(film)") in wiki
    after = _drawn("(see https://example.com)")
    assert LINK.format("https://example.com", "https://example.com") + ")" in after


@needs_node
def test_a_link_with_brackets_stays_exactly_one_link():
    """Silence probe: `[Text](Adresse)` is one `<a>`, its text is no second."""
    html = _drawn("[Text](https://example.com)")
    assert html.count("<a ") == 1
    assert LINK.format("https://example.com", "Text") in html
    both = _drawn("[https://example.com](https://example.com)")
    assert both.count("<a ") == 1


@needs_node
def test_an_address_in_code_stays_text():
    """Silence probe: a span in backticks stays a code span, and a fenced
    block is a block."""
    span = _drawn("run `curl https://example.com` once")
    assert "<code>curl https://example.com</code>" in span
    assert "<a " not in span
    fenced = _drawn("```\ncurl https://example.com\n```")
    assert "<a " not in fenced


@needs_node
def test_text_without_an_address_is_drawn_as_before():
    html = _drawn("A **plain** answer with `code` and 3 < 4.")
    assert "<a " not in html
    assert "<strong>plain</strong>" in html and "<code>code</code>" in html
    assert "3 &lt; 4" in html


@needs_node
def test_a_bare_scheme_without_a_host_is_no_link():
    assert "<a " not in _drawn("Write https:// in front.")
