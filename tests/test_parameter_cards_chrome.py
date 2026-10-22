"""The parameter panel (Parametertafel) in a real browser: two cards of the same
width under the head, in the order of one rule, each ending on its last row;
one under the other in a narrow frame; and the slider track showing its whole
length — the part up to the grip in the text colour, the rest in the strong
line colour.

The real component is built as it ships, with only the service's answers
replaced (`lib/api.js` by a stand-in) and the real German texts put in. Three
panels stand in one page: a model with all twelve knobs in a wide frame, one
with seven in a wide frame, and the twelve in a 500 px frame. Skipped where
there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import Parametertafel from '../../src/teile/Parametertafel.svelte'
  import { models } from './models.svelte.js'
</script>

<div id="twelve" style="width: 1000px; margin: 0 0 40px 20px; display: flex;">
  <Parametertafel modell={models.twelve} withName />
</div>
<div id="seven" style="width: 1000px; margin: 0 0 40px 20px; display: flex;">
  <Parametertafel modell={models.seven} withName />
</div>
<div id="odd" style="width: 1000px; margin: 0 0 40px 20px; display: flex;">
  <Parametertafel modell={models.odd} withName />
</div>
<div id="narrow" style="width: 500px; margin: 0 0 40px 20px; display: flex;">
  <Parametertafel modell={models.narrow} withName />
</div>
"""

MODELS_JS = """const knob = (name, label, minimum, maximum, step, extra = {}) =>
  ({ name, label, hinweis: label + ' hint', minimum, maximum, schritt: step, ganzzahl: false, gruppe: 'sichtbar', ...extra })

const ALL = [
  knob('temperature', 'Temperatur', 0, 2, 0.05),
  knob('top_p', 'Top-P', 0, 1, 0.01),
  knob('max_tokens', 'Antwortlänge', 256, 1000000, 256, { ganzzahl: true }),
  knob('reasoning_budget', 'Denklänge', -1, 1000000, 256, { ganzzahl: true, aktiv: false, grund: 'Thinking is off for this model' }),
  knob('top_k', 'Top-K', 0, 200, 1, { ganzzahl: true, gruppe: 'mehr' }),
  knob('min_p', 'Min-P', 0, 1, 0.01, { gruppe: 'mehr' }),
  knob('repeat_penalty', 'Wiederholungsbremse', 1, 2, 0.01, { gruppe: 'mehr' }),
  knob('repeat_last_n', 'Bremse wirkt auf', 0, 2048, 16, { ganzzahl: true, gruppe: 'mehr' }),
  knob('presence_penalty', 'Themenwechsel', -2, 2, 0.05, { gruppe: 'mehr' }),
  knob('frequency_penalty', 'Wortwiederholung', -2, 2, 0.05, { gruppe: 'mehr' }),
  knob('typical_p', 'Typical-P', 0, 1, 0.01, { gruppe: 'mehr' }),
  knob('seed', 'Startwert', -1, 2147483647, 1, { ganzzahl: true, gruppe: 'mehr' }),
]
const SEVEN = ['temperature', 'top_p', 'max_tokens', 'reasoning_budget', 'presence_penalty', 'frequency_penalty', 'seed']

export const models = $state({
  twelve: { id: 'twelve', name: 'Local-Model.gguf', parameter: ALL },
  seven: { id: 'seven', name: 'Cloud-Model', parameter: ALL.filter((p) => SEVEN.includes(p.name)) },
  narrow: { id: 'narrow', name: 'Narrow.gguf', parameter: ALL },
  // Lengths only, and one knob that is in neither list.
  odd: { id: 'odd', name: 'Odd-Model', parameter: [
    ALL.find((p) => p.name === 'max_tokens'), ALL.find((p) => p.name === 'reasoning_budget'),
    knob('mirostat', 'Mirostat', 0, 2, 1, { ganzzahl: true, gruppe: 'mehr' }),
  ] },
})
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { texte } from '../../src/lib/texte.svelte.js'
import katalog from '../../../app/locales/de.json'
import '../../src/stil/global.css'

texte.katalog = katalog
mount(Shell, { target: document.getElementById('root') })
"""

API_STUB = """export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* antwortStrom() {}
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
// The stored values: a temperature, a response length of 200000 and the seed left at -1.
export const api = new Proxy({}, {
  get: (_, name) => async () => name === 'einstellungAufgeloest'
    ? { wert: { temperature: 0.7, max_tokens: 200000, seed: -1 }, herkunft: { temperature: 'modell:x', max_tokens: 'modell:x', seed: 'modell:x' } }
    : {},
})
"""

CASES = r"""
const report = { errors: [] }
window.addEventListener('error', (event) => report.errors.push(String(event.message)))
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
await wait(1200)

const box = (el) => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height } }
const rgb = (value) => { const probe = document.createElement('span'); probe.style.color = value; document.body.appendChild(probe); const c = getComputedStyle(probe).color; probe.remove(); return c }

const panel = (id) => {
  const root = document.getElementById(id)
  const cards = [...root.querySelectorAll('.param-cards > .abschnitt > .karte')]
  return {
    title: root.querySelector('.tafelkopf .name').textContent.trim(),
    reset: Boolean(root.querySelector('.tafelkopf button[aria-label]')),
    cards: cards.map((card) => {
      const rows = [...card.querySelectorAll(':scope > .zeile.regel')]
      return {
        box: box(card),
        radius: getComputedStyle(card).borderRadius,
        labels: rows.map((row) => row.querySelector('.regelname').textContent.trim()),
        tops: rows.map((row) => getComputedStyle(row).borderTopWidth),
        lastBottom: rows.length ? box(rows[rows.length - 1]).bottom : null,
        firstTop: rows.length ? box(rows[0]).top : null,
        locked: rows.filter((row) => row.classList.contains('gesperrt')).map((row) => ({ label: row.querySelector('.regelname').textContent.trim(), title: row.title })),
      }
    }),
    emptyCells: root.querySelectorAll('.param-cards .karte:empty').length,
  }
}
report.twelve = panel('twelve')
report.seven = panel('seven')
report.narrow = panel('narrow')
report.odd = panel('odd')

// The track of the sliders: its drawing, as the browser computed it.
const text = rgb('var(--text)')
const strong = rgb('var(--linie-stark)')
const tracks = {}
for (const [name, id] of [['seed', 'pt-seed'], ['temperature', 'pt-temperature'], ['max_tokens', 'pt-max_tokens']]) {
  const slider = document.querySelector('#twelve #' + id)
  tracks[name] = { image: getComputedStyle(slider).backgroundImage, share: getComputedStyle(slider).getPropertyValue('--anteil').trim(), height: box(slider).height }
}
report.tracks = { text, strong, ...tracks }

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>parameter cards</title>
<style>body { margin: 0; background: #1c1c1a; padding-top: 20px; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  window.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16)
  window.cancelAnimationFrame = (id) => clearTimeout(id)
</script>
<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      %(cases)s
    } catch (failure) {
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure) })
    }
  })
</script>
"""

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { fileURLToPath } from 'node:url'

const stub = fileURLToPath(new URL('./api_stub.js', import.meta.url))

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  logLevel: 'error',
  resolve: { alias: [{ find: /^(?:\\.|.*\\/lib)\\/api\\.js$/, replacement: stub }] },
  build: {
    outDir: 'out',
    emptyOutDir: true,
    minify: false,
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _read_result(port: int, limit: float = 240.0) -> str:
    websockets = pytest.importorskip("websockets")
    end = time.monotonic() + limit
    address = None
    while time.monotonic() < end and address is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                for page in json.load(response):
                    if page.get("type") == "page" and "measure.html" in page.get("url", ""):
                        address = page["webSocketDebuggerUrl"]
        except OSError:
            pass
        if address is None:
            await asyncio.sleep(0.2)
    assert address, "Chrome did not open the page"
    async with websockets.connect(address, max_size=16 * 1024 * 1024) as connection:
        number = 0
        while time.monotonic() < end:
            number += 1
            await connection.send(json.dumps({
                "id": number,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.getElementById('ergebnis')?.textContent || ''",
                           "returnByValue": True},
            }))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    break
            value = response.get("result", {}).get("result", {}).get("value", "")
            if value:
                return value
            await asyncio.sleep(0.5)
    return ""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-paramcards-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "models.svelte.js").write_text(MODELS_JS, encoding="utf-8")
        (folder / "api_stub.js").write_text(API_STUB, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1100,2400", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_read_result(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
        assert raw, "the page reported nothing"
        result = json.loads(raw)
        assert "failure" not in result, result["failure"]
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


SAMPLING = ["Temperatur", "Top-P", "Top-K", "Min-P", "Typical-P", "Startwert"]
LENGTHS = ["Antwortlänge", "Denklänge", "Wiederholungsbremse", "Bremse wirkt auf", "Themenwechsel", "Wortwiederholung"]


def test_the_page_ran_without_a_script_error(report):
    assert report["errors"] == []


def test_twelve_knobs_stand_in_two_cards_of_the_same_width_24_px_apart_level_at_the_top(report):
    left, right = report["twelve"]["cards"]
    assert abs(left["box"]["width"] - right["box"]["width"]) <= 1
    assert abs((right["box"]["left"] - left["box"]["right"]) - 24) <= 1
    assert abs(left["box"]["top"] - right["box"]["top"]) <= 1
    assert left["radius"] == right["radius"] == "9px"


def test_the_left_card_picks_and_the_right_one_lengths_and_brakes_each_in_its_order(report):
    left, right = report["twelve"]["cards"]
    assert left["labels"] == SAMPLING
    assert right["labels"] == LENGTHS


def test_a_line_stands_under_every_row_but_the_last_and_each_card_ends_on_its_last_row(report):
    for card in report["twelve"]["cards"]:
        assert card["tops"][0] == "0px"
        assert all(width == "1px" for width in card["tops"][1:])
        assert abs(card["box"]["bottom"] - card["lastBottom"]) <= 1
        assert abs(card["box"]["top"] - card["firstTop"]) <= 1


def test_seven_knobs_stand_three_left_and_four_right_with_no_empty_cell(report):
    left, right = report["seven"]["cards"]
    assert left["labels"] == ["Temperatur", "Top-P", "Startwert"]
    assert right["labels"] == ["Antwortlänge", "Denklänge", "Themenwechsel", "Wortwiederholung"]
    assert report["seven"]["emptyCells"] == 0
    for card in (left, right):
        assert card["radius"] == "9px"
        assert abs(card["box"]["bottom"] - card["lastBottom"]) <= 1
    # Each card is as high as its rows: the shorter one does not grow to the taller one.
    assert left["box"]["height"] < right["box"]["height"]


def test_in_a_500_px_frame_the_cards_stand_one_under_the_other_24_px_apart(report):
    top, bottom = report["narrow"]["cards"]
    assert abs(top["box"]["left"] - bottom["box"]["left"]) <= 1
    assert abs(top["box"]["width"] - bottom["box"]["width"]) <= 1
    assert abs((bottom["box"]["top"] - top["box"]["bottom"]) - 24) <= 1
    assert top["labels"] == SAMPLING and bottom["labels"] == LENGTHS


def test_the_head_the_reset_and_the_locked_row_with_its_reason_are_as_before(report):
    twelve = report["twelve"]
    assert twelve["title"] == "Parameter · Local-Model.gguf"
    assert twelve["reset"] is True
    locked = [row for card in twelve["cards"] for row in card["locked"]]
    assert locked == [{"label": "Denklänge", "title": "Thinking is off for this model"}]


def _stops(image: str) -> list[tuple[str, str]]:
    """The colour stops of `linear-gradient(to right, <colour> <at>, <colour> <at>)`."""
    return re.findall(r"(rgba?\([^)]*\)) ([0-9.]+%)", image)


def test_the_track_shows_its_whole_length_text_colour_up_to_the_grip_strong_line_after_it(report):
    tracks = report["tracks"]
    for name in ("temperature", "max_tokens"):
        full, empty = _stops(tracks[name]["image"])
        assert full[0] == tracks["text"], name
        assert empty[0] == tracks["strong"], name
        assert full[1] == empty[1], name
        assert abs(float(full[1][:-1]) - float(tracks[name]["share"][:-1])) < 0.01, name
    assert tracks["text"] != tracks["strong"]


def test_a_knob_at_the_low_end_shows_the_whole_track_in_the_strong_line_colour(report):
    tracks = report["tracks"]
    full, empty = _stops(tracks["seed"]["image"])
    assert full[1] == empty[1] == "0%"
    assert empty[0] == tracks["strong"]


def test_the_knob_is_16_px_in_the_text_colour_and_the_track_4_px(report):
    style = (FRONTEND / "src" / "teile" / "Parametertafel.svelte").read_text(encoding="utf-8").split("<style>", 1)[1]
    thumb = style.split(".regelspur::-webkit-slider-thumb {", 1)[1].split("}", 1)[0]
    assert "width: 16px" in thumb and "height: 16px" in thumb and "background: var(--text)" in thumb
    assert report["tracks"]["temperature"]["height"] == 4


def test_a_knob_in_neither_list_ends_the_right_card_and_a_card_without_rows_is_not_drawn(report):
    cards = report["odd"]["cards"]
    # No sampling knob offered: only the right card is drawn, with the unknown knob last.
    assert len(cards) == 1
    assert cards[0]["labels"] == ["Antwortlänge", "Denklänge", "Mirostat"]
    assert report["odd"]["emptyCells"] == 0
