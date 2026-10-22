"""The skills page of the settings: the three small sign buttons of a row and
the conditions they stand under, the main switch's new name, the foot of the
writing form as two signs, and the red question about deleting.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEILE = ROOT / "frontend" / "src" / "teile"
MASK = TEILE / "Skillmaske.svelte"


def _markup() -> str:
    return MASK.read_text(encoding="utf-8").split("<style>", 1)[0]


def _row() -> str:
    markup = _markup()
    return markup.split("{#each zeilen as zeile (zeile.name)}", 1)[1].split("{/each}", 1)[0]


def test_every_row_has_a_pen_and_only_what_is_the_users_has_the_second_sign():
    row = _row()
    # The pen: in every row, with its word as tooltip and label.
    pen = row.split("{#if zeile.eigen}", 1)[0]
    assert '<Hauszeichen zeichen="stift"' in pen
    assert "aria-label={t('skills.bearbeiten')} title={t('skills.bearbeiten')}" in pen
    # The second sign only for a skill the user owns, in one button whose
    # sign, word and colour follow whether a shipped version stands behind it.
    owned = row.split("{#if zeile.eigen}", 1)[1].split("{/if}", 1)[0]
    assert "class:danger={!zeile.mitgeliefert}" in owned
    assert "zeile.mitgeliefert ? 'refresh' : 'trash'" in owned
    word = "t(zeile.mitgeliefert ? 'skills.zuruecksetzen' : 'skills.loeschen')"
    assert f"aria-label={{{word}}}" in owned and f"title={{{word}}}" in owned
    # No word button is left in the row.
    assert 'class="zurueck"' not in row


def test_a_shipped_skill_that_was_not_changed_shows_neither_arrows_nor_bin():
    row = _row()
    # Both are inside the one condition `eigen` (a shipped, unchanged skill
    # is not the user's own), and nothing outside it draws them.
    outside = row.replace(row.split("{#if zeile.eigen}", 1)[1].split("{/if}", 1)[0], "")
    assert "refresh" not in outside and "trash" not in outside


def test_the_red_belongs_to_the_bin_only():
    css = MASK.read_text(encoding="utf-8").split("<style>", 1)[1]
    plain = re.search(r"\n  \.signbutton \{([^}]*)\}", css)
    danger = re.search(r"\n  \.signbutton\.danger \{([^}]*)\}", css)
    assert plain and danger
    assert "--rot" not in plain.group(1)
    assert "color: var(--rot-text)" in danger.group(1)


def test_the_switch_of_the_page_says_load_not_offer():
    for language, name in (("de", "Skills automatisch laden"), ("en", "Load skills automatically")):
        path = ROOT / "app" / "locales" / f"{language}.json"
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        assert catalogue["skills"]["selbst"] == name


def test_the_write_button_uses_the_house_plus_and_the_foot_of_the_form_is_two_signs():
    markup = _markup()
    start = markup.split('<button class="skillneu"', 1)[1].split("</button>", 1)[0]
    assert '<Hauszeichen zeichen="plus"' in start and "<svg" not in markup
    foot = markup.split('<div class="formfuss">', 1)[1].split("</div>", 1)[0]
    for word, sign in (("abbrechen", "kreuz"), ("sichern", "save")):
        assert f"aria-label={{t('app.{word}')}} title={{t('app.{word}')}}" in foot
        assert f'<Hauszeichen zeichen="{sign}"' in foot
    assert "disabled={!neuName.trim() || !neuInhalt.trim()} onclick={neuSpeichern}" in foot


def test_only_the_question_about_deleting_wears_red_and_carries_the_bin():
    mask = MASK.read_text(encoding="utf-8")
    ask = mask.split("const ja = await frage(", 1)[1].split("\n      })", 1)[0]
    assert "okSchluessel: 'skills.loeschen'" in ask and "danger: true" in ask
    # A shipped skill that is only reset asks nothing.
    assert "if (endgueltig) {" in mask
    state = (ROOT / "frontend" / "src" / "lib" / "zustand.svelte.js").read_text(encoding="utf-8")
    assert "danger = false } = {}) {" in state
    assert "zustand.frage = { text, eingabe, okSchluessel, danger, aufloesen }" in state
    question = (TEILE / "Frage.svelte").read_text(encoding="utf-8")
    assert "class:danger={zustand.frage.danger}" in question
    assert '{#if zustand.frage.danger}<Hauszeichen zeichen="trash"' in question
    # The phone's question window shows the same: red, with the bin.
    phone = (ROOT / "frontend" / "src" / "phone" / "Ask.svelte").read_text(encoding="utf-8")
    assert "class:danger={zustand.frage.danger}" in phone
    assert '{#if zustand.frage.danger}<Hauszeichen zeichen="trash"' in phone
