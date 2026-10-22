"""The memory page of the settings: the names of its two switches, the save
that keeps the page open, the switch that springs back on a failure, and the
phone's foot that stands as two signs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
PAGE = SRC / "teile" / "SystemPrompt.svelte"
PHONE = SRC / "phone" / "settings" / "TextFile.svelte"


def _catalogue(language: str) -> dict[str, dict[str, str]]:
    path = ROOT / "app" / "locales" / f"{language}.json"
    data: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_the_two_switches_carry_their_new_names_under_the_old_keys():
    german = _catalogue("de")["gedaechtnis"]
    english = _catalogue("en")["gedaechtnis"]
    assert german["an_lokal"] == "Exe-AI-Gedächtnis"
    assert german["an_cloud"] == "An Cloud-Modelle und eigene Server schicken"
    assert english["an_lokal"] == "Exe AI Memory"
    assert english["an_cloud"] == "Send to cloud models and custom servers"
    # The keys are what the page reads; the third switch is untouched.
    page = PAGE.read_text(encoding="utf-8")
    for key in ("gedaechtnis.an_lokal", "gedaechtnis.an_cloud", "bildschutz.titel"):
        assert f"t('{key}')" in page, key


def test_saving_the_memory_keeps_the_page_open_and_saving_the_prompt_closes_it():
    source = PAGE.read_text(encoding="utf-8")
    body = source.split("async function sichern() {", 1)[1].split("\n  }\n", 1)[0]
    prompt = body.split("if (istSystem) {", 1)[1].split("} else if (istGedaechtnis)", 1)[0]
    memory = body.split("} else if (istGedaechtnis) {", 1)[1].split("} else if (istDatei)", 1)[0]
    assert "seitenSchliessen()" in prompt
    assert "seitenSchliessen()" not in memory
    assert "gedaechtnis.gesichert" in memory and "gedaechtnis.geleert" in memory


def test_a_switch_that_fails_to_save_springs_back_and_says_so():
    values = (SRC / "lib" / "settingsvalues.svelte.js").read_text(encoding="utf-8")
    body = values.split("async function gedaechtnisSchalten(seite, an) {", 1)[1].split("\n  }\n", 1)[0]
    assert "const vorher = gedaechtnisSchalter" in body
    assert re.search(r"catch \{\s*gedaechtnisSchalter = vorher\s*melde\(t\('fehler\.allgemein'\), 'fehler'\)", body)


def test_the_phone_foot_stands_as_two_signs_with_their_word_as_label():
    source = PHONE.read_text(encoding="utf-8")
    foot = source.split('<div class="signs">', 1)[1].split("</div>", 1)[0]
    for word, sign in (("abbrechen", "kreuz"), ("sichern", "save")):
        assert f"aria-label={{t('app.{word}')}} title={{t('app.{word}')}}" in foot
        assert f'<Hauszeichen zeichen="{sign}"' in foot
    # Each sign keeps its own handler and its own disabled condition.
    cancel, save = foot.split("</button>")[:2]
    assert "onclick={() => (text = loaded)} disabled={!dirty}" in cancel
    assert "onclick={save} disabled={!dirty || failed}" in save
    # Cancel and Save are no word buttons any more; the page's clearing stays one.
    assert "<Action label={t('app.abbrechen')}" not in source
    assert "<Action label={t('app.sichern')}" not in source
    assert "<Action label={t('app.leeren')}" in source
