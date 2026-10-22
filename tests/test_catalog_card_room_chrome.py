"""The cards of the catalogue need no free room, measured in a real browser.

On the chat page every card is as high as its content and as high as every
other, in every state: a card that loads keeps its facts and shows its loading
row under them, its lower edge where the foot of a card at rest ends, and a
card at rest keeps that room free over its line, so none grows when a download
starts. A sentence stands in two lines, a longer one ends with an ellipsis and
is the card's tooltip. The box of the cards is as high as its content, the
column of the kinds reaches as deep as that box, and both end on one line,
above the foot of the window.

`Katalog.svelte` is built as shipped and drawn in headless Chrome in the area
right of the sidebar of a 1920 x 1080 window (1611 x 1064); the service is not
asked — the page answers every request itself, with a download that runs (made
up) and one that waits (made up in the queue). Skipped where there is no Chrome
or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
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
  import Katalog from '@@KATALOG@@'
</script>

<div id="shell" style="position: relative; width: @@AREA@@px; height: 1064px; overflow: hidden;">
  <Katalog offen={true} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '@@GLOBAL@@'
import german from '@@GERMAN@@'
import { texte } from '@@TEXTE@@'
import { downloads, einreihen } from '@@DOWNLOADS@@'
import { katalogFuer, passendeFassung } from '@@RECOMMENDATIONS@@'

texte.katalog = german
texte.sprache = 'de'
const MEMORY = 64
const scenario = { stand: null, there: [], hits: [], files: [] }
window.__scenario = scenario
window.__downloads = downloads
window.__enqueue = einreihen
window.__texte = texte
window.__cards = (kind) => katalogFuer(kind).map((card) => ({ id: card.id, build: passendeFassung(card, MEMORY) }))
window.fetch = async (address, options = {}) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const method = (options.method || 'GET').toUpperCase()
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  if (path === '/runner/download') {
    // The made-up download moves on a little with every question, so the
    // page can measure a speed.
    if (method === 'GET' && scenario.stand) scenario.stand.geladen += 6e7
    return json(scenario.stand)
  }
  if (path === '/runner') {
    return json({ speicher_gb: MEMORY, modelle: scenario.there.map((name) => ({ name })), mmproj: [], mtp: [] })
  }
  if (path === '/models/token') return json({ gesetzt: false })
  if (path === '/models/search') return json(scenario.hits)
  if (path === '/models/files') return json({ dateien: scenario.files, mmproj: null })
  if (path.startsWith('/models/avatar/')) return json({ detail: 'none' }, 404)
  return json({})
}
mount(Shell, { target: document.getElementById('wurzel') })
"""

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  logLevel: 'error',
  build: {
    outDir: 'out',
    emptyOutDir: true,
    minify: false,
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js', cssFileName: 'style' },
  },
})
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const rect = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : null)
const scenario = window.__scenario
const downloads = window.__downloads
const poll = () => wait(2600)
for (let k = 0; k < 80 && document.querySelectorAll('.karte').length === 0; k += 1) await wait(100)
await wait(500)

const cards = () => Array.from(document.querySelectorAll('.raster .karte'))
const measureCard = (node) => {
  const sentence = node.querySelector('.satz')
  const style = getComputedStyle(sentence)
  return {
    rect: rect(node),
    foot: rect(node.querySelector('.fuss')),
    facts: text(node.querySelector('.fakten')),
    factsWeight: node.querySelector('.fakten') ? getComputedStyle(node.querySelector('.fakten')).fontWeight : null,
    factsSize: node.querySelector('.fakten') ? getComputedStyle(node.querySelector('.fakten')).fontSize : null,
    row: rect(node.querySelector('.lauf')),
    room: rect(node.querySelector('.load-room')),
    sentence: rect(sentence),
    sentenceText: text(sentence),
    sentenceTitle: sentence.getAttribute('title'),
    sentenceSize: style.fontSize,
    sentenceLine: style.lineHeight,
    clipped: sentence.scrollHeight > sentence.clientHeight + 1,
    nameSize: getComputedStyle(node.querySelector('.name')).fontSize,
    nameWeight: getComputedStyle(node.querySelector('.name')).fontWeight,
    makerSize: getComputedStyle(node.querySelector('.von')).fontSize,
    padBottom: parseFloat(getComputedStyle(node).paddingBottom),
  }
}
const frame = () => ({
  columns: rect(document.querySelector('.two-columns')),
  kinds: rect(document.querySelector('.kinds')),
  page: rect(document.querySelector('.page')),
  grid: rect(document.querySelector('.raster')),
  shell: rect(document.getElementById('wurzel')),
  rows: Array.from(document.querySelectorAll('.kinds .menuezeile')).map(rect),
})
const reset = () => {
  scenario.stand = null
  scenario.there = []
  downloads.warteschlange.splice(0)
  downloads.laufend = null
}
const running = (name) => ({ datei: name, fertig: false, fehler: null, geladen: 5.8e9, gesamt: 13.8e9, anteil: 0.42 })
const name = (b) => b.ziel ?? b.datei

// A short sentence and a very long one, over the first two cards.
const catalogue = window.__texte.katalog.katalog
catalogue.satz_occamy = 'Short.'
catalogue.satz_gptoss = 'A very long sentence about a model that goes on and on, with many words that cannot all stand in two lines of a card of this width, and then some more words to be sure that it is cut. '.repeat(2)
await wait(300)

reset()
await poll()
report.idle = { cards: cards().map(measureCard), frame: frame() }

const builds = window.__cards('chat').map((c) => c.build)
scenario.stand = running(name(builds[0]))
window.__enqueue({ repo: builds[1].id, datei: builds[1].datei, ziel: builds[1].ziel ?? null })
scenario.there = [name(builds[2])]
await poll()
report.states = { cards: cards().map(measureCard), frame: frame() }

// A window taller than the page: its box ends at its content, not at the
// foot of the window.
document.getElementById('wurzel').style.height = '1800px'
document.getElementById('shell').style.height = '1800px'
await wait(500)
report.tall = frame()
document.getElementById('wurzel').style.height = '1064px'
document.getElementById('shell').style.height = '1064px'
await wait(300)

// The page scrolled to its end, in a window too low for it: the rows of the
// kinds stand in view.
document.getElementById('wurzel').style.height = '520px'
document.getElementById('shell').style.height = '520px'
await wait(500)
const scroller = document.querySelector('.inhalt')
scroller.scrollTop = scroller.scrollHeight
await wait(400)
report.scrolled = {
  top: scroller.scrollTop, height: scroller.scrollHeight, view: scroller.clientHeight,
  scroller: rect(scroller), rows: Array.from(document.querySelectorAll('.kinds .menuezeile')).map(rect),
}
scroller.scrollTop = 0
document.getElementById('wurzel').style.height = '1064px'
document.getElementById('shell').style.height = '1064px'
await wait(300)

// Every model page: its cards, one by one, as high as each other.
report.tabs = {}
for (const label of ['Chat', 'Einbettung', 'Sprache', 'Bild', 'Video']) {
  const row = Array.from(document.querySelectorAll('.kinds .menuezeile')).find((b) => new RegExp('^' + label + '\\b').test(b.textContent.trim()))
  if (!row) throw new Error('no tab ' + label)
  row.click()
  await wait(700)
  report.tabs[label] = cards().map((node) => Math.round(node.getBoundingClientRect().height * 100) / 100)
}

// The accessories stand as before: a card of that page beside its kind.
Array.from(document.querySelectorAll('.kinds .menuezeile')).find((b) => /Zubehör/.test(b.textContent)).click()
await wait(600)
report.accessories = Array.from(document.querySelectorAll('.spaltenraster .karte')).map((node) => ({
  rect: rect(node), nameSize: getComputedStyle(node.querySelector('.zname')).fontSize,
  makerSize: getComputedStyle(node.querySelector('.von')).fontSize, hasRoom: Boolean(node.querySelector('.load-room')),
  foot: Array.from(node.querySelectorAll('.fuss > *')).map(rect),
}))
report.columns = getComputedStyle(document.querySelector('.spaltenraster')).gridTemplateColumns.split(' ').length
report.gallery = rect(document.querySelector('.galerie'))
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: @@AREA@@px; height: 1064px; position: relative; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      @@CASES@@
    } catch (failure) {
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure) })
    }
  })
</script>
</body></html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 180.0) -> dict:
    """Read the page's report over the debug port."""
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
    async with websockets.connect(address, max_size=32 * 1024 * 1024) as connection:
        number = 0

        async def value_of(expression: str):
            nonlocal number
            number += 1
            await connection.send(
                json.dumps({"id": number, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True}})
            )
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response.get("result", {}).get("result", {}).get("value")

        raw = ""
        while time.monotonic() < end and not raw:
            raw = await value_of("document.getElementById('ergebnis')?.textContent || ''")
            if not raw:
                await asyncio.sleep(0.5)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


def _run_case(window_width: int = 1611, area_width: int = 1611) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-card-room-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL.replace("@@KATALOG@@", "../../src/teile/Katalog.svelte").replace("@@AREA@@", str(area_width)),
            encoding="utf-8")
        entry = (
            ENTRY_JS.replace("@@GLOBAL@@", "../../src/stil/global.css")
            .replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
            .replace("@@TEXTE@@", "../../src/lib/texte.svelte.js")
            .replace("@@DOWNLOADS@@", "../../src/lib/downloads.svelte.js")
            .replace("@@RECOMMENDATIONS@@", "../../src/lib/modellempfehlungen.js")
        )
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(
            PAGE.replace("@@CASES@@", CASES).replace("@@AREA@@", str(area_width)), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                f"--window-size={window_width},1064",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return asyncio.run(_drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def measured() -> dict:
    return _run_case()


@pytest.fixture(scope="module")
def narrow() -> dict:
    return _run_case(window_width=860)


@pytest.fixture(scope="module")
def wide() -> dict:
    # A 2560 px window: the area right of the sidebar, a gallery of 1858 px.
    return _run_case(window_width=2560, area_width=2230)


# Page areas whose gallery is 600 px and 1100 px wide (the kinds, the gaps and
# the padding of the page take 372 px); the old limits made columns of 192 px
# and 210 px there, narrower than the foot of a card.
@pytest.fixture(scope="module", params=(972, 1472), ids=("gallery-600", "gallery-1100"))
def between(request) -> dict:
    return _run_case(area_width=request.param)


def _gap(upper: dict, lower: dict) -> float:
    return lower["y"] - upper["bottom"]


def test_the_loading_card_keeps_its_facts_with_the_text_it_has_at_rest(measured):
    idle, states = measured["idle"]["cards"], measured["states"]["cards"]
    assert states[0]["facts"] and states[0]["facts"] == idle[0]["facts"]


def test_the_loading_row_stands_10_px_under_the_foot(measured):
    loading = measured["states"]["cards"][0]
    assert abs(_gap(loading["foot"], loading["row"]) - 10) <= 1, loading


def test_the_loading_row_ends_where_the_foot_of_a_card_at_rest_ends(measured):
    loading, waiting, done = measured["states"]["cards"][:3]
    # The cards of one row, one box: their lower edges are one line.
    assert abs(loading["rect"]["bottom"] - done["rect"]["bottom"]) <= 1
    assert abs(loading["row"]["bottom"] - done["foot"]["bottom"]) <= 1, (loading["row"], done["foot"])
    assert abs(loading["row"]["bottom"] - waiting["foot"]["bottom"]) <= 1


def test_the_room_a_card_keeps_is_as_high_as_the_loading_row(measured):
    loading, waiting = measured["states"]["cards"][:2]
    assert waiting["room"] and abs(waiting["room"]["height"] - loading["row"]["height"]) <= 1


def test_the_line_stands_where_it_stood_at_rest_or_one_row_higher_while_it_loads(measured):
    loading, waiting = measured["states"]["cards"][:2]
    # Line and facts move up by the room and the gap when the row takes it.
    rise = (waiting["foot"]["y"] - loading["foot"]["y"])
    assert abs(rise - (waiting["room"]["height"] + 10)) <= 1, rise


def test_all_cards_are_one_height_at_rest_and_while_one_loads_one_waits_and_one_is_downloaded(measured):
    for phase in ("idle", "states"):
        heights = {round(card["rect"]["height"]) for card in measured[phase]["cards"]}
        assert len(heights) == 1, (phase, heights)
    before = measured["idle"]["cards"][0]["rect"]["height"]
    assert abs(measured["states"]["cards"][0]["rect"]["height"] - before) <= 1


def test_the_cards_of_every_model_page_are_one_height_whether_or_not_they_have_a_sign(measured):
    """Chat has signs on most cards, the embedding and speech cards have none,
    and an image card may have no class: all ten of each page and all fifty
    cards together stand one height."""
    tabs = measured["tabs"]
    assert set(tabs) == {"Chat", "Einbettung", "Sprache", "Bild", "Video"}
    for label, heights in tabs.items():
        assert len(heights) == 10, (label, len(heights))
    assert len({height for heights in tabs.values() for height in heights}) == 1, tabs


def test_silence_in_a_quiet_catalogue_the_foot_of_each_card_stands_at_its_lower_edge_with_14_px(measured):
    for card in measured["idle"]["cards"]:
        assert card["padBottom"] == 14
        assert abs(card["rect"]["bottom"] - card["foot"]["bottom"] - 15) <= 1, card["rect"]


def test_a_sentence_stands_in_two_lines_whether_it_is_short_or_long(measured):
    short, long = measured["idle"]["cards"][:2]
    assert abs(short["rect"]["height"] - long["rect"]["height"]) <= 1
    assert abs(short["sentence"]["height"] - long["sentence"]["height"]) <= 1
    for card in measured["idle"]["cards"]:
        assert card["sentence"]["height"] <= 2 * 18.85 + 1, card["sentenceText"]


def test_a_long_sentence_ends_with_an_ellipsis_and_the_whole_of_it_is_the_tooltip(measured):
    short, long = measured["idle"]["cards"][:2]
    assert long["clipped"] and not short["clipped"]
    assert long["sentenceTitle"].startswith("A very long sentence") and len(long["sentenceTitle"]) > 300
    assert short["sentenceTitle"] == "Short."


def test_the_card_wears_the_type_of_the_drawing(measured):
    card = measured["idle"]["cards"][0]
    assert (card["nameSize"], card["nameWeight"]) == ("16px", "600")
    assert card["makerSize"] == "12px"
    assert card["sentenceSize"] == "13px" and abs(float(card["sentenceLine"][:-2]) - 13 * 1.45) <= 0.1
    assert (card["factsSize"], card["factsWeight"]) == ("12px", "400")


def test_the_box_of_the_cards_ends_24_px_under_its_last_row_not_at_the_foot_of_the_window(measured):
    frame = measured["idle"]["frame"]
    assert abs(frame["page"]["bottom"] - frame["grid"]["bottom"] - 24) <= 1, frame
    # Measured in a window taller than the page: ten cards fill the low one.
    tall = measured["tall"]
    assert tall["shell"]["bottom"] - tall["page"]["bottom"] > 100, tall


def test_the_column_of_the_kinds_ends_on_the_line_of_the_box_beside_it(measured):
    for phase in ("idle", "states"):
        frame = measured[phase]["frame"]
        assert abs(frame["kinds"]["bottom"] - frame["page"]["bottom"]) <= 1, frame
        assert abs(frame["kinds"]["y"] - frame["page"]["y"]) <= 1, frame
    frame = measured["idle"]["frame"]
    assert abs(frame["page"]["x"] - frame["kinds"]["right"] - 24) <= 1, frame


def test_the_rows_of_the_kinds_stay_in_view_when_the_page_is_scrolled(measured):
    scrolled = measured["scrolled"]
    assert scrolled["top"] > 50, scrolled
    view = scrolled["scroller"]
    assert len(scrolled["rows"]) >= 6, scrolled
    for row in scrolled["rows"]:
        assert row["y"] >= view["y"] - 1 and row["bottom"] <= view["bottom"] + 1, (row, view)


def test_silence_the_accessories_keep_their_cards_and_have_no_room_for_a_loading_row(measured):
    assert measured["accessories"], "no accessory card was measured"
    for card in measured["accessories"]:
        assert not card["hasRoom"]
        assert (card["nameSize"], card["makerSize"]) == ("12.5px", "11.5px")


def test_silence_the_narrow_view_puts_the_kinds_over_the_cards(narrow):
    frame = narrow["idle"]["frame"]
    assert frame["kinds"]["bottom"] <= frame["page"]["y"] + 1, frame


def _outside(measure: dict) -> list:
    """Footer parts that stand outside their card."""
    found = []
    for card in measure["accessories"]:
        box = card["rect"]
        for part in card["foot"]:
            if part["x"] < box["x"] - 0.5 or part["right"] > box["right"] + 0.5:
                found.append((part, box))
    return found


def test_the_footer_of_every_accessory_card_stands_inside_its_card(measured, narrow, between):
    for measure in (measured, narrow, between):
        assert measure["accessories"], "no accessory card was measured"
        assert not _outside(measure), (measure["columns"], measure["gallery"], _outside(measure)[:2])


def test_every_accessory_column_is_as_wide_as_the_widest_footer(measured, between):
    # 224 px: the pill "Vision (mmproj)", the largest size and the sign, with the card's padding.
    for measure in (measured, between):
        for card in measure["accessories"]:
            assert card["rect"]["width"] >= 224, (measure["columns"], measure["gallery"], card["rect"])


def _cards_per_row(measure: dict) -> list[int]:
    rows: dict[int, int] = {}
    for card in measure["idle"]["cards"]:
        top = round(card["rect"]["y"])
        rows[top] = rows.get(top, 0) + 1
    return [rows[top] for top in sorted(rows)]


def test_five_cards_and_five_accessory_columns_on_a_wide_page(wide):
    """The page has no limit on its width, so a gallery of 1858 px holds the
    ten cards of a model page in two rows of five, and the accessories in
    five columns."""
    assert _cards_per_row(wide) == [5, 5]
    assert wide["columns"] == 5


def test_silence_a_gallery_under_1306_px_keeps_three_cards_to_a_row(measured):
    """The area of 1611 px leaves a gallery of 1239 px: not wide enough for
    five cards of 250 px, so the rows stay what they were."""
    assert _cards_per_row(measured) == [3, 3, 3, 1]
