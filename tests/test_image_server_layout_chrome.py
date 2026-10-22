"""The picture server page in the order it is drawn in, and the values of a
model with a save button, in a real browser.

On top stands a row of two columns: the model card with the prompt
preparation under it on the left, memory and devices on the right; under it
the values of one model with a choice of the folder's models at the head's
left end, then the conversion to GGUF, the folding list of the model files,
the generator (sd.cpp) and the log at the foot. The values block carries the
choice in its head and, at the head's right end, the two signs reset and save
(34 px). A change is written when save is pressed and not a moment after;
switching the model over a change not saved asks first; reset writes at once.
The names of the rows stand 13 px semi-bold, the version line of sd.cpp
semi-bold with and without the update button.

The real page is built as shipped on the stub of ``tests/image_window_page.py``,
which this file widens by the routes of the model files and the generator
(nothing in the shared file changes but the size of the window). Skipped where
there is no Chrome or no node.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from tests import image_window_page as harness
from tests.image_window_page import needs_browser, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

ROOT = Path(__file__).resolve().parent.parent
GERMAN = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))

SHELL_IMPORTS = """  import Bildserver from '../../src/teile/Bildserver.svelte'
"""

SHELL_SCENES = """  {#if scene.show === 'page'}<Bildserver />{/if}
"""

ENTRY_IMPORTS = """import { texte } from '../../src/lib/texte.svelte.js'
import { zustand, frageBeantworten } from '../../src/lib/zustand.svelte.js'
import german from '../../../app/locales/de.json'
texte.katalog = german
texte.sprache = 'de'
window.zustand = zustand
window.frageBeantworten = frageBeantworten
"""

ROUTES = """  if (path === '/bild/model-files') return answer(structuredClone(backend.files))
  if (path === '/bild/modelle') {
    return answer({
      modelle: backend.files.map((file) => file.name),
      families: { 'a.safetensors': 'sdxl', 'b.safetensors': 'sdxl' },
      programm_da: true, bau: 'master-4ff2c8a', standardmodell: '', sizes: {}, restorable: false,
    })
  }
  if (path === '/bild/programm/varianten') return answer({ varianten: [], installiert: null, unavailable: [] })
  if (path === '/bild/programm/aktualisierung') return answer({ verfuegbar: backend.update === true, aktuell: backend.update !== true })
  if (path === '/bild/server/log') return answer([])
  if (path === '/bild/turbo') return answer({ zustand: 'aus', programm_da: true })
"""

CASES = r"""
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const rect = (node) => { const r = node.getBoundingClientRect(); return { w: r.width, h: r.height, top: r.top, left: r.left, right: r.right, bottom: r.bottom } }
const cards = () => [...document.querySelectorAll('section.abschnitt, section.block')]
// The values block names its model in the choice at its head's left end.
const headOf = (card) => (card.matches('.block') ? text(card.querySelector('.kopf .feld .text')) : text(card.querySelector('.kopf')))
const card = (head) => cards().find((c) => headOf(c) === head)
const file = (name, size) => ({ name, size, collecting_imatrix: false, has_imatrix: false, gguf_type: null, convert_types: [] })
const keptValues = () => backend.calls.filter((c) => c.key === 'bildmodellwerte').map((c) => c.sent)
const asked = () => (window.zustand.frage ? window.zustand.frage.text : null)
// A question that was never asked cannot be answered: the run goes on, and the test of it fails.
const answer = (yes) => { if (window.zustand.frage) window.frageBeantworten(yes) }
backend.files = [file('a.safetensors', 6.9e9), file('b.safetensors', 7.2e9)]

// --- The order of the page ---
await show('page')
await wait(1800)
report.order = cards().map((c) => ({ head: headOf(c), ...rect(c) }))
report.log = rect(document.querySelector('.log'))

// --- The values: at the top from the start ---
const block = () => document.querySelector('section.block')
const values = () => block()
const signs = () => (values() ? [...values().querySelectorAll('.kopf .signs button')] : [])
const choose = async (name) => {
  block().querySelector('.kopf button[role="combobox"]').click()
  await wait(300)
  const option = [...document.querySelectorAll('[role="option"]')].find((o) => text(o).endsWith(name))
  option.click()
  await wait(300)
}
report.opened = {
  shown: headOf(block()),
  head: rect(values().querySelector('.kopf')),
  signs: signs().map((b) => ({ label: b.getAttribute('aria-label'), title: b.getAttribute('title'), disabled: b.disabled, ...rect(b) })),
  oldWordButton: Array.from(values().querySelectorAll('button')).some((b) => text(b) === 'Zurücksetzen'),
}
const named = (label) => Array.from(values().querySelectorAll('.zeile .name, .zeile .regelname')).find((n) => text(n) === label)
const look = (node) => { const s = getComputedStyle(node); return { size: s.fontSize, weight: s.fontWeight } }
report.names = { width: look(named('Breite')), sampler: look(named('Sampler')) }
report.clippedLabels = Array.from(values().querySelectorAll('.zeile .name, .zeile .regelname'))
  .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => text(node))
report.labelCount = values().querySelectorAll('.zeile .name, .zeile .regelname').length
// With the family not read every part of the kit can be given: all their names.
const readSwitch = () => values().querySelector('button[role="switch"]')
readSwitch().click()
await wait(400)
// The kit is folded under the model card until its head is pressed.
values().querySelector('.kitkopf').click()
await wait(300)
report.freeLabels = {
  count: values().querySelectorAll('.zeile .name, .zeile .regelname').length,
  clipped: Array.from(values().querySelectorAll('.zeile .name, .zeile .regelname')).filter((node) => node.scrollWidth > node.clientWidth + 1)
    .map((node) => ({ text: text(node), title: node.getAttribute('title') })),
}
readSwitch().click()
await wait(300)
report.fieldWeights = {
  number: look(values().querySelector('.zahlplatz input')),
  select: look(values().querySelector('.karte button[role="combobox"]')),
}

// --- Nothing is written by itself ---
const trigger = () => document.querySelector('input[id^="bmw-trigger-"]') || { value: null }
const typeTrigger = (value) => { const node = document.querySelector('input[id^="bmw-trigger-"]'); if (node) typeInto(node, value) }
typeTrigger('lighthouse')
await wait(1200)
report.typed = { written: keptValues().length, saveDisabled: signs()[1]?.disabled }
signs()[1]?.click()
await wait(700)
report.saved = { written: keptValues(), saveDisabled: signs()[1]?.disabled, kept: trigger().value }

// --- Switching over a change not saved asks first ---
await choose('b.safetensors')
report.cleanSwitch = { asked: asked(), shown: headOf(block()) }
await choose('a.safetensors')
typeTrigger('unsaved')
await wait(200)
await choose('b.safetensors')
report.askSwitch = { text: asked() }
answer(false)
await wait(400)
report.stayed = { shown: headOf(block()), value: trigger().value, written: keptValues().length }

// --- A yes switches and leaves nothing of the change in the other model ---
// The other model's values arrive late: what stands meanwhile is the point.
const realFetch = window.fetch
window.fetch = (address, options) => (String(address).includes('vorgaben') && String(address).includes('b.safetensors')
  ? new Promise((done) => setTimeout(done, 700)).then(() => realFetch(address, options))
  : realFetch(address, options))
await choose('b.safetensors')
answer(true)
await wait(150)
report.switchedMeanwhile = {
  shown: headOf(block()),
  trigger: trigger().value,
  saveDisabled: signs()[1].disabled,
}
await wait(1100)
window.fetch = realFetch
report.switched = {
  shown: headOf(block()), trigger: trigger().value, saveDisabled: signs()[1].disabled, written: keptValues().length,
}
await choose('a.safetensors')

// --- While a save runs, reset cannot be pressed (and the other way round) ---
backend.delay = 600
typeTrigger('during the save')
await wait(100)
signs()[1]?.click()
await wait(150)
report.lock = { reset: signs()[0]?.disabled, save: signs()[1]?.disabled }
await wait(900)
backend.delay = 0
report.afterLock = { reset: signs()[0]?.disabled, save: signs()[1]?.disabled }

// --- Reset writes at once ---
const before = keptValues().length
signs()[0]?.click()
await wait(700)
report.reset = { written: keptValues().slice(before) }

// --- The version line of sd.cpp ---
const sd = () => card('sd.cpp')
const version = () => Array.from(sd().querySelectorAll('.zeile .name')).find((n) => text(n) === 'Version')
const mark = () => sd().querySelector('.versionsmarke')
const sign = () => sd().querySelector('.updatezeichen')
report.version = { without: { text: text(version()), mark: text(mark()), found: sign().classList.contains('gefunden'), ...look(version()) } }
backend.update = true
sign().click()
await wait(900)
report.version.withButton = { signs: sd().querySelectorAll('.updatezeichen').length, found: sign().classList.contains('gefunden'), ...look(version()) }
"""


@pytest.fixture(scope="module")
def report() -> dict:
    for anchor in (
        "import '../../src/stil/global.css'\n",
        "  if (path === '/bild/devices') return answer([])\n",
    ):
        assert anchor in harness.ENTRY_JS, f"the shared harness changed, widen it again: {anchor!r}"
    for anchor in (
        "  import { scene } from './scene.svelte.js'\n",
        "  {#if scene.show === 'values'}",
        "width: 760px",
    ):
        assert anchor in harness.SHELL, f"the shared harness changed, widen it again: {anchor!r}"
    shell = (
        harness.SHELL.replace(
            "  import { scene } from './scene.svelte.js'\n", SHELL_IMPORTS + "  import { scene } from './scene.svelte.js'\n"
        )
        .replace("  {#if scene.show === 'values'}", SHELL_SCENES + "  {#if scene.show === 'values'}")
        .replace("width: 760px", "width: 1180px")
    )
    entry = harness.ENTRY_JS.replace(
        "import '../../src/stil/global.css'\n", "import '../../src/stil/global.css'\n" + ENTRY_IMPORTS
    ).replace(
        "  if (path === '/bild/devices') return answer([])\n", ROUTES + "  if (path === '/bild/devices') return answer([])\n"
    )
    entry = entry.replace("  calls: [],\n  delay: 0,\n}", "  calls: [],\n  delay: 0,\n  files: [],\n  update: false,\n}")
    assert "update: false" in entry and "texte.katalog = german" in entry
    # The house's own stylesheet (fonts and colours), which the shared page does not load.
    assert '<script src="out/entry.js"></script>' in harness.PAGE
    page = harness.PAGE.replace(
        '<script src="out/entry.js"></script>',
        '<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">\n<script src="out/entry.js"></script>',
    )
    with (
        mock.patch.object(harness, "SHELL", shell),
        mock.patch.object(harness, "ENTRY_JS", entry),
        mock.patch.object(harness, "PAGE", page),
    ):
        return run_cases(CASES, limit=240.0, window="1500,3000")


HEAD_MODEL = GERMAN["bildserver"]["modell"]
HEAD_PREPARATION = GERMAN["bildserver"]["aufbereitung"]
HEAD_DEVICES = GERMAN["bild"]["gruppe_speicher"]
HEAD_CONVERT = GERMAN["bildserver"]["gguf_konvertierung"]
HEAD_TABLE = GERMAN["bildserver"]["bildmodelle_im_ordner"]
ASK = GERMAN["agenten"]["verwerfen_frage"]


def _by_head(cards: list[dict], head: str) -> dict:
    found = [card for card in cards if card["head"].startswith(head)]
    assert found, (head, [card["head"] for card in cards])
    return found[0]


# --- The order of the page ---


def test_a_row_of_two_columns_stands_on_top(report):
    cards = report["order"]
    model, preparation, devices = (_by_head(cards, h) for h in (HEAD_MODEL, HEAD_PREPARATION, HEAD_DEVICES))
    # Model and preparation on the left, one under the other; the devices at the right, level with the model.
    assert abs(model["left"] - preparation["left"]) <= 1
    assert preparation["top"] >= model["bottom"] - 1
    assert devices["left"] >= model["right"] + 10, (model, devices)
    assert abs(devices["top"] - model["top"]) <= 2
    # The cards beside each other end on one line.
    assert abs(devices["bottom"] - preparation["bottom"]) <= 2, (devices, preparation)


def test_the_values_the_conversion_the_table_the_generator_and_the_log_follow_in_that_order(report):
    cards = report["order"]
    model, preparation, devices = (_by_head(cards, h) for h in (HEAD_MODEL, HEAD_PREPARATION, HEAD_DEVICES))
    values, convert, table, generator = (_by_head(cards, h) for h in ("a.safetensors", HEAD_CONVERT, HEAD_TABLE, "sd.cpp"))
    row_bottom = max(preparation["bottom"], devices["bottom"])
    assert values["top"] >= row_bottom - 1
    assert convert["top"] >= values["bottom"] - 1
    assert table["top"] >= convert["bottom"] - 1
    assert generator["top"] >= table["bottom"] - 1
    assert report["log"]["top"] >= generator["bottom"] - 1
    # The model card has the row's first place: nothing stands above it.
    assert min(card["top"] for card in cards) == model["top"]


# --- The head of the values ---


def test_the_values_head_carries_the_two_signs_of_34_at_its_right_end(report):
    opened = report["opened"]
    assert [sign["label"] for sign in opened["signs"]] == [GERMAN["sprachserver"]["zuruecksetzen"], GERMAN["app"]["sichern"]]
    assert [sign["title"] for sign in opened["signs"]] == [GERMAN["sprachserver"]["zuruecksetzen"], GERMAN["app"]["sichern"]]
    for sign in opened["signs"]:
        assert abs(sign["w"] - 34) <= 0.5 and abs(sign["h"] - 34) <= 0.5, sign
    head = opened["head"]
    assert abs(opened["signs"][1]["right"] - head["right"]) <= 1, (opened["signs"], head)
    assert opened["signs"][0]["right"] <= opened["signs"][1]["left"] + 0.5
    assert opened["oldWordButton"] is False


def test_the_names_of_the_values_stand_13_semi_bold_and_the_fields_regular(report):
    for name in report["names"].values():
        assert name == {"size": "13px", "weight": "600"}, name
    for field in report["fieldWeights"].values():
        assert field["weight"] == "400", field


def test_the_head_with_the_model_s_name_stands_while_the_other_model_is_read(report):
    # The choice names the new model at once; the values wait for the answer.
    assert report["switchedMeanwhile"]["shown"] == "b.safetensors"


def test_no_name_of_the_values_is_cut_off_by_the_heavier_weight(report):
    assert report["labelCount"] >= 8, report["labelCount"]
    assert report["clippedLabels"] == [], report["clippedLabels"]


def test_a_name_of_the_kit_parts_that_is_too_long_for_its_column_carries_its_whole_word_as_title(report):
    free = report["freeLabels"]
    assert free["count"] > report["labelCount"], free
    for name in free["clipped"]:
        assert name["title"] == name["text"], name


# --- Saving ---


def test_a_change_is_not_written_by_itself(report):
    assert report["typed"] == {"written": 0, "saveDisabled": False}


def test_save_is_not_pressable_without_a_change(report):
    assert report["opened"]["signs"][1]["disabled"] is True
    assert report["saved"]["saveDisabled"] is True


def test_the_save_sign_writes_the_changed_fields_only(report):
    assert report["saved"]["written"] == [{"a.safetensors": {"trigger": "lighthouse"}}]
    assert report["saved"]["kept"] == "lighthouse"


# --- The question before a change not saved is thrown away ---


def test_the_default_model_is_the_first_file_where_none_is_chosen(report):
    assert report["opened"]["shown"] == "a.safetensors"


def test_switching_without_a_change_asks_nothing(report):
    assert report["cleanSwitch"] == {"asked": None, "shown": "b.safetensors"}


def test_switching_over_a_change_not_saved_asks_and_a_no_keeps_the_model_and_the_change(report):
    assert report["askSwitch"]["text"] == ASK
    assert report["stayed"] == {"shown": "a.safetensors", "value": "unsaved", "written": 1}


def test_a_yes_switches_the_model_and_leaves_nothing_of_the_change_in_the_other(report):
    switched = report["switched"]
    assert switched == {"shown": "b.safetensors", "trigger": "", "saveDisabled": True, "written": 1}, switched


def test_while_the_other_model_is_read_nothing_of_the_first_one_stands_in_its_block(report):
    # The save sign of the new block cannot be pressed, and the old field is gone.
    assert report["switchedMeanwhile"] == {"shown": "b.safetensors", "trigger": None, "saveDisabled": True}


def test_while_a_save_runs_neither_sign_can_be_pressed_and_both_come_back_after(report):
    assert report["lock"] == {"reset": True, "save": True}
    assert report["afterLock"] == {"reset": False, "save": True}


def test_reset_writes_the_start_values_at_once(report):
    assert report["reset"]["written"] == [{"a.safetensors": None}]


# --- The version line of the generator ---


def test_the_version_line_of_the_generator_stands_semi_bold_with_and_without_the_update_sign(report):
    version = report["version"]
    assert version["without"]["text"] == "Version"
    assert version["without"]["mark"] == "master-4ff2c8a"
    assert version["without"]["weight"] == "600" and version["without"]["size"] == "13px"
    assert version["without"]["found"] is False
    # The first press only asks: the sign turns yellow, and there is still one.
    assert version["withButton"]["signs"] == 1
    assert version["withButton"]["found"] is True
    assert version["withButton"]["weight"] == "600"
