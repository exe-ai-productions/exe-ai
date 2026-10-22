"""The llama.cpp card of the server windows, in a real browser, after a download
that failed: the sentence "Download failed" stands in the red of a sentence
(``--rot-text``) — beside the button where no program is there yet and in the
list of the builds — and not in the reading colour or in the red of a dot.
The names of the builds and the version line stay in the reading colour and
semi-bold, the sentence in the list stays regular.

The real card is built as shipped on the stub of ``tests/model_windows_page.py``,
which this file widens by the two answers about the program's download (the
shared file stays as it is); the failed download is made up. Skipped where
there is no Chrome or no node.
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

SHELL_IMPORTS = "  import LlamaCppSection from '../../src/teile/LlamaCppSection.svelte'\n"

SHELL_SCENES = """  {#if scene.show === 'beside' || scene.show === 'list'}
    <LlamaCppSection auskunft={{ programm: null, version: null, updatable: false, restorable: false }} />
  {/if}
"""

STUB_METHODS = """methods.serverProgrammStand = async () => stub.programState ?? {}
methods.serverProgrammVarianten = async () => stub.variants ?? {}
"""

CASES = r"""
const stub = window.__stub
texte.katalog = germanTexts
const probe = document.createElement('span')
document.body.appendChild(probe)
const colourOf = (value) => { probe.style.color = value; const read = getComputedStyle(probe).color; probe.style.color = ''; return read }
const look = (node) => {
  const style = getComputedStyle(node)
  return {
    text: node.textContent.trim(), colour: style.color, weight: style.fontWeight, size: style.fontSize,
    classes: node.className.replace(/svelte-\w+/g, '').trim(),
  }
}
// Waits for the card to draw the sentence instead of a fixed time.
const until = async (test) => {
  for (let k = 0; k < 100 && !test(); k += 1) await new Promise((done) => setTimeout(done, 100))
}
const report = {
  rotText: colourOf('var(--rot-text)'), rot: colourOf('var(--rot)'), text: colourOf('var(--text)'),
}
stub.programState = { fehler: true, fertig: false, anteil: 0 }
// A machine that has no list to choose from: the sentence stands beside the button.
stub.variants = {}
scene.show = 'beside'
await until(() => document.querySelector('.v_fehler'))
report.beside = [...document.querySelectorAll('.v_fehler')].map(look)
report.besideButton = [...document.querySelectorAll('.zeile button.feldknopf')].map((b) => b.textContent.trim())
scene.show = null
await new Promise((done) => setTimeout(done, 300))
// A machine with a list of builds: the sentence stands in the list.
stub.variants = { varianten: [{ variante: 'cpu', groesse: 0 }, { variante: 'cuda12', groesse: 0 }], installiert: null }
scene.show = 'list'
await until(() => document.querySelector('.v_fehler') && document.querySelector('.karte .zeile .name'))
await new Promise((done) => setTimeout(done, 200))
report.list = [...document.querySelectorAll('.v_fehler')].map(look)
report.names = [...document.querySelectorAll('.karte .zeile .name')]
  .filter((node) => !node.classList.contains('v_fehler'))
  .map(look)
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


def test_the_page_has_the_house_reds_and_they_differ(report):
    # The sentence red and the dot red are two colours, and neither is the reading colour.
    assert report["rotText"] != report["rot"]
    assert report["rotText"] != report["text"] and report["rot"] != report["text"]


def test_the_sentence_beside_the_button_stands_in_the_red_of_a_sentence(report):
    assert len(report["beside"]) == 1, report["beside"]
    sentence = report["beside"][0]
    assert sentence["text"] == "Download fehlgeschlagen"
    assert sentence["colour"] == report["rotText"], sentence
    # The button that tries again is still there.
    assert report["besideButton"], report["besideButton"]


def test_the_sentence_in_the_list_of_the_builds_stands_in_the_red_of_a_sentence_and_regular(report):
    assert len(report["list"]) == 1, report["list"]
    sentence = report["list"][0]
    assert sentence["text"] == "Download fehlgeschlagen"
    assert "name" in sentence["classes"], sentence
    assert sentence["colour"] == report["rotText"], sentence
    assert (sentence["weight"], sentence["size"]) == ("400", "13px"), sentence


def test_the_names_of_the_builds_and_the_version_line_stay_in_the_reading_colour_and_semi_bold(report):
    names = report["names"]
    texts = [name["text"] for name in names]
    assert "cpu" in texts and "cuda12" in texts and any(text.startswith("Version") for text in texts), texts
    for name in names:
        assert name["colour"] == report["text"], name
        assert name["weight"] == "600", name
