"""The page Downloads of the catalogue, measured in a real browser — with the
row of the Hugging Face token over its list (54 high, the field 220 wide at the
right end, the bin a button of 32) and the rows of a search in the catalogue
(56 high, the name 14 medium, maker and loads 12), which stand in the same file
and are measured in the second run of the harness.

Every entry is 72 high with two lines: the maker's logo (18 px, no dot), the
file name — cut with an ellipsis — and the small Hugging Face mark (14 px)
over the cross of the second line, in a column of 22 px. The second line
begins under the name and is the download row of the catalogue: bar,
percentage, divider, amounts and cross (22 px) while it runs; the size,
"Waiting" and the cross while it waits; the size and "downloaded" with the
green tick when it arrived. The card is as high as its entries; the empty one
is a card of its own with the sentence in its middle.

`Katalog.svelte` is built as shipped and drawn in headless Chrome with the
global stylesheet; the service is not asked — the page answers every request
itself (a download that runs, made up) and the queue and the receipts are made
up in the page. Skipped where there is no Chrome or no node, like the other
browser tests.
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

<div id="shell" style="position: relative; width: 1280px; height: 960px; overflow: hidden;">
  <Katalog offen={true} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '@@GLOBAL@@'
import german from '@@GERMAN@@'
import { texte } from '@@TEXTE@@'
import { downloads, einreihen, fertigMerken } from '@@DOWNLOADS@@'
import { katalogFuer, passendeFassung } from '@@RECOMMENDATIONS@@'

texte.katalog = german
texte.sprache = 'de'
const MEMORY = 64
const scenario = { stand: null, there: [], hits: [], files: [] }
window.__scenario = scenario
window.__downloads = downloads
window.__enqueue = einreihen
window.__done = fertigMerken
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
  if (path === '/models/token') return json(@@TOKEN@@)
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
const downloads = window.__downloads
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
const poll = () => wait(2600)

for (let k = 0; k < 80 && document.querySelectorAll('.karte').length === 0; k += 1) await wait(100)
await wait(500)
const kinds = Array.from(document.querySelectorAll('.kinds .menuezeile'))
kinds[kinds.length - 1].click()
await wait(600)
const empty = document.querySelector('.leer')
const sentence = document.createRange()
if (empty) sentence.selectNodeContents(empty)
report.idle = {
  text: text(document.querySelector('.page')),
  entries: document.querySelectorAll('.entry').length,
  card: rect(empty),
  sentence: empty ? rect(sentence) : null,
  shell: rect(document.getElementById('shell')),
}
const emptyRow = document.querySelector('.hf-zeile')
report.tokenEmpty = {
  row: rect(emptyRow),
  field: rect(emptyRow?.querySelector('.feld')),
  dot: rect(emptyRow?.querySelector('.scheibe')),
  fieldStyle: emptyRow ? { size: getComputedStyle(emptyRow.querySelector('.feld')).fontSize, weight: getComputedStyle(emptyRow.querySelector('.feld')).fontWeight } : null,
  button: rect(emptyRow?.querySelector('.knopf')),
  buttonText: text(emptyRow?.querySelector('.knopf')),
  note: rect(document.querySelector('.fussnote')),
}

const LONG = 'A-very-long-model-file-name-' + 'that-goes-on-and-on-'.repeat(12) + 'Q4_K_M.gguf'
const gpt = window.__cards('chat')[1].build
scenario.stand = { datei: gpt.datei, fertig: false, fehler: null, geladen: 5.8e9, gesamt: 13.8e9, anteil: 0.42 }
downloads.repos[gpt.datei] = 'SoAI/gpt-oss-20b-VISION-v2-GGUF'
window.__enqueue({ repo: 'unsloth/Some-Model-GGUF', datei: 'Some-Model-Q5_K_M.gguf', groesse: 16.8 })
window.__enqueue({ repo: 'maker/Long-GGUF', datei: LONG, groesse: 4.2 })
window.__enqueue({ datei: 'orphan-without-repo.gguf' })
const occamy = window.__cards('chat')[0].build
window.__done(occamy.datei, 14.8e9)
downloads.repos[occamy.datei] = 'IsValorum/Occamy-GGUF'
window.__done('home-made-file.gguf', 1.2e9)
await poll()

const entries = () => Array.from(document.querySelectorAll('.entry'))
const describe = (node) => {
  const mark = node.querySelector('.mark')
  const hf = node.querySelector('.hf svg')
  const cross = Array.from(node.querySelectorAll('.zeile .sign-button'))[0]
  const crossMark = node.querySelector('.zeile .sign-button svg')
  const name = node.querySelector('.datei')
  return {
    rect: rect(node),
    dots: node.querySelectorAll('.punkt').length,
    mark: rect(mark?.firstElementChild),
    markKind: mark?.querySelector('svg') ? 'svg' : mark?.querySelector('img') ? 'img' : 'letter',
    name: text(name),
    nameRect: rect(name),
    clipped: name.scrollWidth > name.clientWidth,
    overflow: getComputedStyle(name).textOverflow,
    hf: rect(hf),
    hfShown: Boolean(hf),
    cross: rect(cross),
    crossMark: rect(crossMark),
    line: rect(node.querySelector('.zeile')),
    bar: rect(node.querySelector('.bar')),
    percent: text(node.querySelector('.percent')),
    percentStyle: node.querySelector('.percent') ? { color: getComputedStyle(node.querySelector('.percent')).color, weight: getComputedStyle(node.querySelector('.percent')).fontWeight } : null,
    barFill: node.querySelector('.bar i') ? getComputedStyle(node.querySelector('.bar i')).backgroundColor : null,
    sizeStyle: node.querySelector('.size') ? { color: getComputedStyle(node.querySelector('.size')).color, weight: getComputedStyle(node.querySelector('.size')).fontWeight } : null,
    divider: rect(node.querySelector('.divider')),
    amounts: text(node.querySelector('.amounts')),
    size: text(node.querySelector('.size')),
    waiting: node.querySelector('.waiting') ? { text: text(node.querySelector('.waiting')), color: getComputedStyle(node.querySelector('.waiting')).color, weight: getComputedStyle(node.querySelector('.waiting')).fontWeight } : null,
    done: text(node.querySelector('.done')),
    doneStyle: node.querySelector('.done') ? { color: getComputedStyle(node.querySelector('.done')).color, weight: getComputedStyle(node.querySelector('.done')).fontWeight, tick: getComputedStyle(node.querySelector('.tick')).color } : null,
    tick: rect(node.querySelector('.tick')),
  }
}
report.entries = entries().map(describe)
report.page = rect(document.querySelector('.list'))
const waitingEntry = entries()[1]
const queued = downloads.warteschlange.length
waitingEntry?.querySelector('.sign-button')?.click()
await wait(300)
report.dequeued = { before: queued, after: downloads.warteschlange.length, entries: entries().length }
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

# The token set (a made-up answer) and three search hits (made up too).
TOKEN_CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const rect = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : null)
const style = (node) => {
  if (!node) return null
  const c = getComputedStyle(node)
  return { size: c.fontSize, weight: c.fontWeight, color: c.color }
}
const probe = document.createElement('span')
document.body.appendChild(probe)
const colourOf = (name) => {
  probe.style.color = `var(${name})`
  return getComputedStyle(probe).color
}
report.tokens = { text: colourOf('--text'), leise: colourOf('--text-leise'), still: colourOf('--text-still') }
for (let k = 0; k < 80 && document.querySelectorAll('.karte').length === 0; k += 1) await wait(100)
await wait(500)
const kinds = Array.from(document.querySelectorAll('.kinds .menuezeile'))
kinds[kinds.length - 1].click()
await wait(800)
const row = document.querySelector('.hf-zeile')
const field = row?.querySelector('.feld')
const button = row?.querySelector('.sign-button')
const buttonStyle = button && getComputedStyle(button)
report.token = {
  row: rect(row),
  logo: rect(row?.querySelector('.hf-marke')),
  name: rect(row?.querySelector('.hf-name')),
  nameStyle: style(row?.querySelector('.hf-name')),
  dot: rect(row?.querySelector('.scheibe')),
  field: rect(field),
  fieldText: text(field),
  fieldStyle: style(field),
  button: rect(button),
  buttonGround: buttonStyle ? buttonStyle.backgroundColor : null,
  buttonLine: buttonStyle ? buttonStyle.boxShadow : null,
  buttonRadius: buttonStyle ? buttonStyle.borderTopLeftRadius : null,
  buttonLabel: button?.getAttribute('title') || null,
  sign: rect(button?.querySelector('svg')),
  inputs: row?.querySelectorAll('input').length,
  note: Boolean(document.querySelector('.fussnote')),
}
kinds[0].click()
await wait(600)
const box = document.querySelector('.suchfeld')
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
window.__scenario.hits = [
  { id: 'liquid/LFM2.5-24B-A2B-GGUF', name: 'LFM2.5-24B-A2B-GGUF', anbieter: 'LiquidAI', ladungen: 121000 },
  { id: 'unsloth/Some-Model-GGUF', name: 'Some-Model-GGUF', anbieter: 'unsloth', ladungen: 48000 },
  { id: 'maker/Third-GGUF', name: 'Third-GGUF', anbieter: 'maker', ladungen: 9300 },
]
setter.call(box, 'gguf')
box.dispatchEvent(new Event('input', { bubbles: true }))
await wait(1500)
const hits = Array.from(document.querySelectorAll('.treffer'))
report.hits = hits.map((hit) => ({
  rect: rect(hit),
  mark: rect(hit.querySelector('.twer')?.previousElementSibling),
  who: rect(hit.querySelector('.twer')),
  name: text(hit.querySelector('.tname')),
  nameStyle: style(hit.querySelector('.tname')),
  nameRect: rect(hit.querySelector('.tname')),
  under: rect(hit.querySelector('.tunter')),
  underStyle: style(hit.querySelector('.tunter')),
  count: text(hit.querySelector('.tzieh')),
  countStyle: style(hit.querySelector('.tzieh')),
  countRect: rect(hit.querySelector('.tzieh')),
  arrow: rect(hit.querySelector('.tpfeil')),
}))
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; height: 960px; position: relative; }</style>
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


def _run_case(cases: str = CASES, token: str = "{ gesetzt: false }") -> dict:
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
            .replace("@@TOKEN@@", token)
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
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", cases), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1280,960",
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
def with_token() -> dict:
    return _run_case(TOKEN_CASES, "{ gesetzt: true, ende: 'a1b2' }")


def test_the_harness_has_the_house_colours(measured):
    # Without the global stylesheet every colour reads black and the colour
    # checks below would compare black with black.
    assert measured["yellow"] not in ("rgb(0, 0, 0)", "")


def _square(rect: dict, side: float = 22) -> bool:
    return abs(rect["width"] - side) <= 0.5 and abs(rect["height"] - side) <= 0.5


def _centre_x(rect: dict) -> float:
    return rect["x"] + rect["width"] / 2


def _centre_y(rect: dict) -> float:
    return rect["y"] + rect["height"] / 2


# --- The entries ---------------------------------------------------------------


def test_every_entry_is_72_high_finished_ones_too(measured):
    assert len(measured["entries"]) == 6
    for entry in measured["entries"]:
        assert abs(entry["rect"]["height"] - 72) <= 0.5, entry["name"]
        assert abs(entry["line"]["height"] - 22) <= 0.5, entry["name"]


def test_the_card_is_as_high_as_its_entries_and_ends_4_px_below_the_last(measured):
    last = measured["entries"][-1]["rect"]
    assert abs(measured["page"]["bottom"] - last["bottom"] - 4) <= 1, (measured["page"], last)
    first = measured["entries"][0]["rect"]
    assert abs(first["y"] - measured["page"]["y"] - 4) <= 1, (measured["page"], first)
    assert abs(measured["page"]["height"] - (6 * 72 + 8)) <= 1


def test_a_mark_of_18_px_stands_before_the_name_and_no_dot(measured):
    assert len(measured["entries"]) == 6
    for entry in measured["entries"]:
        assert entry["dots"] == 0, entry["name"]
        assert entry["mark"] and _square(entry["mark"], 18), (entry["name"], entry["mark"])
        assert entry["mark"]["right"] <= entry["nameRect"]["x"] + 0.5


def test_the_maker_logo_is_the_one_of_the_catalogue_card(measured):
    # The running file and the finished catalogue file wear a drawn logo; the
    # made-up file and the file of an unknown owner wear a letter.
    kinds = [entry["markKind"] for entry in measured["entries"]]
    assert kinds[0] == "svg" and kinds[4] == "svg"
    assert kinds[3] == "letter" and kinds[5] == "letter"


def test_the_hugging_face_mark_is_14_px_over_the_centre_of_the_cross(measured):
    assert len(measured["entries"]) == 6
    for entry in measured["entries"][:2]:
        assert entry["hf"] and _square(entry["hf"], 14), entry["name"]
        assert entry["cross"] and _square(entry["cross"]), entry["name"]
        assert abs(_centre_x(entry["hf"]) - _centre_x(entry["cross"])) <= 1, entry["name"]
    # Small in the corner: 14 px from the top edge and from the right edge.
    shown = [entry for entry in measured["entries"] if entry["hfShown"]]
    assert len(shown) == 4
    for entry in shown:
        above = entry["hf"]["y"] - entry["rect"]["y"]
        beside = entry["rect"]["right"] - entry["hf"]["right"]
        assert abs(above - 14) <= 1 and abs(beside - 14) <= 1, (entry["name"], above, beside)


def test_the_name_ends_with_an_ellipsis_before_the_hugging_face_mark(measured):
    long = measured["entries"][2]
    assert long["clipped"] and long["overflow"] == "ellipsis"
    assert long["nameRect"]["right"] <= long["hf"]["x"] + 0.5


def test_a_running_entry_is_one_line_of_the_download_row_with_a_cross_of_22_px(measured):
    running = measured["entries"][0]
    assert running["percent"] == "42 %" and running["divider"]
    assert re.fullmatch(r"\d+,\d / 13,8 GB( · \d+,\d MB/s)?", running["amounts"]), running["amounts"]
    assert running["cross"] and _square(running["cross"])
    # The cross stands in the column of the Hugging Face mark above it, and
    # the line ends where the first line ends.
    assert abs(running["cross"]["right"] - (running["hf"]["right"] + 4)) <= 1
    assert running["bar"]["right"] <= running["cross"]["x"]
    # The sign inside the cross is 14 px, in the middle of the button.
    assert running["crossMark"] and _square(running["crossMark"], 14)
    assert abs(_centre_x(running["crossMark"]) - _centre_x(running["cross"])) <= 0.5


def test_the_bar_begins_flush_with_the_name_not_under_the_logo(measured):
    running = measured["entries"][0]
    assert abs(running["bar"]["x"] - running["nameRect"]["x"]) <= 1, (running["bar"], running["nameRect"])
    assert running["bar"]["x"] >= running["mark"]["right"] + 8


def test_a_waiting_entry_says_its_size_and_waiting_in_yellow_with_a_cross(measured):
    waiting = measured["entries"][1]
    assert waiting["size"] == "16,8 GB"
    assert waiting["waiting"]["text"] == "Wartet"
    assert waiting["cross"] and _square(waiting["cross"])


def test_the_words_of_the_states_stand_in_the_text_colours_and_the_numbers_quiet(measured):
    tokens = measured["tokens"]
    # The harness reads the house colours: the three text colours differ.
    assert len({tokens["still"], tokens["yellowText"], tokens["greenText"], tokens["green"]}) == 4
    running, waiting, done = measured["entries"][0], measured["entries"][1], measured["entries"][4]
    assert running["percentStyle"] == {"color": tokens["still"], "weight": "400"}
    assert running["barFill"] == tokens["blue"]
    assert waiting["waiting"]["color"] == tokens["yellowText"] and waiting["waiting"]["weight"] == "500"
    assert waiting["sizeStyle"] == {"color": tokens["still"], "weight": "400"}
    assert done["doneStyle"] == {"color": tokens["greenText"], "weight": "500", "tick": tokens["green"]}
    assert done["sizeStyle"] == {"color": tokens["still"], "weight": "400"}


def test_the_cross_of_a_waiting_entry_takes_it_out_of_the_queue(measured):
    assert measured["dequeued"] == {"before": 3, "after": 2, "entries": 5}


def test_a_finished_entry_says_its_size_and_downloaded_with_the_tick(measured):
    done = measured["entries"][4]
    assert done["size"] == "14,8 GB" and done["done"] == "heruntergeladen"
    assert done["tick"] and done["cross"] is None


def test_silence_without_a_download_the_page_says_so_and_has_no_entry(measured):
    assert measured["idle"]["entries"] == 0
    assert "Kein aktiver Download" in measured["idle"]["text"]


def test_the_empty_list_is_a_card_with_its_sentence_in_the_middle(measured):
    idle = measured["idle"]
    card, sentence = idle["card"], idle["sentence"]
    assert card and sentence, idle
    assert abs(card["height"] - 50) <= 1, card
    assert abs(_centre_x(card) - _centre_x(sentence)) <= 1, (card, sentence)
    assert abs(_centre_y(card) - _centre_y(sentence)) <= 1, (card, sentence)
    # It does not reach down to the edge of the window.
    assert idle["shell"]["bottom"] - card["bottom"] > 100, (card, idle["shell"])


def test_silence_an_entry_without_a_known_repository_has_no_hugging_face_mark(measured):
    orphan = next(e for e in measured["entries"] if e["name"].startswith("orphan"))
    assert not orphan["hfShown"] and orphan["size"] is None and orphan["waiting"]
    home = next(e for e in measured["entries"] if e["name"].startswith("home-made"))
    assert not home["hfShown"]


def test_every_job_of_the_catalogue_carries_the_size_of_its_file():
    # The page shows the size of a waiting file from its job; the catalogue
    # hands it over where it queues a model, a found file, its projector and
    # the parts of a kit. (Read off the source: the page is not asked in the
    # browser run above, which queues its jobs itself.)
    source = (FRONTEND / "src" / "teile" / "Katalog.svelte").read_text(encoding="utf-8")
    for piece in (
        "ziel: f.ziel ?? null, groesse: f.groesse }",
        "rolle: 'mmproj', groesse: repoAugen.groesse_gb }",
        "rolle: teil.feld, groesse: teil.groesse_gb,",
        "ziel: modell === flach(d.datei) ? null : modell, groesse: d.groesse_gb },",
    ):
        assert piece in source, piece


# --- The row of the Hugging Face token ------------------------------------------


def test_the_set_token_is_a_row_of_54_with_its_logo_name_and_dot(with_token):
    token = with_token["token"]
    row = token["row"]
    assert abs(row["height"] - 54) <= 1, row
    assert abs(token["logo"]["x"] - row["x"] - 15) <= 1, token["logo"]
    assert abs(token["name"]["x"] - token["logo"]["right"] - 12) <= 1, (token["logo"], token["name"])
    assert token["nameStyle"]["size"] == "13.5px" and token["nameStyle"]["weight"] == "500"
    assert token["nameStyle"]["color"] == with_token["tokens"]["text"]
    assert abs(token["dot"]["width"] - 9) <= 0.5 and abs(token["dot"]["height"] - 9) <= 0.5, token["dot"]


def test_the_masked_field_fills_the_row_from_the_dot_to_the_button_12_before_it(with_token):
    token = with_token["token"]
    assert token["fieldText"] == "••••••••••••a1b2"
    assert abs(token["field"]["height"] - 32) <= 0.5, token["field"]
    # It begins 12 behind the dot and ends 12 before the button: nothing of the row is left over.
    assert abs(token["field"]["x"] - token["dot"]["right"] - 12) <= 1, (token["dot"], token["field"])
    assert token["field"]["width"] > 400, token["field"]
    assert abs(token["button"]["x"] - token["field"]["right"] - 12) <= 1, (token["field"], token["button"])
    assert abs(token["row"]["right"] - token["button"]["right"] - 11) <= 1, (token["row"], token["button"])
    assert token["fieldStyle"] == {"size": "12.5px", "weight": "400", "color": with_token["tokens"]["leise"]}


def test_the_bin_is_a_button_of_32_on_the_glass_with_its_line_and_a_sign_of_14(with_token):
    token = with_token["token"]
    button, sign = token["button"], token["sign"]
    assert abs(button["width"] - 32) <= 0.5 and abs(button["height"] - 32) <= 0.5, button
    assert token["buttonGround"] not in ("rgba(0, 0, 0, 0)", "transparent"), token["buttonGround"]
    assert token["buttonLine"] != "none", token["buttonLine"]
    assert token["buttonRadius"] == "9px"
    assert abs(sign["width"] - 14) <= 0.5 and abs(sign["height"] - 14) <= 0.5, sign
    assert abs(sign["x"] + sign["width"] / 2 - (button["x"] + button["width"] / 2)) <= 0.5
    assert token["buttonLabel"], "the bin keeps its tooltip"


def test_a_set_token_has_no_field_to_type_into_and_no_footnote(with_token):
    token = with_token["token"]
    assert token["inputs"] == 0, "the set token is shown, not typed"
    assert not token["note"], "the footnote stands under the empty row only"


def test_the_empty_row_has_the_same_field_and_the_word_behind_it(measured):
    empty = measured["tokenEmpty"]
    assert abs(empty["field"]["height"] - 32) <= 0.5, empty["field"]
    assert abs(empty["field"]["x"] - empty["dot"]["right"] - 12) <= 1, (empty["dot"], empty["field"])
    assert empty["field"]["width"] > 400, empty["field"]
    assert abs(empty["row"]["height"] - 54) <= 1, empty["row"]
    assert empty["fieldStyle"]["size"] == "12.5px" and empty["fieldStyle"]["weight"] == "400", empty["fieldStyle"]
    assert empty["buttonText"] == "Verbinden"
    assert abs(empty["row"]["right"] - empty["button"]["right"] - 11) <= 1, empty
    assert abs(empty["button"]["x"] - empty["field"]["right"] - 12) <= 1, empty
    assert empty["note"] and empty["note"]["y"] >= empty["row"]["bottom"], empty


# --- The hits of the search -----------------------------------------------------


def test_a_search_hit_is_a_row_of_56_with_its_name_in_14_medium(with_token):
    hits = with_token["hits"]
    assert len(hits) == 3
    for hit in hits:
        assert abs(hit["rect"]["height"] - 56) <= 1, hit["rect"]
        assert hit["nameStyle"]["size"] == "14px" and hit["nameStyle"]["weight"] == "500", hit["nameStyle"]
        assert hit["nameStyle"]["color"] == with_token["tokens"]["text"]
        assert abs(hit["who"]["x"] - hit["mark"]["right"] - 12) <= 1, (hit["mark"], hit["who"])


def test_the_maker_and_the_loads_stand_in_12_px_quiet(with_token):
    for hit in with_token["hits"]:
        assert hit["underStyle"]["size"] == "12px" and hit["countStyle"]["size"] == "12px", hit
        assert hit["underStyle"]["color"] == with_token["tokens"]["still"]
        assert hit["countStyle"]["color"] == with_token["tokens"]["still"]
        assert abs(hit["arrow"]["x"] - hit["countRect"]["right"] - 12) <= 1, hit
    first = with_token["hits"][0]
    assert first["count"].endswith("↓") and first["name"] == "LFM2.5-24B-A2B-GGUF"
