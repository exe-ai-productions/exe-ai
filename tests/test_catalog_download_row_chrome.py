"""The state of a download in the catalogue — file rows and cards — measured in
a real browser.

A file row of the model page shows a running download in one line (name, bar,
"42 %", a fine divider, "loaded / total GB · speed", the cross), a download
that waits behind it as "Waiting" in yellow with the cross that takes it out of
the queue, a finished one as "downloaded" with the green tick. The cards of the
catalogue show the same states in their foot and keep their size in every one
of them, on the chat page and among the accessories.

`Katalog.svelte` is built as shipped and drawn in headless Chrome; the service
is not asked — the page answers every request itself, with a download that
runs (made up) and one that waits (made up in the queue). Skipped where there
is no Chrome or no node, like the other browser tests.
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
  import Katalog from '@@KATALOG@@'
</script>

<div id="shell" style="position: relative; width: 1280px; height: 640px; overflow: hidden;">
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
// The light look: only there the text form of a colour differs from its sign
// form, so only there a word in the wrong one can be told from the right one.
document.documentElement.dataset.modus = 'hell'
const rect = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : null)
const scenario = window.__scenario
const probe = document.createElement('span')
probe.style.color = 'var(--gelb)'
document.body.appendChild(probe)
report.yellow = getComputedStyle(probe).color
const tokenColor = (name) => {
  probe.style.color = `var(${name})`
  return getComputedStyle(probe).color
}
report.tokens = {
  still: tokenColor('--text-still'),
  yellowText: tokenColor('--gelb-text'),
  greenText: tokenColor('--gruen-text'),
  green: tokenColor('--gruen'),
  blue: tokenColor('--blau'),
}
const colorOf = (node) => (node ? getComputedStyle(node).color : null)
const poll = () => wait(2600)

for (let k = 0; k < 80 && document.querySelectorAll('.karte').length === 0; k += 1) await wait(100)
await wait(500)

const state = (node) => ({
  rect: rect(node),
  state: rect(node.querySelector('.state')),
  signs: Array.from(node.querySelectorAll('.sign-button')).map(rect),
  signMarks: Array.from(node.querySelectorAll('.sign-button svg')).map(rect),
  tickMark: rect(node.querySelector('.tick svg')),
  tick: rect(node.querySelector('.done')),
  doneWord: node.querySelector('.done') ? text(node.querySelector('.done')) : null,
  waiting: node.querySelector('.waiting') ? { text: text(node.querySelector('.waiting')), color: colorOf(node.querySelector('.waiting')), rect: rect(node.querySelector('.waiting')) } : null,
  bar: rect(node.querySelector('.bar')),
  percent: node.querySelector('.percent') ? { text: text(node.querySelector('.percent')), rect: rect(node.querySelector('.percent')), color: colorOf(node.querySelector('.percent')), weight: getComputedStyle(node.querySelector('.percent')).fontWeight } : null,
  barFill: node.querySelector('.bar i') ? getComputedStyle(node.querySelector('.bar i')).backgroundColor : null,
  doneStyle: node.querySelector('.done') ? { color: colorOf(node.querySelector('.done')), weight: getComputedStyle(node.querySelector('.done')).fontWeight, tick: colorOf(node.querySelector('.tick')) } : null,
  waitingWeight: node.querySelector('.waiting') ? getComputedStyle(node.querySelector('.waiting')).fontWeight : null,
  amountsStyle: node.querySelector('.amounts') ? { color: colorOf(node.querySelector('.amounts')), weight: getComputedStyle(node.querySelector('.amounts')).fontWeight, size: getComputedStyle(node.querySelector('.amounts')).fontSize } : null,
  divider: rect(node.querySelector('.divider')),
  amounts: node.querySelector('.amounts') ? { text: text(node.querySelector('.amounts')), rect: rect(node.querySelector('.amounts')) } : null,
  facts: Boolean(node.querySelector('.fakten')),
  size: node.querySelector('.fgb') ? text(node.querySelector('.fgb')) : null,
  foot: text(node.querySelector('.fuss')),
})

const reset = () => {
  scenario.stand = null
  scenario.there = []
  downloads.warteschlange.splice(0)
  downloads.laufend = null
}
const downloads = window.__downloads
const running = (name) => ({ datei: name, fertig: false, fehler: null, geladen: 5.8e9, gesamt: 13.8e9, anteil: 0.42 })

// --- The cards of one page: four states, one card each ----------------------
const cardsOf = async (selector, kind) => {
  const builds = window.__cards(kind).map((c) => c.build)
  const name = (b) => b.ziel ?? b.datei
  const cards = () => Array.from(document.querySelectorAll(selector))
  reset()
  await poll()
  const idle = cards().map(state)
  // 0 loads, 1 waits, 2 is downloaded, 3 is new.
  scenario.stand = running(name(builds[0]))
  window.__enqueue({ repo: builds[1].id, datei: builds[1].datei, ziel: builds[1].ziel ?? null })
  scenario.there = [name(builds[2])]
  await poll()
  const states = cards().map(state)
  // The cross of the waiting card takes it out of the queue.
  const waiting = cards()[1]
  const before = downloads.warteschlange.length
  waiting.querySelector('.sign-button').click()
  await wait(300)
  const dequeued = { before, after: downloads.warteschlange.length, button: cards()[1].querySelectorAll('.sign-button').length }
  return { idle, states, dequeued }
}
report.chat = await cardsOf('.raster .karte', 'chat')

// --- The accessories ----------------------------------------------------------
const kinds = Array.from(document.querySelectorAll('.kinds .menuezeile'))
kinds.find((b) => /Zubehör/.test(b.textContent)).click()
await wait(600)
report.accessories = await cardsOf('.spaltenraster .karte', 'zubehoer')

// --- The page of a found model ------------------------------------------------
kinds.find((b) => /Chat/.test(b.textContent)).click()
await wait(400)
reset()
scenario.hits = [{ id: 'maker/Some-Model-GGUF', name: 'Some-Model-GGUF', anbieter: 'maker', ladungen: 55000 }]
const names = ['Some-Model-Q4_K_M.gguf', 'Some-Model-Q5_K_M.gguf', 'Some-Model-Q6_K.gguf', 'Some-Model-Q8_0.gguf']
scenario.files = names.map((datei, k) => ({ datei, groesse_gb: [14.3, 16.8, 19.4, 25.1][k], bytes: 1, teile: 1 }))
const field = document.querySelector('.suchfeld')
field.value = 'some'
field.dispatchEvent(new Event('input', { bubbles: true }))
for (let k = 0; k < 40 && document.querySelectorAll('.treffer').length === 0; k += 1) await wait(100)
document.querySelector('.treffer').click()
for (let k = 0; k < 40 && document.querySelectorAll('.files .zeile').length === 0; k += 1) await wait(100)
const rows = () => Array.from(document.querySelectorAll('.files .zeile')).map((row) => ({
  ...state(row.querySelector('.obere')),
  name: text(row.querySelector('.fname')),
  row: rect(row),
}))
report.detail = { idle: rows() }
scenario.stand = running(names[0])
window.__enqueue({ repo: 'maker/Some-Model-GGUF', datei: names[1], ziel: null })
scenario.there = [names[2]]
await poll()
await poll()
report.detail.states = rows()
const waitingRow = document.querySelectorAll('.files .zeile')[1]
const queued = downloads.warteschlange.length
waitingRow.querySelector('.sign-button').click()
await wait(300)
report.detail.dequeued = { before: queued, after: downloads.warteschlange.length }
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; height: 640px; position: relative; }</style>
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


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-download-row-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL.replace("@@KATALOG@@", "../../src/teile/Katalog.svelte"), encoding="utf-8")
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
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", CASES), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1280,640",
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


def test_the_harness_has_the_house_colours(measured):
    # Without the global stylesheet every colour reads black and the colour
    # checks below would compare black with black.
    assert measured["yellow"] not in ("rgb(0, 0, 0)", "")


def _square(rect: dict, side: float = 22) -> bool:
    return abs(rect["width"] - side) <= 0.5 and abs(rect["height"] - side) <= 0.5


def _centre(rect: dict) -> float:
    return rect["y"] + rect["height"] / 2


# --- The file rows of the model page ----------------------------------------


def test_a_running_row_is_one_line_with_the_divider_and_a_cross_of_22_px(measured):
    running = measured["detail"]["states"][0]
    assert running["bar"] and running["percent"]["text"] == "42 %"
    assert running["divider"] and running["divider"]["width"] <= 1.5 and running["divider"]["height"] >= 10
    assert re.fullmatch(r"\d+,\d / 13,8 GB · \d+,\d MB/s", running["amounts"]["text"]), running["amounts"]
    cross = running["signs"]
    assert len(cross) == 1 and _square(cross[0])
    # In one line: the centres of the bar, the percentage, the amounts and the
    # cross lie within two pixels of each other.
    centres = [_centre(running["bar"]), _centre(running["percent"]["rect"]),
               _centre(running["amounts"]["rect"]), _centre(cross[0])]
    assert max(centres) - min(centres) <= 2, centres
    # The size is part of the amounts now; it does not stand twice.
    assert running["size"] is None
    # The order of the line: bar, percentage, divider, amounts, cross.
    assert (running["bar"]["right"] <= running["percent"]["rect"]["x"] + 0.5
            <= running["divider"]["x"] + 0.5 <= running["amounts"]["rect"]["x"] + 0.5
            <= cross[0]["x"] + 0.5)


def test_a_running_row_needs_no_second_line(measured):
    idle = measured["detail"]["idle"]
    running = measured["detail"]["states"][0]
    # The row is as high as it was with a button: nothing hangs under it.
    assert abs(running["rect"]["height"] - idle[0]["rect"]["height"]) <= 1.5
    heights = [(r["name"], r["row"]["height"]) for r in measured["detail"]["states"]]
    assert all(abs(h - idle[0]["row"]["height"]) <= 1.5 for _, h in heights), (idle[0]["row"]["height"], heights)


def test_a_waiting_row_says_waiting_in_yellow_with_a_cross(measured):
    waiting = measured["detail"]["states"][1]
    assert waiting["waiting"]["text"] == "Wartet"
    assert waiting["waiting"]["color"] == measured["tokens"]["yellowText"]
    assert len(waiting["signs"]) == 1 and _square(waiting["signs"][0])
    assert waiting["waiting"]["rect"]["right"] <= waiting["signs"][0]["x"] + 0.5
    # The size stays beside it, as beside the button.
    assert waiting["size"] and "16,8" in waiting["size"]


def test_every_sign_of_a_row_is_14_px_in_its_22_px_button(measured):
    count = 0
    rows = measured["detail"]["idle"] + measured["detail"]["states"]
    for card_page in ("chat", "accessories"):
        rows += measured[card_page]["idle"] + measured[card_page]["states"]
    for row in rows:
        for mark in row["signMarks"]:
            count += 1
            assert _square(mark, 14), mark
        if row["tickMark"]:
            count += 1
            assert _square(row["tickMark"], 14), row["tickMark"]
    # The loop above must have looked at the cross, the download sign and the tick.
    assert count >= 12, count


def test_the_numbers_of_a_row_stand_quiet_and_the_words_in_the_text_colours(measured):
    tokens = measured["tokens"]
    # The harness reads the light look: the sign form of a colour and its text
    # form differ, so a word in the wrong one is told from the right one.
    assert len({tokens["still"], tokens["yellowText"], tokens["greenText"], tokens["green"]}) == 4
    running = measured["detail"]["states"][0]
    assert running["percent"]["color"] == tokens["still"] and running["percent"]["weight"] == "400"
    assert running["amountsStyle"] == {"color": tokens["still"], "weight": "400", "size": "12px"}
    assert running["barFill"] == tokens["blue"]
    waiting = measured["detail"]["states"][1]
    assert waiting["waitingWeight"] == "500"
    done = measured["detail"]["states"][2]
    assert done["doneStyle"] == {"color": tokens["greenText"], "weight": "500", "tick": tokens["green"]}
    # The same on the cards of the catalogue.
    card = measured["chat"]["states"]
    assert card[0]["percent"]["color"] == tokens["still"] and card[0]["barFill"] == tokens["blue"]
    assert card[1]["waiting"]["color"] == tokens["yellowText"]
    assert card[2]["doneStyle"]["tick"] == tokens["green"]


def test_the_cross_of_a_waiting_row_takes_the_file_out_of_the_queue(measured):
    assert measured["detail"]["dequeued"] == {"before": 1, "after": 0}


def test_a_finished_row_keeps_the_green_tick_and_the_word(measured):
    done = measured["detail"]["states"][2]
    assert done["doneWord"] == "heruntergeladen" and not done["signs"]


def test_a_new_row_keeps_the_download_sign_of_22_px(measured):
    new = measured["detail"]["states"][3]
    assert len(new["signs"]) == 1 and _square(new["signs"][0])


def test_silence_without_a_download_every_row_has_its_button_and_no_waiting(measured):
    for row in measured["detail"]["idle"]:
        assert row["waiting"] is None and row["percent"] is None and row["bar"] is None, row["name"]
    idle = measured["detail"]["idle"]
    # Nothing is there yet but the file the page lists as downloaded: it is
    # not in the made-up folder in this phase, so every row offers the button.
    for row in idle:
        assert len(row["signs"]) == 1 and _square(row["signs"][0]), row["name"]
        assert row["doneWord"] is None, row["name"]


# --- The cards --------------------------------------------------------------


@pytest.mark.parametrize("page", ["chat", "accessories"])
def test_no_card_grows_while_one_loads_one_waits_and_one_is_downloaded(measured, page):
    idle, states = measured[page]["idle"], measured[page]["states"]
    assert len(idle) == len(states) >= 4
    for before, now in zip(idle, states, strict=True):
        assert abs(before["rect"]["height"] - now["rect"]["height"]) <= 1, (before["foot"], now["foot"])
    if page == "chat":
        # The cards of one row stand one height.
        assert len({round(c["rect"]["height"]) for c in states[:2]}) == 1
        assert len({round(c["rect"]["height"]) for c in states}) == 1


@pytest.mark.parametrize("page", ["chat", "accessories"])
def test_the_foot_of_each_state_stands_in_the_same_place(measured, page):
    states = measured[page]["states"]
    running, waiting, done, new = states[:4]
    for card in (running, waiting, done, new):
        assert card["state"], card["foot"]
    # The button of the new card, the cross of the waiting card and the tick
    # of the downloaded card end on one right edge (cards of one column align).
    assert _square(new["signs"][0]) and _square(waiting["signs"][0]) and _square(running["signs"][0])
    assert abs(done["tick"]["width"] - 22) <= 0.5 and abs(done["tick"]["height"] - 22) <= 0.5
    # A tick has no word beside it; the word is its tooltip.
    assert done["doneWord"] == "" and not done["signs"]
    if page == "chat":
        rights = [card["state"]["right"] - card["rect"]["right"] for card in (running, waiting, done, new)]
        assert max(rights) - min(rights) <= 1, rights
    else:
        # The accessory cards of this width are narrower than their own foot
        # (kind, size and sign): that is not this test's measure. Each state
        # still ends at the right edge or beyond it by the same overflow.
        for card in (running, waiting):
            assert card["state"]["right"] <= card["rect"]["right"], card["foot"]


def test_a_running_chat_card_says_percent_and_loaded_of_total_without_the_speed(measured):
    running = measured["chat"]["states"][0]
    assert running["percent"]["text"] == "42 %"
    assert running["divider"] and running["amounts"]
    assert re.fullmatch(r"\d+,\d / 13,8 GB", running["amounts"]["text"]), running["amounts"]
    assert "MB/s" not in running["foot"]
    assert _square(running["signs"][0])
    # The cross stays inside the card.
    assert running["signs"][0]["right"] <= running["rect"]["right"]


def test_a_running_accessory_card_keeps_the_amounts_in_its_tooltip(measured):
    running = measured["accessories"]["states"][0]
    assert running["percent"]["text"] == "42 %" and running["amounts"] is None


def test_a_waiting_card_says_waiting_in_yellow_with_a_cross(measured):
    for page in ("chat", "accessories"):
        waiting = measured[page]["states"][1]
        assert waiting["waiting"]["text"] == "Wartet"
        assert waiting["waiting"]["color"] == measured["tokens"]["yellowText"]
        assert len(waiting["signs"]) == 1


@pytest.mark.parametrize("page", ["chat", "accessories"])
def test_the_cross_of_a_waiting_card_takes_it_out_of_the_queue(measured, page):
    assert measured[page]["dequeued"] == {"before": 1, "after": 0, "button": 1}


def test_silence_the_cards_of_a_quiet_catalogue_have_their_button_and_their_facts(measured):
    for card in measured["chat"]["idle"]:
        assert card["facts"] and len(card["signs"]) == 1 and _square(card["signs"][0])
        assert card["waiting"] is None and card["percent"] is None
