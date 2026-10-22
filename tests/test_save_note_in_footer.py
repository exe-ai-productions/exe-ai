"""The answer of a save on the credentials, configuration and tools-file
pages: it stands left in the foot, in the line of the two signs, and nothing is
said above the chat for these three pages. The other editor pages keep their
notice. Read off the source, the way the other interface tests do.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "frontend" / "src" / "teile" / "SystemPrompt.svelte").read_text(encoding="utf-8")
MARKUP, STYLE = SOURCE.split("<style>", 1)


def _save_function() -> str:
    return SOURCE.split("async function sichern() {", 1)[1].split("\n  /* ``name`` is the agent", 1)[0]


def _branch(marker: str, until: str) -> str:
    return _save_function().split(marker, 1)[1].split(until, 1)[0]


def _catalogue(language: str) -> dict[str, dict[str, str]]:
    path = ROOT / "app" / "locales" / f"{language}.json"
    data: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_the_files_pages_answer_in_the_foot_and_no_longer_above_the_chat():
    files = _branch("} else if (istDatei) {", "} else if (istTools) {")
    assert "saveNote = {" in files
    assert "'dateien.gesichert_kaputt' : 'dateien.gesichert'" in files
    assert "melde(" not in files
    tools = _branch("} else if (istTools) {", "} else {")
    assert "saveNote = {" in tools
    assert "'werkzeuge.gesichert_kaputt' : 'werkzeuge.gesichert'" in tools
    assert "melde(" not in tools


def test_the_other_editor_pages_keep_their_notice_and_a_failed_save_stays_an_error():
    save = _save_function()
    assert "melde(daten.text ? t('systemprompt.gesichert')" in save
    assert "melde(daten.text ? t('gedaechtnis.gesichert')" in save
    assert "meldeText('agenten.gesichert'" in save
    assert "melde(t(meldeschluessel('nicht_gesichert')), 'fehler')" in save


def test_the_note_stands_left_in_the_foot_before_the_signs_in_one_line():
    foot = MARKUP.split('<div class="fuss">', 1)[1].split("{/snippet}", 1)[0]
    assert '<span class="save-note" class:caution={shownNote?.caution} role="status">' in foot
    assert "{#if shownNote}{t(shownNote.key)}{/if}" in foot
    assert foot.index('class="save-note"') < foot.index('<div class="rechts">')
    # The signs stay where they were, behind the note.
    assert foot.index('<div class="rechts">') < foot.index('zeichen="kreuz"') < foot.index('zeichen="save"')
    rule = STYLE.split("\n  .fuss {", 1)[1].split("}", 1)[0]
    assert "display: flex" in rule and "align-items: center" in rule


def test_a_long_note_takes_two_lines_and_the_signs_stay_right():
    note = STYLE.split("\n  .save-note {", 1)[1].split("}", 1)[0]
    assert "flex: 1" in note and "min-width: 0" in note
    assert "white-space" not in note
    assert "flex: none" in STYLE.split("\n  .rechts {", 1)[1].split("}", 1)[0]


def test_the_note_stands_until_the_field_changes_or_another_page_opens():
    assert "const shownNote = $derived(saveNote && saveNote.saved === text ? saveNote : null)" in MARKUP
    assert "saved: geladen" in _save_function()
    load = SOURCE.split("async function laden(neueArt, name = '') {", 1)[1].split("try {", 1)[0]
    assert load.count("saveNote = null") == 2


def test_a_save_in_flight_takes_the_last_answer_down_and_a_late_one_stays_with_its_page():
    save = _save_function()
    head = save.split("try {", 1)[0]
    assert "const savedPage = art" in head and "saveNote = null" in head
    # Both file branches write the note only while the same page is open.
    assert save.count("if (art === savedPage) {") == 2


def test_the_caution_for_an_invalid_file_is_the_one_sentence_that_names_the_previous_version():
    caution = STYLE.split("\n  .save-note.caution {", 1)[1].split("}", 1)[0]
    assert "var(--gelb-text)" in caution
    # The red box about the broken file stays beside it, over the field of a
    # file page and under the page's own part on the others.
    assert "{#if filePage && (kaputt || unlesbar)}" in MARKUP
    assert "{#if !filePage && (kaputt || unlesbar)}" in MARKUP
    for language in ("de", "en"):
        assert _catalogue(language)["dateien"]["gesichert_kaputt"]
        assert _catalogue(language)["werkzeuge"]["gesichert_kaputt"]
    assert ".vorher" in _catalogue("en")["dateien"]["gesichert_kaputt"]
