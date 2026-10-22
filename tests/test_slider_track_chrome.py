"""The track of every slider stands as drawn, in a real browser: the empty
stretch in the strong line colour, the filled stretch in the text colour, on
the pages of the model, the speech, the embedding and the clean-up server —
and the track of the parameter board stays as it was.

The real pages are built as shipped on the stub of ``tests/model_windows_page.py``,
which this file widens by the answers of the embedding, speech and clean-up
servers (the shared file stays as it is). The track is read off the track
pseudo-element of the range input, so it is the painted colour that is
measured, not the name of a variable. Skipped where there is no Chrome or no
node, like the other browser tests.
"""

from __future__ import annotations

import re
from unittest import mock

import pytest

from tests import model_windows_page as harness
from tests.model_windows_page import BROWSER_TESTS_POSSIBLE, ROOT, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        not BROWSER_TESTS_POSSIBLE, reason="no node or no frontend dependencies on this machine"
    ),
]

SHELL_IMPORTS = (
    "  import Einbettungsserver from '../../src/teile/Einbettungsserver.svelte'\n"
    "  import Bereinigungsserver from '../../src/teile/Bereinigungsserver.svelte'\n"
    "  import Sprachserver from '../../src/teile/Sprachserver.svelte'\n"
    "  import Schieberegler from '../../src/teile/Schieberegler.svelte'\n"
)
SHELL_SCENES = (
    "  {#if scene.show === 'embed'}<Einbettungsserver />{/if}\n"
    "  {#if scene.show === 'bereinigung'}<Bereinigungsserver />{/if}\n"
    "  {#if scene.show === 'sprach'}<Sprachserver />{/if}\n"
    "  {#if scene.show === 'plain'}<Schieberegler wert={5} min={0} max={10} />{/if}\n"
)

STUB_METHODS = """const putz = { putzkontext: 2048, putzschichten: 99, putzfaeden: 0, putztemperatur: 0, putztop_k: 0,
  putztop_p: 1, putzmin_p: 0, putzstrafe: 1 }
const works = {
  sprache: 'auto', anweisung: 'x', bereinigung: 'aus', putzmodell: 'clean.gguf', bereinigung_anweisung: 'y',
  vorlesen: true, keep_model_in_memory: true, conversation_pause_seconds: 3, stimme: '', stimmprobe: '',
  stimmsprache: '', stimmtemperatur: 0.9, stimmtop_k: 50, stimmtop_p: 1, stimmmin_p: 0, stimmstrafe: 1.05,
  stimmschichten: 99, stimmfaeden: 0, gespraechsanweisung: 'z', automatik: false, microphone_key: 'Meta+Alt',
  ...putz,
}
methods.einbettungAuskunft = async () => ({
  ...program, ordner: '/m', modelle: [{ name: 'embed.gguf', groesse_gb: 0.6 }],
  laeuft: false, modell: 'embed.gguf', selected_model: 'embed.gguf', port: 8081, belegt_gb: null,
  unknown_architecture: null, context: 2048, batch: 2048, pooling: '', layers: null, threads: 0,
  mlock: false, parallel: null,
})
methods.bereinigungAuskunft = async () => ({
  ...program, ordner: '/m', modelle: [{ name: 'clean.gguf', groesse_gb: 1 }], laeuft: false,
  modell: null, port: 8085, kerne: 8, unknown_architecture: null, diktat_vorgaben: copy(works),
})
methods.spracheAuskunft = async () => ({
  ...program, ordner: '/m', modelle: [{ name: 'voice.gguf', groesse_gb: 1 }], mmproj: [],
  projektoren: { 'voice.gguf': 'mm.gguf' }, laeuft: false, modell: null, port: 8084,
  kontext: null, schichten: null, threads: null, kerne: 8, unknown_architecture: null,
  vorgaben: { kontext: 4096, schichten: 99, threads: 0 }, diktat_vorgaben: copy(works), stimmproben: [],
})
methods.bereinigungProtokoll = async () => []
methods.spracheProtokoll = async () => []
methods.speicherBlick = async () => ({ wired_limit_gb: 20, gesamt_gb: 32 })
"""

CASES = r"""
const stub = window.__stub
texte.katalog = germanTexts
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const report = {}

// The browser gives no computed style for the track and grip of a range input,
// so the rules of the shipped style sheets are read: for each property the
// last rule whose selector, without its pseudo-element, matches the input is
// the one in force (the more specific rule of a filled slider stands after
// the plain one).
const valueOf = (input, pseudo, property) => {
  let found = ''
  for (const sheet of document.styleSheets) {
    for (const rule of sheet.cssRules) {
      if (!rule.selectorText || !rule.selectorText.includes(pseudo)) continue
      for (const selector of rule.selectorText.split(',')) {
        if (!selector.includes(pseudo)) continue
        const bare = selector.replace(pseudo, '').trim()
        let hit = false
        try { hit = input.matches(bare) } catch (e) { /* not a selector of this engine */ }
        const value = rule.style.getPropertyValue(property)
        if (hit && value) found = value
      }
    }
  }
  return found
}
const colourNames = (value) => [...value.matchAll(/var\((--[a-z-]+)\)/g)].map((m) => m[1]).filter((n) => n !== '--anteil')
const trackOf = (input) => {
  const background = valueOf(input, '::-webkit-slider-runnable-track', 'background')
  return { background, names: colourNames(background), height: valueOf(input, '::-webkit-slider-runnable-track', 'height') }
}
const gripOf = (input) => ({
  width: valueOf(input, '::-webkit-slider-thumb', 'width'),
  height: valueOf(input, '::-webkit-slider-thumb', 'height'),
  names: colourNames(valueOf(input, '::-webkit-slider-thumb', 'background')),
})
const measure = (scope) => [...scope.querySelectorAll('input[type=range]')].map((input) => ({
  id: input.id,
  track: trackOf(input),
  grip: gripOf(input),
  filled: input.closest('.regler')?.classList.contains('fuellung') ?? false,
}))

const open = async (name, ready) => {
  scene.show = null
  await wait(200)
  scene.show = name
  for (let k = 0; k < 100 && !ready(); k += 1) await wait(100)
  await wait(500)
}

await open('modell', () => document.querySelector('input[type=range]'))
report.model = measure(document)
await open('embed', () => document.querySelector('input[type=range]'))
report.embedding = measure(document)
await open('sprach', () => document.querySelector('input[type=range]'))
report.speech = measure(document)
await open('bereinigung', () => document.querySelector('input[type=range]'))
report.cleanup = measure(document)

// A slider without the filled stretch: the whole track is the strong line colour.
await open('plain', () => document.querySelector('input[type=range]'))
report.plain = measure(document)

// The track moved: the share the filled stretch runs to follows the grip.
const first = document.querySelector('input[type=range]')
const share = () => first.closest('.regler').style.getPropertyValue('--anteil')
first.value = first.min
first.dispatchEvent(new Event('input', { bubbles: true }))
await wait(200)
const atStart = share()
first.value = first.max
first.dispatchEvent(new Event('input', { bubbles: true }))
await wait(200)
report.moves = { atStart, atEnd: share(), disabled: first.disabled }

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


SLIDER_SOURCE = ROOT / "frontend" / "src" / "teile" / "Schieberegler.svelte"


def _every_slider(report):
    for page in ("model", "embedding", "speech", "cleanup"):
        sliders = report[page]
        assert sliders, f"no slider on the {page} server page"
        for slider in sliders:
            yield page, slider


def test_the_empty_stretch_of_every_slider_is_the_strong_line_colour(report):
    for page, slider in _every_slider(report):
        assert slider["track"]["names"][-1] == "--linie-stark", (page, slider["id"], slider["track"])


def test_the_filled_stretch_of_every_slider_is_the_text_colour(report):
    for page, slider in _every_slider(report):
        assert slider["filled"], (page, slider["id"])
        assert slider["track"]["names"] == ["--text", "--linie-stark"], (page, slider["id"], slider["track"])


def test_the_track_keeps_its_height_and_the_grip_its_size(report):
    for page, slider in _every_slider(report):
        assert slider["track"]["height"] == "4px", (page, slider["id"])
        assert (slider["grip"]["width"], slider["grip"]["height"]) == ("16px", "16px"), (page, slider["id"])
        assert slider["grip"]["names"] == ["--text"], (page, slider["id"])


def test_the_filled_stretch_follows_the_grip(report):
    moves = report["moves"]
    assert moves["disabled"] is False
    assert moves["atStart"] == "0%"
    assert moves["atEnd"] == "100%"


def test_a_slider_without_the_filled_stretch_has_the_strong_line_colour_all_along(report):
    (slider,) = report["plain"]
    assert slider["filled"] is False
    assert slider["track"]["names"] == ["--linie-stark"], slider["track"]
    assert slider["track"]["height"] == "4px"


def test_the_firefox_track_rules_paint_the_same_as_the_chrome_ones():
    # Chrome drops a rule it does not know the pseudo-element of, so the
    # Firefox rules cannot be read off the page: compare the style text.
    source = SLIDER_SOURCE.read_text(encoding="utf-8")

    def backgrounds(pseudo: str) -> list[str]:
        pattern = re.escape(pseudo) + r"\s*\{[^}]*?background:\s*([^;]+);"
        return re.findall(pattern, source)

    chrome = backgrounds("::-webkit-slider-runnable-track")
    firefox = backgrounds("::-moz-range-track")
    assert len(chrome) == len(firefox) == 2
    assert chrome == firefox
    assert "var(--linie-stark)" in chrome[0] and "var(--text)" in chrome[1]


def test_the_parameter_board_still_draws_its_own_track():
    source = (ROOT / "frontend" / "src" / "teile" / "Parametertafel.svelte").read_text(encoding="utf-8")
    assert "linear-gradient(to right, var(--text) var(--anteil), var(--linie-stark) var(--anteil))" in source
