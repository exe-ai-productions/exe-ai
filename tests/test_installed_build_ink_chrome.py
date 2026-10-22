"""The word "Installed" in the list of the server program's builds, in a real
browser, in each look of the program.

The word stands in the colour of a text (``--gruen-text``), the tick behind it
in the colour of a shape (``--gruen``), as the word and the tick of a finished
download do. The two greens differ in the lighter looks and are equal in Exe and
Moune. The word stays 13 px and regular; a greyed build of a Mac has no word.

The real card is built as shipped on the stub of ``tests/model_windows_page.py``,
which this file widens by the two answers about the program's download (the
shared file stays as it is); the list of builds is made up, because every build
is greyed on a Mac. Skipped where there is no Chrome or no node.
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

SHELL_SCENES = """  {#if scene.show === 'list' || scene.show === 'greyed'}
    <LlamaCppSection auskunft={{ programm: null, version: null, updatable: false, restorable: false }} />
  {/if}
"""

STUB_METHODS = """methods.serverProgrammStand = async () => ({})
methods.serverProgrammVarianten = async () => stub.variants ?? {}
"""

CASES = r"""
const stub = window.__stub
texte.katalog = germanTexts
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const probe = document.createElement('span')
document.body.appendChild(probe)
const colourOf = (value) => { probe.style.color = value; const read = getComputedStyle(probe).color; probe.style.color = ''; return read }
const builds = ['cpu', 'cuda12', 'vulkan', 'rocm'].map((variante) => ({ variante, groesse: 1000000 }))
const until = async (test) => { for (let k = 0; k < 100 && !test(); k += 1) await wait(100) }
const look = (node) => {
  const style = getComputedStyle(node)
  return { text: node.textContent.replace(/\s+/g, ' ').trim(), colour: style.color, weight: style.fontWeight, size: style.fontSize }
}
const MODES = { pearl: 'hell', exe: 'dunkel', darkmatter: 'darkmatter', heaven: 'heaven', moune: 'moune' }
const report = { themes: {} }

stub.variants = { varianten: builds, installiert: 'cuda12' }
scene.show = 'list'
await until(() => document.querySelector('.da'))
await wait(200)
for (const [name, mode] of Object.entries(MODES)) {
  if (mode) document.documentElement.setAttribute('data-modus', mode)
  else document.documentElement.removeAttribute('data-modus')
  await wait(150)
  const word = document.querySelector('.da')
  const tick = word.querySelector('.haken')
  report.themes[name] = {
    expectedText: colourOf('var(--gruen-text)'),
    expectedShape: colourOf('var(--gruen)'),
    word: look(word),
    tick: { colour: getComputedStyle(tick).color },
    tickSvg: getComputedStyle(tick.querySelector('svg')).color,
  }
}
report.installedRows = [...document.querySelectorAll('.karte .zeile')].map((row) => ({
  name: row.querySelector('.name')?.textContent.trim() ?? null,
  installed: Boolean(row.querySelector('.da')),
  button: Boolean(row.querySelector('button')),
}))

// A Mac: every build greyed, and no build says it is installed.
document.documentElement.removeAttribute('data-modus')
scene.show = null
await wait(300)
stub.variants = { unavailable: builds, installiert: 'cuda12' }
scene.show = 'greyed'
await until(() => document.querySelector('.zeile.gesperrt'))
await wait(200)
report.greyed = {
  rows: document.querySelectorAll('.zeile.gesperrt').length,
  words: document.querySelectorAll('.da').length,
}
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


LIGHT_AND_DARK_LOOKS = ["pearl", "darkmatter", "heaven"]


@pytest.mark.parametrize("theme", LIGHT_AND_DARK_LOOKS)
def test_the_word_wears_the_colour_of_a_text_and_the_tick_the_colour_of_a_shape(report, theme):
    data = report["themes"][theme]
    assert data["word"]["text"] == "Installiert", theme
    assert data["word"]["colour"] == data["expectedText"], theme
    assert data["tick"]["colour"] == data["expectedShape"], theme
    # The tick is drawn in the colour it stands in.
    assert data["tickSvg"] == data["expectedShape"], theme
    # The two greens are two colours in these looks.
    assert data["expectedText"] != data["expectedShape"], theme


@pytest.mark.parametrize("theme", ["exe", "moune"])
def test_where_the_two_greens_are_one_colour_the_word_and_the_tick_agree(report, theme):
    data = report["themes"][theme]
    assert data["expectedText"] == data["expectedShape"], theme
    assert data["word"]["colour"] == data["tick"]["colour"] == data["expectedText"], theme


def test_silence_the_word_stays_13_px_and_regular(report):
    for theme, data in report["themes"].items():
        assert (data["word"]["size"], data["word"]["weight"]) == ("13px", "400"), theme


def test_silence_only_the_installed_build_says_so_and_the_others_keep_their_button(report):
    rows = {row["name"]: row for row in report["installedRows"]}
    assert rows["cuda12"]["installed"] is True
    for name in ("cpu", "vulkan", "rocm"):
        assert rows[name]["installed"] is False and rows[name]["button"] is True, name


def test_silence_the_greyed_builds_of_a_mac_have_no_word(report):
    assert report["greyed"]["rows"] == 4
    assert report["greyed"]["words"] == 0
