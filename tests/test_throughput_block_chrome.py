"""The block "Performance" at the top of the text servers' windows, in a real
browser.

The model, agent, clean-up and speech windows are built as shipped and drawn
in headless Chrome on the stand-in of ``tests/model_windows_page.py``, with
the German texts the window shows and the service's answer for the tokens per
second replaced. The picture and embedding windows make no text and carry no
block. Skipped where there is no Chrome or no node, like the other browser
tests.
"""

from __future__ import annotations

from unittest import mock

import pytest

from tests import model_windows_page

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        not model_windows_page.BROWSER_TESTS_POSSIBLE,
        reason="no node or no frontend dependencies on this machine",
    ),
]

TEXT_PAGES = ["modell", "agent", "cleanup", "speech"]
OTHER_PAGES = ["einbettung", "bild"]
SERVER_OF = {"modell": "model", "agent": "agent", "cleanup": "cleanup", "speech": "speech"}

# Each group is one fresh browser: the windows that the stand-in answers only
# in part end their own effects with an error, and nothing after them in the
# same page would run again — so those stand alone.
GROUPS = [["modell", "agent"], ["cleanup"], ["speech"], ["einbettung", "bild"]]

HISTORY = [0.0] * 10 + [30.0, 40.0, 38.0] * 4 + [0.0] * 8

MEASURE = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
window.texte.katalog = window.germanTexts
const out = { pages: {}, calls: [] }
const readBlock = () => {
  const block = document.querySelector('.leistung')
  if (!block) return null
  const first = document.querySelector('.reihe')
  const line = block.querySelector('.linie')
  const area = block.querySelector('.flaeche')
  const svg = block.querySelector('.verlauf')
  const ys = [...line.getAttribute('d').matchAll(/[ML]([\d.]+),([\d.]+)/g)].map((m) => +m[2])
  return {
    heading: block.closest('.abschnitt').querySelector('.name').textContent.trim(),
    title: block.querySelector('.metric-name').textContent.trim(),
    figure: block.querySelector('.gross').textContent.trim(),
    unit: block.querySelector('.einheit').textContent.trim(),
    average: block.querySelector('.schnitt').textContent.trim(),
    points: ys.length,
    ys,
    areaClosed: /Z$/.test(area.getAttribute('d')),
    stroke: getComputedStyle(line).stroke,
    ink: getComputedStyle(svg).color,
    blockTop: block.getBoundingClientRect().top,
    rowTop: first ? first.getBoundingClientRect().top : null,
  }
}
for (const name of %(order)s) {
  window.__throughput = null
  scene.show = name
  await wait(1200)
  const empty = readBlock()
  window.__throughput = %(figures)s
  // The first window to answer with figures: a slow window mounts late and asks again two seconds on.
  for (let i = 0; i < 40 && document.querySelector('.gross')?.textContent.trim() === '-'; i++) await wait(300)
  await wait(300)
  out.pages[name] = { empty, filled: readBlock() }
  scene.show = null
  await wait(300)
}
// While a window is open the block asks every two seconds, and it stops
// asking the moment the window is gone.
if (%(polling)s) {
// (The speech window stays mounted after the scene is cleared and keeps asking
// for its own server; only the model window's asks are counted here.)
window.__throughputCalls = []
const modelCalls = () => window.__throughputCalls.filter((s) => s === 'model').length
scene.show = 'modell'
await wait(4600)
out.callsWhileOpen = modelCalls()
scene.show = null
await wait(300)
const closedAt = modelCalls()
await wait(4500)
out.callsAfterClose = modelCalls() - closedAt
}
document.getElementById('ergebnis').textContent = JSON.stringify(out)
"""


def _run(order: list[str]) -> dict:
    imports = (
        "  import Einbettungsserver from '../../src/teile/Einbettungsserver.svelte'\n"
        "  import Sprachserver from '../../src/teile/Sprachserver.svelte'\n"
        "  import Bildserver from '../../src/teile/Bildserver.svelte'\n"
        "  import Bereinigungsserver from '../../src/teile/Bereinigungsserver.svelte'\n"
    )
    scenes = (
        "  {#if scene.show === 'einbettung'}<Einbettungsserver />{/if}\n"
        "  {#if scene.show === 'speech'}<Sprachserver />{/if}\n"
        "  {#if scene.show === 'bild'}<Bildserver />{/if}\n"
        "  {#if scene.show === 'cleanup'}<Bereinigungsserver />{/if}\n"
    )
    anchors = (
        "  import { scene } from './scene.svelte.js'\n",
        "  {#if scene.show === 'modell'}",
    )
    for anchor in anchors:
        assert anchor in model_windows_page.SHELL, f"the shared harness changed, widen it again: {anchor!r}"
    shell = (
        model_windows_page.SHELL
        .replace(anchors[0], imports + anchors[0])
        .replace(anchors[1], scenes + anchors[1])
    )
    stub_anchor = "const methods = {\n"
    assert stub_anchor in model_windows_page.API_STUB, "the shared harness changed, widen it again"
    stub = model_windows_page.API_STUB.replace(
        stub_anchor,
        stub_anchor
        + "  spracheAuskunft: async () => ({ ...auskunft('chat'), ordner: '/s', modelle: [], laeuft: false }),\n"
        "  bereinigungAuskunft: async () => ({ ...auskunft('chat'), ordner: '/s', modelle: [], laeuft: false }),\n"
        "  serverThroughput: async (server) => {\n"
        "    (window.__throughputCalls ||= []).push(server)\n"
        "    return (window.__throughput && window.__throughput[server])\n"
        "      || { now: null, average: null, history: [] }\n"
        "  },\n",
    )
    figures = "{" + ", ".join(
        f"{server}: {{ now: 38.4, average: 36.9, history: {HISTORY} }}" for server in SERVER_OF.values()
    ) + "}"
    cases = MEASURE % {
        "order": repr(order),
        "figures": figures,
        "polling": "true" if order[0] == "modell" else "false",
    }
    with (
        mock.patch.object(model_windows_page, "SHELL", shell),
        mock.patch.object(model_windows_page, "API_STUB", stub),
    ):
        return model_windows_page.run_cases(cases)


@pytest.fixture(scope="module")
def result() -> dict:
    merged: dict = {"pages": {}}
    for order in GROUPS:
        run = _run(order)
        merged["pages"].update(run["pages"])
        for key in ("callsWhileOpen", "callsAfterClose"):
            if key in run:
                merged[key] = run[key]
    return merged


def test_the_four_text_servers_carry_the_block_with_its_words(result):
    for name in TEXT_PAGES:
        for state in ("empty", "filled"):
            block = result["pages"][name][state]
            assert block, f"{name}: no block ({state})"
            assert block["heading"] == "Leistung", (name, block)
            assert block["title"] == "Token pro Sekunde", (name, block)
            assert block["unit"] == "Token/s", (name, block)


def test_the_block_stands_above_the_rows_of_the_window(result):
    for name in ("modell", "agent", "speech"):
        block = result["pages"][name]["filled"]
        assert block["rowTop"] is not None and block["blockTop"] < block["rowTop"], (name, block)


def test_without_data_both_figures_read_a_dash_and_the_line_lies_flat(result):
    for name in TEXT_PAGES:
        block = result["pages"][name]["empty"]
        assert block["figure"] == "-", (name, block)
        assert block["average"] == "⌀ - · letzte 5 min", (name, block)
        assert block["points"] == 30, (name, block)
        assert set(block["ys"]) == {64.0}, (name, block)


def test_with_data_the_figures_and_the_course_are_drawn(result):
    for name in TEXT_PAGES:
        block = result["pages"][name]["filled"]
        assert block["figure"] == "38,4", (name, block)
        assert block["average"] == "⌀ 36,9 · letzte 5 min", (name, block)
        assert block["points"] == 30, (name, block)
        ys = block["ys"]
        # The pause is on the floor, the highest value stands 8 px below the top.
        assert ys[0] == 64.0 and ys[-1] == 64.0, (name, ys)
        assert min(ys) == pytest.approx(8.0), (name, ys)
        assert ys[11] == pytest.approx(8.0), (name, ys)
        assert block["areaClosed"], (name, block)


def test_the_line_is_in_the_colour_of_the_text_not_a_colour_of_its_own(result):
    for name in TEXT_PAGES:
        block = result["pages"][name]["filled"]
        assert block["stroke"] == block["ink"], (name, block)


def test_the_picture_and_embedding_windows_have_no_block(result):
    for name in OTHER_PAGES:
        assert result["pages"][name]["empty"] is None, name
        assert result["pages"][name]["filled"] is None, name


def test_the_block_asks_every_two_seconds_while_open_and_not_after(result):
    # 4.6 s open: the first ask at once, then one every two seconds.
    assert 2 <= result["callsWhileOpen"] <= 4, result["callsWhileOpen"]
    assert result["callsAfterClose"] == 0, result["callsAfterClose"]
