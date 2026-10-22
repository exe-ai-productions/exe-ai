"""Settings: the rows of the menu say their values as numbers, "active" and
"inactive" — one scheme everywhere, counts as `active/all`.

The sounds row says "sounds active" or "sounds inactive", the skills row the
skills offered by themselves of all there are, the servers and tools rows
the active of all, the agents row only its number, and the cronjobs row
stays as it was. The sentences the rows used to say are gone from both
catalogues. Read off the source, the way the other window tests do.
"""

from __future__ import annotations

import json
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
SEITE = (WURZEL / "frontend/src/teile/SystemPrompt.svelte").read_text(encoding="utf-8")
LOCALES = WURZEL / "app" / "locales"


def _katalog(sprache: str) -> dict:
    return json.loads((LOCALES / f"{sprache}.json").read_text(encoding="utf-8"))


def test_the_sounds_row_says_active_and_inactive():
    assert _katalog("en")["einstellungen"]["toene_an"] == "sounds active"
    assert _katalog("en")["einstellungen"]["toene_aus"] == "sounds inactive"
    assert _katalog("de")["einstellungen"]["toene_an"] == "Töne aktiv"
    assert _katalog("de")["einstellungen"]["toene_aus"] == "Töne inaktiv"


def test_the_three_sentences_of_the_rows_are_gone_and_unread():
    for sprache in ("en", "de"):
        editor = _katalog(sprache)["editor"]
        for schluessel in ("unter_agenten", "unter_skills", "unter_server"):
            assert schluessel not in editor, (sprache, schluessel)
    for schluessel in ("editor.unter_agenten", "editor.unter_skills", "editor.unter_server"):
        assert schluessel not in SEITE


def test_the_rows_carry_their_numbers_and_the_header_of_the_tools_page_keeps_its_sentence():
    figures = (WURZEL / "frontend/src/lib/settingsState.svelte.js").read_text(encoding="utf-8")
    zeile = figures.split("export function rowValue", 1)[1].split("export function rowDot", 1)[0]
    assert "`${settingsState.skillsAuto ? settingsState.skillsAngeboten : 0}/${settingsState.skills}`" in zeile
    assert "`${serverStand().aktiv}/${serverStand().alle}`" in zeile
    assert "`${anzahlAn()}/${anzahlAlle()}`" in zeile
    assert "t('agenten.created_count', { n: settingsState.agents })" in zeile
    # The cronjobs row was already this form; the page head keeps its sentence.
    assert "`${settingsState.cronjobsAktiv}/${settingsState.cronjobs}`" in zeile
    assert _katalog("de")["werkzeuge"]["aktiv_zahl"] == "{zahl} aktiv, aus {quellen} Quellen"
