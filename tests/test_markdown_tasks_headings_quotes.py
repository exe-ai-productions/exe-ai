"""Task items, deep headings and quotes of several paragraphs.

The real renderer (`lib/markdown.js`) is run in node, the way
``tests/test_markdown_addresses.py`` runs it:

* a list item that begins with `[ ]`, `[x]` or `[X]` and a blank gets a locked
  box in front of its text, ticked for an x — in bulleted lists, numbered
  lists and nested lists; without the blank, or in the middle of a sentence or
  in a code block, it stays text;
* `#####` and `######` are headings like `####`; seven hashes are text;
* a quote whose paragraphs are parted by a line of its own marker shows them
  apart inside one quote, and a quote of one paragraph is drawn as before.
"""

from __future__ import annotations

import re
import shutil

import pytest

from tests.test_markdown_addresses import _drawn

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

OPEN_BOX = '<input type="checkbox" disabled>'
TICKED_BOX = '<input type="checkbox" disabled checked>'


def _flat(html: str) -> str:
    """The markup without the line breaks the renderer puts between blocks."""
    return html.replace("\n", "")


@needs_node
def test_task_items_get_a_locked_box_ticked_for_an_x():
    html = _flat(_drawn("- [ ] open\n- [x] done\n- [X] also done"))
    assert html == (
        f"<ul><li>{OPEN_BOX} open</li><li>{TICKED_BOX} done</li><li>{TICKED_BOX} also done</li></ul>"
    )
    assert "[" not in html


@needs_node
def test_a_numbered_list_takes_task_items_too():
    html = _flat(_drawn("1. [ ] one\n2. [x] two"))
    assert html == f"<ol><li>{OPEN_BOX} one</li><li>{TICKED_BOX} two</li></ol>"


@needs_node
def test_a_task_item_inside_a_task_item_has_a_box_of_its_own():
    html = _flat(_drawn("- [x] foo\n  - [ ] bar"))
    assert html == f"<ul><li>{TICKED_BOX} foo<ul><li>{OPEN_BOX} bar</li></ul></li></ul>"


@needs_node
def test_a_task_item_goes_on_over_an_indented_line():
    html = _flat(_drawn("- [ ] a long task that\n  runs on a second line"))
    assert html == f"<ul><li>{OPEN_BOX} a long task that runs on a second line</li></ul>"


@needs_node
def test_a_bracket_without_a_blank_after_it_stays_text():
    assert _flat(_drawn("- [x]foo")) == "<ul><li>[x]foo</li></ul>"
    assert _flat(_drawn("- [] none")) == "<ul><li>[] none</li></ul>"


@needs_node
def test_a_bracket_in_a_sentence_or_in_code_stays_text():
    assert _flat(_drawn("Done is [x] in the middle")) == "<p>Done is [x] in the middle</p>"
    html = _drawn("```\n- [ ] in code\n```")
    assert "<input" not in html and "- [ ] in code" in html


@needs_node
def test_the_deep_headings_look_like_the_fourth_level():
    four = _flat(_drawn("#### Four"))
    assert _flat(_drawn("##### Five")) == four.replace("Four", "Five")
    assert _flat(_drawn("###### Six")) == four.replace("Four", "Six")


@needs_node
def test_seven_hashes_are_text():
    assert _flat(_drawn("####### Too deep")) == "<p>####### Too deep</p>"


@needs_node
def test_two_paragraphs_in_a_quote_stand_apart_in_one_quote():
    html = _flat(_drawn("> one\n>\n> two"))
    assert html == "<blockquote><p>one</p><p>two</p></blockquote>"


@needs_node
def test_a_quote_of_one_paragraph_is_drawn_as_before():
    assert _flat(_drawn("> one\n> goes on")) == "<blockquote>one goes on</blockquote>"
    assert _flat(_drawn("# Head\n\n> Quote")) == "<h2>Head</h2><blockquote>Quote</blockquote>"


@needs_node
def test_a_quote_holds_lists_and_headings_by_the_same_rules():
    html = _flat(_drawn("> # Head\n> - a\n> - b\n>\n> text"))
    assert html == "<blockquote><h2>Head</h2><ul><li>a</li><li>b</li></ul><p>text</p></blockquote>"
    assert _flat(_drawn("> > inner")) == "<blockquote><blockquote>inner</blockquote></blockquote>"


@needs_node
def test_a_fence_in_a_quote_still_draws_its_block():
    html = _drawn("> ```bash\n> ls\n> ```\n> after")
    assert re.search(r'<div class="codeblock[^"]*">', html)
    assert "<code>ls</code>" in html
    assert "<blockquote>after</blockquote>" in _flat(html)


@needs_node
def test_silence_plain_text_lists_and_quotes_draw_as_before():
    assert _flat(_drawn("- a\n- b")) == "<ul><li>a</li><li>b</li></ul>"
    assert _flat(_drawn("# One\n## Two\n### Three\n#### Four")) == (
        "<h2>One</h2><h3>Two</h3><h4>Three</h4><h5>Four</h5>"
    )
    assert _flat(_drawn("> a\n\n> b")) == "<blockquote>a</blockquote><blockquote>b</blockquote>"
    assert _drawn("42") == "<p>42</p>" and _drawn("datei1") == "<p>datei1</p>"
