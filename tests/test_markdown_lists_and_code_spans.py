"""Lists keep their nesting and their count, and code spans stay literal.

The real renderer (`lib/markdown.js`) is run in node, the way
``tests/test_markdown_addresses.py`` runs it:

* a list indented under an item stands inside that item, as deep as the
  indentation goes; a numbered list inside another counts for itself; a numbered
  list starts at the number of its first item; a blank line between two items
  does not start the count again; an indented line goes on with the open item;
* between backticks nothing is read — asterisks, tildes, brackets and addresses
  stand character for character in the ``<code>``.
"""

from __future__ import annotations

import re
import shutil

import pytest

from tests.test_markdown_addresses import _drawn

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _flat(html: str) -> str:
    """The markup without the line breaks the renderer puts between blocks."""
    return html.replace("\n", "")


@needs_node
def test_an_indented_list_stands_inside_its_item_as_deep_as_the_indentation_goes():
    html = _flat(_drawn("- A\n  - A1\n    - A1a\n- B"))
    assert html == (
        "<ul><li>A<ul><li>A1<ul><li>A1a</li></ul></li></ul></li><li>B</li></ul>"
    )


@needs_node
def test_a_numbered_list_inside_a_numbered_list_counts_for_itself():
    html = _flat(_drawn("1. Eins\n2. Zwei\n   1. Unter\n3. Drei"))
    assert html == "<ol><li>Eins</li><li>Zwei<ol><li>Unter</li></ol></li><li>Drei</li></ol>"


@needs_node
def test_a_bulleted_list_inside_a_numbered_one_and_back():
    html = _flat(_drawn("1. A\n   - x\n   - y\n2. B"))
    assert html == "<ol><li>A<ul><li>x</li><li>y</li></ul></li><li>B</li></ol>"


@needs_node
def test_a_numbered_list_starts_with_the_number_of_its_first_item():
    html = _flat(_drawn("3. Drei\n4. Vier"))
    assert html == '<ol start="3"><li>Drei</li><li>Vier</li></ol>'
    assert "start=" not in _drawn("1. Eins\n2. Zwei")


@needs_node
def test_a_blank_line_between_two_items_does_not_start_the_count_again():
    html = _flat(_drawn("1. Eins\n\n2. Zwei"))
    assert html == "<ol><li>Eins</li><li>Zwei</li></ol>"
    assert _flat(_drawn("- a\n\n- b")) == "<ul><li>a</li><li>b</li></ul>"


@needs_node
def test_an_indented_line_goes_on_with_the_open_item_and_is_no_paragraph():
    html = _flat(_drawn("- A long item that\n  runs on a second line\n- Next"))
    assert html == "<ul><li>A long item that runs on a second line</li><li>Next</li></ul>"


@needs_node
def test_text_that_is_not_indented_ends_the_list_and_is_a_paragraph():
    html = _flat(_drawn("- a\n- b\nplain text"))
    assert html == "<ul><li>a</li><li>b</li></ul><p>plain text</p>"
    assert _flat(_drawn("- a\n\nplain text")) == "<ul><li>a</li></ul><p>plain text</p>"


@needs_node
def test_a_list_after_a_nested_one_goes_on_at_the_outer_level():
    html = _flat(_drawn("- a\n  - a1\n- b\n  - b1"))
    assert html == "<ul><li>a<ul><li>a1</li></ul></li><li>b<ul><li>b1</li></ul></li></ul>"


@needs_node
def test_a_tab_indents_like_four_blanks_and_a_heading_ends_the_list():
    assert _flat(_drawn("- a\n\t- tab")) == "<ul><li>a<ul><li>tab</li></ul></li></ul>"
    assert _flat(_drawn("- a\n  # head\n- b")) == "<ul><li>a</li></ul><h2>head</h2><ul><li>b</li></ul>"


@needs_node
def test_a_code_block_between_two_items_ends_the_list_and_the_count_goes_on():
    html = _drawn("1. Step\n   ```bash\n   ls\n   ```\n2. Next")
    assert "<ol>\n<li>Step</li>\n</ol>" in html
    assert '<ol start="2">\n<li>Next</li>\n</ol>' in html


@needs_node
@pytest.mark.parametrize(
    "span",
    ["2*3*4", "x**2 + y**2", "~~a~~", "[x](https://example.com)", "https://example.com/a_b", "a*b* c*d*"],
)
def test_between_backticks_nothing_is_read(span):
    html = _drawn(f"Run `{span}` now, **bold** stays.")
    assert f"<code>{span}</code>" in html
    inside = re.search(r"<code>(.*?)</code>", html).group(1)
    assert not re.search(r"<(em|strong|del|a)[ >]", inside)
    assert "<strong>bold</strong>" in html


@needs_node
def test_silence_flat_lists_emphasis_paths_and_numbers_draw_as_before():
    assert _flat(_drawn("- a\n- b\n- c")) == "<ul><li>a</li><li>b</li><li>c</li></ul>"
    assert _flat(_drawn("1. a\n2. b")) == "<ol><li>a</li><li>b</li></ol>"
    html = _drawn("**fett** und *kursiv* und ~~weg~~ und app/__init__.py")
    assert "<strong>fett</strong>" in html and "<em>kursiv</em>" in html and "<del>weg</del>" in html
    assert "app/__init__.py" in html and "<em>" not in html.replace("<em>kursiv</em>", "")
    # A bare number or `datei1` on a line of its own stands as a paragraph, not
    # as a list or a marker of a block.
    assert _drawn("42") == "<p>42</p>"
    assert _drawn("datei1") == "<p>datei1</p>"
    assert _flat(_drawn("- a\n42")) == "<ul><li>a</li></ul><p>42</p>"
    assert _flat(_drawn("# Titel\n\n> Zitat")) == "<h2>Titel</h2><blockquote>Zitat</blockquote>"


@needs_node
def test_silence_a_link_outside_code_and_an_address_stay_links():
    html = _drawn("See [x](https://example.com) and https://example.org here.")
    assert html.count("<a ") == 2


@needs_node
def test_silence_a_table_after_a_list_closes_the_list():
    html = _flat(_drawn("- a\n- b\n\n| h |\n| --- |\n| c |"))
    assert html.startswith("<ul><li>a</li><li>b</li></ul><table>")
