"""The catalogue calls the memory of the machine "memory", not "VRAM".

The head of the catalogue read "VRAM: 32 GB" on a Mac whose memory is shared
between the processor and the graphics chip, so no memory of that name exists
there, and the card line for a model that does not fit read "Recommended VRAM".
Now the head carries the word the local models window already uses ("Memory"
in English, "Speicher" in German) and the card line says "memory" as well. The
limit of the image generator keeps its own name, it is a graphics limit.

The real catalogue, built as it ships, in a real Chrome; the machine is stood
in by the page (32 GB). Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.loading_harness import run_page
from tests.test_speech_server_projector_memory import browser

LOCALES = Path(__file__).resolve().parent.parent / "app" / "locales"

SHELL = "<p></p>"

ENTRY_JS = """import { mount } from 'svelte'
import Katalog from '../src/teile/Katalog.svelte'
import { texte } from '../src/lib/texte.svelte.js'
import { zustand } from '../src/lib/zustand.svelte.js'
import { meldungen } from '../src/lib/meldewesen.svelte.js'
import catalogue from '../../app/locales/__LANGUAGE__.json'
import '../src/stil/global.css'

texte.katalog = catalogue
texte.sprache = '__LANGUAGE__'
window.zustand = zustand
window.meldungen = meldungen
const root = document.getElementById('root')
root.style.cssText = 'height: 1000px; display: flex; flex-direction: column;'
mount(Katalog, { target: root, props: { offen: true } })
"""

CASES = r"""
window.answers = {
  runnerAuskunft: { speicher_gb: 32, modelle: [], mmproj: [], mtp: [] },
  modellHolenStand: null,
}
await until(() => document.querySelector('.kopfecke .maschine'), 'the head with the memory of the machine')
await until(() => document.querySelectorAll('.karte').length > 1, 'the cards')
report.head = document.querySelector('.kopfecke .maschine').textContent.replace(/\s+/g, ' ').trim()
report.cards = document.querySelectorAll('.karte').length
report.page = document.body.textContent
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _run(language: str) -> dict:
    return run_page(SHELL, ENTRY_JS.replace("__LANGUAGE__", language), CASES)


@pytest.fixture(scope="module")
def german() -> dict:
    return _run("de")


@pytest.fixture(scope="module")
def english() -> dict:
    return _run("en")


def _catalogue(language: str) -> dict:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))


@browser
def test_the_head_names_the_memory_in_german(german):
    assert german["errors"] == []
    assert german["head"] in ("Speicher: 32 GB", "Speicher: 32,0 GB")
    assert "VRAM" not in german["page"]


@browser
def test_the_head_names_the_memory_in_english(english):
    assert english["errors"] == []
    assert english["head"] in ("Memory: 32 GB", "Memory: 32.0 GB")
    assert "VRAM" not in english["page"]


@browser
def test_silence_the_cards_stand_as_before(german, english):
    assert german["cards"] > 1 and german["cards"] == english["cards"]


@pytest.mark.parametrize("language", ["de", "en"])
def test_no_text_of_the_catalogue_says_vram(language):
    for key, text in _catalogue(language)["katalog"].items():
        assert "VRAM" not in text, (language, key)
    assert "maschine" not in _catalogue(language)["katalog"]


def test_the_card_line_for_a_model_that_does_not_fit_says_memory():
    assert _catalogue("en")["katalog"]["braucht_maschine"] == "Recommended memory: {gb} GB"
    assert _catalogue("de")["katalog"]["braucht_maschine"] == "Empfohlener Speicher: {gb} GB"


def test_silence_the_image_limit_keeps_its_graphics_name():
    assert "VRAM" in _catalogue("en")["bild"]["vram_limit"]
