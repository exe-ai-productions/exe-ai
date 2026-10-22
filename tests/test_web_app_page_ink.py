"""The Web App page of the settings (`frontend/src/teile/SettingsWebApp.svelte`):
its state words wear the form of their colour made for type, its row names
stand as large as the other pages' rows, and the name of the page is written
as two words.

The interface has no DOM library here, so these tests read the page's source
and the two text catalogues, like `test_web_app_password_minimum.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "frontend/src/teile/SettingsWebApp.svelte"
LOCALES = ROOT / "app" / "locales"


def _style() -> str:
    text = PAGE.read_text(encoding="utf-8")
    return text[text.index("<style>"):]


def _rule(selector: str) -> str:
    found = re.findall(r"\n  " + re.escape(selector) + r" \{(.*?)\}", _style(), re.S)
    assert len(found) == 1, selector
    return found[0]


def _catalogue(language: str) -> dict:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)


def test_every_state_word_wears_the_text_form_of_its_colour():
    assert "color: var(--gruen-text)" in _rule(".word.green")
    assert "color: var(--gelb-text)" in _rule(".word.yellow")
    assert "color: var(--rot-text)" in _rule(".word.red")
    assert "color: var(--rot-text)" in _rule(".sentence")


def test_no_rule_of_the_page_sets_a_plain_state_colour_as_type():
    plain = re.findall(r"(?<![-\w])color:\s*var\(--(gruen|gelb|rot|blau)\)", _style())
    assert plain == [], plain


def test_the_row_names_are_medium_and_as_large_as_the_text_of_the_other_pages():
    label = _rule(".label")
    assert "font: 500 var(--schrift-text) / 1.4 var(--schrift)" in label
    assert "color: var(--text)" in label


def test_the_state_words_and_the_buttons_keep_their_size():
    word = _rule(".word")
    assert "font-size: 13px" in word and "font-weight: 500" in word


def test_the_web_app_is_written_with_a_hyphen_in_german_and_as_two_words_in_english():
    german = _catalogue("de")
    assert german["webapp"]["title"] == "Web-App"
    assert _catalogue("en")["webapp"]["title"] == "Web App"
    assert "Web-App" in german["webapp"]["phone"]


def test_the_english_sentences_are_as_they_were():
    english = _catalogue("en")["webapp"]
    assert english["phone"] == "The web app on a phone"
    assert [text for text in _strings(english) if "Web-App" in text] == []
