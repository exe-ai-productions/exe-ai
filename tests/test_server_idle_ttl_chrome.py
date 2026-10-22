"""The idle time stands under "Advanced" on all six local server pages, in a real
browser.

The real pages (model, agent, embedding, speech, clean-up and picture server)
are built as shipped on the stub of ``tests/image_window_page.py``, widened by
the answers of the five llama servers. Each page shows the field "Idle TTL"
(German "Leerlaufzeit") in minutes inside its card "Advanced", empty at the
start; a number typed into it is kept, and the page opened again shows it.
Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from tests import image_window_page as harness
from tests.image_window_page import needs_browser, run_cases
from tests.test_image_server_layout_chrome import ROUTES as BILD_ROUTES

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

ROOT = Path(__file__).resolve().parent.parent
GERMAN = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))
ENGLISH = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))

SHELL_IMPORTS = """  import Modellserver from '../../src/teile/Modellserver.svelte'
  import Agentserver from '../../src/teile/Agentserver.svelte'
  import Einbettungsserver from '../../src/teile/Einbettungsserver.svelte'
  import Sprachserver from '../../src/teile/Sprachserver.svelte'
  import Bereinigungsserver from '../../src/teile/Bereinigungsserver.svelte'
  import Bildserver from '../../src/teile/Bildserver.svelte'
"""

SHELL_SCENES = """  {#if scene.show === 'modell'}<Modellserver />{/if}
  {#if scene.show === 'agent'}<Agentserver />{/if}
  {#if scene.show === 'einbettung'}<Einbettungsserver />{/if}
  {#if scene.show === 'sprache'}<Sprachserver />{/if}
  {#if scene.show === 'bereinigung'}<Bereinigungsserver />{/if}
  {#if scene.show === 'bild'}<Bildserver />{/if}
"""

ENTRY_IMPORTS = """import { texte } from '../../src/lib/texte.svelte.js'
import german from '../../../app/locales/de.json'
import english from '../../../app/locales/en.json'
texte.katalog = german
texte.sprache = 'de'
window.texte = texte
window.german = german
window.english = english
"""

# The five llama servers answer alike: a folder with one file, nothing running,
# and the stored values of the setting each of them keeps.
LLAMA_ROUTES = r"""  const llama = (extra = {}) => ({
    programm: '/bin/llama-server', version: 'b1', updatable: false, restorable: false,
    ordner: '/m', modelle: [{ name: 'a.gguf', groesse_gb: 2 }], mmproj: [], projector_size_gb: {}, mtp: [],
    speicher_gb: 32, kerne: 8, belegt_gb: null, laeuft: false, modell: null, kontext: null, schichten: null,
    port: 8083, drafter: null, vision: null, fein: null, flash_aktiv: null, mtp_aktiv: null,
    unknown_architecture: null, zuordnung: {}, vorgaben: { kontext: 16384, schichten: 99, port: null, vorladen: true },
    vorgabe: 'a.gguf', diktat_vorgaben: {}, projektoren: {}, threads: null, stimmproben: [], stimmproben_dauer: {},
    ...extra,
  })
  if (path === '/runner') return answer(llama({ port: 8080 }))
  if (path === '/agentenmodell') return answer(llama())
  if (path === '/einbettungsserver') {
    const stored = backend.settings.embedding || {}
    return answer(llama({
      selected_model: 'a.gguf', context: 2048, batch: 2048, pooling: '', layers: null, threads: 0, mlock: false,
      parallel: null, idle_minutes: stored.idle_minutes ?? null,
    }))
  }
  if (path === '/sprachserver') return answer(llama({ selected_model: 'a.gguf', port: 8084 }))
  if (path === '/bereinigungsserver') return answer(llama({ selected_model: 'a.gguf', port: 8085 }))
  if (path.endsWith('/log')) return answer([])
"""

CASES = r"""
backend.settings.diktat = backend.settings.diktat || {}
backend.settings.embedding = backend.settings.embedding || {}
backend.settings.runnermodell = backend.settings.runnermodell || {}
backend.settings.feineinstellungen = backend.settings.feineinstellungen || {}
backend.settings.agentenmodell = backend.settings.agentenmodell || { sorte: 'slot', wert: 'a.gguf' }
backend.files = [{ name: 'a.safetensors', size: 6.9e9, collecting_imatrix: false, has_imatrix: false, gguf_type: null, convert_types: [] }]

const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const idField = () => document.querySelector('input[id$="-idle"]')
const card = () => idField() ? idField().closest('section.abschnitt') : null
const look = () => {
  const input = idField()
  if (!input) return { found: false }
  const section = card()
  const row = input.closest('.zeile')
  return {
    found: true, value: input.value, word: row.querySelector('.nullwort')?.textContent ?? null,
    label: text(row.querySelector('label')), card: section ? text(section.querySelector('.kopf')) : null,
    disabled: input.disabled,
  }
}
const open = async (name) => {
  await show(name)
  for (let k = 0; k < 60 && !idField(); k += 1) await wait(100)
  await wait(500)
}
const typeNumber = async (value) => {
  const input = idField()
  typeInto(input, String(value))
  input.dispatchEvent(new Event('change', { bubbles: true }))
  await wait(1500)
}

report.pages = {}
for (const name of ['modell', 'agent', 'einbettung', 'sprache', 'bereinigung', 'bild']) {
  const entry = {}
  await open(name)
  entry.german = look()
  window.texte.katalog = window.english
  window.texte.sprache = 'en'
  await wait(300)
  entry.english = look()
  window.texte.katalog = window.german
  window.texte.sprache = 'de'
  await wait(300)
  if (entry.german.found) {
    await typeNumber(15)
    entry.typed = look()
    await show('')
    await wait(300)
    await open(name)
    entry.reopened = look()
  }
  await show('')
  await wait(300)
  report.pages[name] = entry
}
report.written = {
  modell: backend.settings.feineinstellungen, agent: backend.settings.agentenmodell,
  einbettung: backend.settings.embedding, diktat: backend.settings.diktat, bild: backend.settings.bildgeraete,
}
"""


@pytest.fixture(scope="module")
def report() -> dict:
    shell = harness.SHELL.replace(
        "  import { scene } from './scene.svelte.js'\n", SHELL_IMPORTS + "  import { scene } from './scene.svelte.js'\n"
    ).replace("  {#if scene.show === 'values'}", SHELL_SCENES + "  {#if scene.show === 'values'}").replace(
        "width: 760px", "width: 1180px"
    )
    entry = harness.ENTRY_JS.replace(
        "import '../../src/stil/global.css'\n", "import '../../src/stil/global.css'\n" + ENTRY_IMPORTS
    ).replace(
        "  if (path === '/bild/devices') return answer([])\n",
        LLAMA_ROUTES + BILD_ROUTES + "  if (path === '/bild/devices') return answer([])\n",
    )
    entry = entry.replace("  calls: [],\n  delay: 0,\n}", "  calls: [],\n  delay: 0,\n  files: [],\n  update: false,\n}")
    page = harness.PAGE.replace(
        '<script src="out/entry.js"></script>',
        '<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">\n<script src="out/entry.js"></script>',
    )
    with (
        mock.patch.object(harness, "SHELL", shell),
        mock.patch.object(harness, "ENTRY_JS", entry),
        mock.patch.object(harness, "PAGE", page),
    ):
        return run_cases(CASES, limit=280.0, window="1500,3000")


PAGES = ["modell", "agent", "einbettung", "sprache", "bereinigung", "bild"]
LABEL_DE = GERMAN["modell"]["feld_idle_ttl"]
LABEL_EN = ENGLISH["modell"]["feld_idle_ttl"]
ADVANCED_DE = GERMAN["modell"]["gruppe_erweitert"]
ADVANCED_EN = ENGLISH["modell"]["gruppe_erweitert"]


def test_the_catalogues_name_the_field_in_both_languages():
    assert (LABEL_DE, LABEL_EN) == ("Leerlaufzeit", "Idle TTL")


@pytest.mark.parametrize("page", PAGES)
def test_every_page_shows_the_field_under_advanced_empty_at_the_start(report, page):
    german = report["pages"][page]["german"]
    assert german["found"] is True, (page, german)
    assert german["label"] == LABEL_DE and german["card"] == ADVANCED_DE, german
    assert german["value"] == "" and german["word"] == "-", german
    assert german["disabled"] is False, german


@pytest.mark.parametrize("page", PAGES)
def test_the_field_is_called_idle_ttl_in_english(report, page):
    english = report["pages"][page]["english"]
    assert english["label"] == LABEL_EN and english["card"] == ADVANCED_EN, (page, english)


@pytest.mark.parametrize("page", PAGES)
def test_a_typed_number_stays_and_the_page_opened_again_shows_it(report, page):
    entry = report["pages"][page]
    assert entry["typed"]["value"] == "15", entry
    assert entry["reopened"]["value"] == "15", entry
    assert entry["reopened"]["word"] is None, entry


def test_each_number_went_to_the_setting_that_page_keeps(report):
    written = report["written"]
    assert written["modell"].get("idle_minutes") == 15, written
    assert written["agent"].get("fein", {}).get("idle_minutes") == 15, written
    assert written["einbettung"].get("idle_minutes") == 15, written
    assert written["diktat"].get("speech_idle_minutes") == 15, written
    assert written["diktat"].get("cleanup_idle_minutes") == 15, written
    assert written["bild"].get("idle_minutes") == 15, written
