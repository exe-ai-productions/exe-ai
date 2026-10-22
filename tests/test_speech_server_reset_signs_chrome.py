"""Setting an instruction back on the speech server's page, in a real browser.

The real page is built as shipped on the stub of ``tests/model_windows_page.py``
with the speech server's answers added. In its three instruction rows
(dictation, clean-up, conversation) the way back to the works text is a sign
button, the double arrow, not the word:

* no button of the three rows carries the text "Reset" any more; each carries
  the sign, the word as its tooltip and the group and the field as the name
  read out;
* the button is 30 × 30, stands in the line of the row's name at the right end
  of the row, the field under both;
* a click after a change puts the works text of that very instruction back;
* silence: the buttons of the voice sample stay 34 × 34, and the row of the
  picture server's preparation stands as it did.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

from unittest import mock

import pytest

from tests import model_windows_page as harness
from tests.model_windows_page import BROWSER_TESTS_POSSIBLE, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        not BROWSER_TESTS_POSSIBLE, reason="no node or no frontend dependencies on this machine"
    ),
]

SHELL_IMPORTS = (
    "  import Sprachserver from '../../src/teile/Sprachserver.svelte'\n"
    "  import Promptaufbereitung from '../../src/teile/Promptaufbereitung.svelte'\n"
)
SHELL_SCENES = (
    "  {#if scene.show === 'sprache'}<Sprachserver />{/if}\n"
    "  {#if scene.show === 'aufbereitung'}<Promptaufbereitung />{/if}\n"
)

STUB_METHODS = """methods.spracheAuskunft = async () => ({
  ...program, programm: '/bin/whisper-server', ordner: '/m',
  modelle: [{ name: 'speech.bin', groesse_gb: 1.5 }], mmproj: [], projektoren: [], mtp: [],
  laeuft: false, modell: null, port: 8794, kerne: 8, speicher_gb: 32,
  stimmproben: [{ name: 'sample.wav', dauer: 4 }], stimmproben_dauer: 4,
  diktat_vorgaben: {
    sprache: 'auto', bereinigung: 'aus', anweisung: 'WORKS DICTATION',
    bereinigung_anweisung: 'WORKS CLEANUP', gespraechsanweisung: 'WORKS CONVERSATION',
    automatik: false, vorlesen: true, keep_model_in_memory: false,
  },
  vorgaben: { kontext: 4096, schichten: 99, port: 8794, vorladen: true },
})
methods.spracheProtokoll = async () => []
"""

CASES = r"""
texte.katalog = germanTexts
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const box = (node) => {
  const r = node.getBoundingClientRect()
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }
}
const cards = () => [...document.querySelectorAll('section.abschnitt')]
const headOf = (card) => { const head = card.querySelector(':scope > .kopf'); return head ? text(head) : '' }
const cardByHead = (name) => cards().find((card) => headOf(card) === name)
const typeInto = async (area, value) => {
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
  area.focus()
  set.call(area, value)
  area.dispatchEvent(new Event('input', { bubbles: true }))
  await wait(150)
}
const report = {}
scene.show = 'sprache'
for (let k = 0; k < 100 && !(cardByHead('Diktat') && cardByHead('Bereinigung') && cardByHead('Gespräch')); k += 1) await wait(100)
await wait(800)

report.heads = cards().map(headOf)
report.groups = {}
for (const group of ['Diktat', 'Bereinigung', 'Gespräch']) {
  const card = cardByHead(group)
  const row = card.querySelector('.zeile.stapel')
  const top = row.querySelector('.obenzeile')
  const button = top?.querySelector('button')
  const field = row.querySelector('textarea')
  report.groups[group] = {
    wordButtons: [...card.querySelectorAll('button')].filter((b) => text(b) === 'Zurücksetzen').length,
    hasTop: Boolean(top),
    title: button?.getAttribute('title') ?? null,
    label: button?.getAttribute('aria-label') ?? null,
    sign: Boolean(button?.querySelector('svg')),
    buttonText: button ? text(button) : null,
    button: button ? box(button) : null,
    name: top ? box(top.querySelector('.name')) : null,
    row: box(row),
    field: field ? box(field) : null,
    rowPadding: parseFloat(getComputedStyle(row).paddingRight),
  }
  if (button && field) {
    await typeInto(field, 'changed text')
    report.groups[group].changed = field.value
    button.click()
    await wait(200)
    report.groups[group].afterClick = field.value
  }
}
const probeButtons = [...document.querySelectorAll('.zeichenknopf')].map((b) => ({ w: Math.round(b.getBoundingClientRect().width), h: Math.round(b.getBoundingClientRect().height) }))
report.probe = probeButtons

scene.show = null
await wait(300)
scene.show = 'aufbereitung'
await wait(1000)
const prep = document.querySelector('.zeile.stapel')
const prepButton = prep?.querySelector('.obenzeile button')
report.preparation = prepButton ? {
  w: Math.round(prepButton.getBoundingClientRect().width), h: Math.round(prepButton.getBoundingClientRect().height),
  title: prepButton.getAttribute('title'), label: prepButton.getAttribute('aria-label'),
  sign: Boolean(prepButton.querySelector('svg')),
  top: box(prep.querySelector('.obenzeile')), field: prep.querySelector('textarea') ? box(prep.querySelector('textarea')) : null,
} : null
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    for anchor in ("  import { scene } from './scene.svelte.js'\n", "  {#if scene.show === 'modell'}"):
        assert anchor in harness.SHELL, f"the shared harness changed, widen it again: {anchor!r}"
    assert "export const setSessionKey = () => {}\n" in harness.API_STUB
    shell = harness.SHELL.replace(
        "  import { scene } from './scene.svelte.js'\n", SHELL_IMPORTS + "  import { scene } from './scene.svelte.js'\n"
    ).replace("  {#if scene.show === 'modell'}", SHELL_SCENES + "  {#if scene.show === 'modell'}")
    stub = harness.API_STUB.replace(
        "export const setSessionKey = () => {}\n", STUB_METHODS + "export const setSessionKey = () => {}\n"
    )
    with mock.patch.object(harness, "SHELL", shell), mock.patch.object(harness, "API_STUB", stub):
        return run_cases(CASES)


GROUPS = {
    "Diktat": ("Zurücksetzen Diktat Anweisung", "WORKS DICTATION"),
    "Bereinigung": ("Zurücksetzen Bereinigung Anweisung", "WORKS CLEANUP"),
    "Gespräch": ("Zurücksetzen Gespräch Anweisung", "WORKS CONVERSATION"),
}


def test_the_three_instruction_rows_carry_no_button_with_the_word(report):
    assert {"Diktat", "Bereinigung", "Gespräch"} <= set(report["heads"])
    for group in GROUPS:
        data = report["groups"][group]
        assert data["wordButtons"] == 0, group
        assert data["hasTop"] is True, group
        assert data["sign"] is True and data["buttonText"] == "", group


def test_each_sign_has_the_word_as_its_tooltip_and_the_group_and_field_as_its_name(report):
    for group, (name, _) in GROUPS.items():
        data = report["groups"][group]
        assert data["title"] == "Zurücksetzen", group
        assert data["label"] == name, group


def test_the_sign_is_30_square_in_the_line_of_the_name_at_the_rows_right_end(report):
    for group in GROUPS:
        data = report["groups"][group]
        button, name, row, field = data["button"], data["name"], data["row"], data["field"]
        assert round(button["width"]) == 30 and round(button["height"]) == 30, group
        centre = (button["top"] + button["bottom"]) / 2
        assert abs(centre - (name["top"] + name["bottom"]) / 2) <= 1.5, group
        assert abs(button["right"] - (row["right"] - data["rowPadding"])) <= 1, group
        # The field stands under both, over the whole width of the row's inside.
        assert field["top"] >= max(button["bottom"], name["bottom"]) - 1, group
        assert abs(field["left"] - (row["left"] + data["rowPadding"])) <= 1, group
        assert abs(field["right"] - (row["right"] - data["rowPadding"])) <= 1, group


def test_a_click_after_a_change_puts_the_works_text_of_that_instruction_back(report):
    for group, (_, works) in GROUPS.items():
        data = report["groups"][group]
        assert data["changed"] == "changed text", group
        assert data["afterClick"] == works, group


def test_silence_the_buttons_of_the_voice_sample_stay_34_square(report):
    assert report["probe"], "the voice sample row has buttons"
    assert all(size == {"w": 34, "h": 34} for size in report["probe"])


def test_silence_the_preparation_window_keeps_its_sign_button(report):
    data = report["preparation"]
    assert data is not None
    assert (data["w"], data["h"]) == (30, 30)
    assert data["title"] == "Zurücksetzen" and data["label"] == "Zurücksetzen" and data["sign"] is True
    assert data["field"]["top"] >= data["top"]["bottom"] - 1
