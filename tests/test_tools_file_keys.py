"""The keys of the tools file: a heading "Keys" over one row for each, the name
on the left and on the right only the file that holds the value — ".env" in
green with a check where the key is there, in red with a cross where it is not
(frontend/src/teile/SystemPrompt.svelte, frontend/src/phone/settings/TextFile.svelte).

The pages are single files with the service's whole state behind them, so the
markup is read from the source, the way the tests of the settings list read
it: the block, the two signs, the guard that keeps the block off every other
page, and the catalogue. The sentences the rows used to carry must be gone from
both languages.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
SRC = WURZEL / "frontend" / "src"
DESKTOP = (SRC / "teile" / "SystemPrompt.svelte").read_text(encoding="utf-8")
PHONE = (SRC / "phone" / "settings" / "TextFile.svelte").read_text(encoding="utf-8")


def _catalogue(language: str) -> dict:
    return json.loads((WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))


def _block(source: str, opening: str) -> str:
    """The text from `opening` to the `{/if}` that closes it, counting the
    `{#if` and `{/if}` in between."""
    start = source.index(opening)
    depth = 0
    for found in re.finditer(r"\{#if\b|\{/if\}", source[start:]):
        depth += 1 if found.group().startswith("{#if") else -1
        if depth == 0:
            return source[start : start + found.end()]
    raise AssertionError(f"{opening!r} is never closed")


def test_the_desktop_block_names_the_file_with_a_check_or_a_cross():
    block = _block(DESKTOP, "{#if istTools && platzhalter.length}")
    assert "werkzeuge.keys_heading" in block
    assert "werkzeuge.platzhalter_gesetzt" in block and "werkzeuge.platzhalter_fehlt" in block
    assert "eintrag.gesetzt ? 'haken' : 'kreuz'" in block
    # Colour and state go together: the dot and the word are green only for a set key.
    assert "eintrag.gesetzt ? 'gruen' : 'rot'" in block
    assert "class:set={eintrag.gesetzt}" in block and "class:missing={!eintrag.gesetzt}" in block
    # Nothing of the old sentence is assembled in the markup any more.
    assert "{eintrag.name} -" not in block


def test_the_phone_row_shows_the_same_file_with_the_same_signs():
    block = _block(PHONE, "{#if placeholders.length}")
    assert "werkzeuge.platzhalter_gesetzt" in block and "werkzeuge.platzhalter_fehlt" in block
    assert "entry.gesetzt ? 'haken' : 'kreuz'" in block
    assert "entry.gesetzt ? 'gruen' : 'rot'" in block
    assert "{entry.name} -" not in block


def test_the_block_stands_only_on_the_tools_file_and_only_with_keys():
    """Silence: no keys in the file, no block; and no other page has one."""
    assert DESKTOP.count("{#if istTools && platzhalter.length}") == 1
    assert DESKTOP.count("werkzeuge.keys_heading") == 1
    assert DESKTOP.count("werkzeuge.platzhalter_gesetzt") == 1
    # The phone reads them under the tools file alone.
    inside = _block(PHONE, "{#if kind === 'tools_datei'}")
    assert PHONE.count("werkzeuge.platzhalter_gesetzt") == inside.count("werkzeuge.platzhalter_gesetzt") == 1


def test_both_texts_are_the_name_of_the_file_and_the_old_sentences_are_gone():
    sentences = ("in der .env gesetzt", "fehlt in der .env", "set in .env", "missing in .env")
    for language, heading in (("en", "Keys"), ("de", "Schlüssel")):
        tools = _catalogue(language)["werkzeuge"]
        assert tools["platzhalter_gesetzt"] == ".env"
        assert tools["platzhalter_fehlt"] == ".env"
        assert tools["keys_heading"] == heading
        raw = (WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8")
        for sentence in sentences:
            assert sentence not in raw, (language, sentence)


def test_the_two_signs_exist_in_the_house_set():
    signs = (SRC / "teile" / "Hauszeichen.svelte").read_text(encoding="utf-8")
    assert "zeichen === 'haken'" in signs and "zeichen === 'kreuz'" in signs


def _sign_of(block: str) -> str:
    """The element that carries the check or the cross: from its opening tag to its closing one."""
    found = re.search(r'<span class="key-sign"[^>]*>.*?</span>', block, re.S)
    assert found, "the check and the cross stand in no element of their own"
    return found.group(0)


def test_the_sign_of_a_key_says_its_state_to_a_reader_that_cannot_see_it_on_the_desktop():
    sign = _sign_of(_block(DESKTOP, "{#if istTools && platzhalter.length}"))
    assert 'role="img"' in sign
    assert "aria-label={t(eintrag.gesetzt ? 'modell.schluessel_gesetzt' : 'modell.schluessel_fehlt')}" in sign
    assert "eintrag.gesetzt ? 'haken' : 'kreuz'" in sign


def test_the_sign_of_a_key_says_its_state_on_the_phone_alike():
    sign = _sign_of(_block(PHONE, "{#if placeholders.length}"))
    assert 'role="img"' in sign
    assert "aria-label={t(entry.gesetzt ? 'modell.schluessel_gesetzt' : 'modell.schluessel_fehlt')}" in sign
    assert "entry.gesetzt ? 'haken' : 'kreuz'" in sign


def test_the_name_sits_at_the_sign_and_the_visible_text_stays_the_file():
    """Silence: the word beside the sign is still the file, the name is the
    sign's alone, and the sentences the catalogue carries for it are the ones
    the table of the cloud providers uses for the same state."""
    for source, block_start in ((DESKTOP, "{#if istTools && platzhalter.length}"), (PHONE, "{#if placeholders.length}")):
        block = _block(source, block_start)
        assert "werkzeuge.platzhalter_gesetzt" in block and "werkzeuge.platzhalter_fehlt" in block
        # The name is not on the row or its word: "<name>, .env" stays as it is.
        row = block.split('<span class="key-sign"', 1)[0]
        assert "aria-label" not in row
    for language, words in (("en", ("set", "Key missing")), ("de", ("gesetzt", "Schlüssel fehlt"))):
        model = _catalogue(language)["modell"]
        assert (model["schluessel_gesetzt"], model["schluessel_fehlt"]) == words


def test_the_name_is_set_with_the_braces_of_the_notation_and_the_dot_is_a_disc_of_10_px():
    """The service names the key without the braces; the page sets them. The
    look of the list is measured in the browser (test_tools_file_keys_chrome.py)."""
    block = _block(DESKTOP, "{#if istTools && platzhalter.length}")
    assert "{'${' + eintrag.name + '}'}" in block
    assert "groesse={10}" in block and "groesse={11}" not in block
