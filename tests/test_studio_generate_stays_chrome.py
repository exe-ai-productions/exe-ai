"""In the picture studio a picture that comes into the generation area never
changes the mode, measured in a real browser.

`ImageStudio.svelte` and the left column `StudioBasics.svelte` are built as
shipped and drawn in headless Chrome at 1920 x 1080 with the picture service
made up in the page: one model, a row of three pictures, and start values
that arrive after a delay. "Generate" stays "generate" when a tile of the row
is clicked and when the start values arrive late, and the draw it asks for
carries no start picture; "edit with a picture" and "auto" stay as chosen, and
the strength still steps down from 1 to 0.6. Skipped where there is no Chrome
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
  import ImageStudio from '../../src/teile/ImageStudio.svelte'
  import StudioBasics from '../../src/teile/StudioBasics.svelte'

  const draw = (job) => { (window.__draws ??= []).push(job) }
</script>

<div id="frame" style="width: 1920px; height: 1000px; display: flex; position: relative;">
  <div style="width: 340px; flex: none; position: relative; overflow: hidden;"><StudioBasics /></div>
  <div style="flex: 1; position: relative;"><ImageStudio zeichnen={draw} /></div>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { werte, auswahl } from %(studio)r

const scenario = new URLSearchParams(location.search).get('scenario')
const names = ['a', 'b', 'c'].map((c) => c.repeat(32) + '.png')
const answers = {
  '/bild/modelle': {
    programm_da: true, modelle: ['model-a'], standardmodell: 'model-a', families: {}, sampler: [], scheduler: [],
    loras: [], sizes: {},
  },
  '/bild/familien': [],
  '/bild/vorgaben': { family: '', breite: 1024, hoehe: 1024, schritte: 8, cfg: 1 },
  '/bilder': { bilder: names },
  '/settings/resolved/bildfenster': { wert: { modell: 'model-a', prompt: 'a cat' } },
}
const delays = { '/bild/vorgaben': scenario === 'late' ? 3000 : 0 }
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  if (delays[path]) await new Promise((r) => setTimeout(r, delays[path]))
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
window.__studio = { werte, auswahl, names }
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
const scenario = new URLSearchParams(location.search).get('scenario')
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const modeButton = () => document.querySelector('.modeplace .mode')
const modeText = () => modeButton().querySelector('span').textContent.trim()
const tiles = () => Array.from(document.querySelectorAll('.leiste .kachel.bild .flaeche'))
for (let k = 0; k < 100 && (!modeButton() || tiles().length < 3); k += 1) await wait(100)
await wait(600)

const chooseKind = async (text) => {
  modeButton().click()
  await wait(200)
  const option = Array.from(document.querySelectorAll('.modelist [role="option"]'))
    .find((o) => o.textContent.trim() === text || o.textContent.trim().startsWith(text))
  option.click()
  await wait(200)
}
const { werte, auswahl } = window.__studio
const report = { scenario, tiles: tiles().length }

const kind = { generate: 'bild.art_txt2img', edit: 'bild.art_img2img', auto: 'bild.art_auto' }[
  { tile: 'generate', late: 'generate', edit: 'edit', auto: 'auto' }[scenario]
]
if (scenario === 'auto') {
  // "Auto" is the start; no choice is made.
} else {
  await chooseKind(kind)
}
report.chosen = { text: modeText(), art: auswahl.art }
// A full strength, as a picture that has just been laid in finds it.
werte.staerke = 1
const tile = tiles()[1]
tile.click()
await wait(400)
report.afterTile = { text: modeText(), art: auswahl.art, startbild: werte.startbild, strength: werte.staerke }

if (scenario === 'late') {
  // The start values are still on their way: choose again, then let them arrive.
  await chooseKind(kind)
  report.beforeLate = { text: modeText(), art: auswahl.art }
  await wait(4000)
  report.afterLate = { text: modeText(), art: auswahl.art, startbild: werte.startbild }
}

{
  const prompt = document.querySelector('textarea.prompt')
  prompt.focus()
  prompt.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  for (let k = 0; k < 60 && !(window.__draws || []).length; k += 1) await wait(100)
  const job = (window.__draws || [])[0]
  report.draw = job ? { startbild: job.startbild, maske: job.maske, prompt: job.prompt } : null
  report.afterDraw = { text: modeText(), art: auswahl.art, startbild: werte.startbild }
}

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1920px; position: relative; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
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
</body></html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 150.0) -> dict:
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
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


@pytest.fixture(scope="module")
def harness():
    """The page built once; each case opens it with its own scenario."""
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-studio-generate-stays-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css", "studio": "../../src/lib/studio.svelte.js"},
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE % {"cases": CASES}, encoding="utf-8")

        def measure(scenario: str) -> dict:
            port = _free_port()
            browser = subprocess.Popen(
                [
                    program,
                    "--headless=new",
                    "--no-first-run",
                    "--disable-background-networking",
                    "--allow-file-access-from-files",
                    "--window-size=1920,1080",
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={folder / ('profile-' + scenario)}",
                    (folder / "measure.html").as_uri() + f"?scenario={scenario}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                return asyncio.run(_drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)

        yield measure
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def tile(harness) -> dict:
    return harness("tile")


@pytest.fixture(scope="module")
def late(harness) -> dict:
    return harness("late")


@pytest.fixture(scope="module")
def edit(harness) -> dict:
    return harness("edit")


@pytest.fixture(scope="module")
def auto(harness) -> dict:
    return harness("auto")


# --- "Generate" stays "generate" ---


def test_a_tile_of_the_row_leaves_generate_as_it_is(tile):
    assert tile["tiles"] == 3, tile
    assert tile["chosen"]["art"] == "txt2img", tile
    assert tile["afterTile"]["art"] == "txt2img" and tile["afterTile"]["text"] == "bild.art_txt2img", tile
    # The picture did come into the area: the tile is what the area holds now.
    assert tile["afterTile"]["startbild"] == "b" * 32 + ".png", tile


def test_the_draw_after_that_makes_a_new_picture_and_the_picture_stays_in_the_area(tile):
    assert tile["draw"] is not None, tile
    assert tile["draw"]["startbild"] is None and tile["draw"]["maske"] is None, tile
    assert tile["afterDraw"]["art"] == "txt2img", tile
    assert tile["afterDraw"]["startbild"] == "b" * 32 + ".png", tile


def test_start_values_that_arrive_late_leave_generate_as_it_is(late):
    assert late["beforeLate"]["art"] == "txt2img", late
    assert late["afterLate"]["art"] == "txt2img" and late["afterLate"]["text"] == "bild.art_txt2img", late
    assert late["afterLate"]["startbild"] == "b" * 32 + ".png", late
    assert late["draw"] is not None and late["draw"]["startbild"] is None, late


# --- Silence: what stays as it was ---


def test_silence_edit_with_a_picture_stays_edit_and_the_strength_steps_down(edit):
    assert edit["chosen"]["art"] == "img2img", edit
    assert edit["afterTile"]["art"] == "img2img" and edit["afterTile"]["text"] == "bild.art_img2img", edit
    assert edit["afterTile"]["strength"] == 0.6, edit
    # It draws from the picture in the area, as before.
    assert edit["draw"] is not None and edit["draw"]["startbild"], edit


def test_silence_auto_stays_auto_and_the_strength_steps_down(auto):
    assert auto["afterTile"]["art"] == "auto" and auto["afterTile"]["text"] == "bild.art_auto", auto
    assert auto["afterTile"]["strength"] == 0.6, auto
    # With a picture and a strength below 1 "auto" still edits the picture.
    assert auto["draw"] is not None and auto["draw"]["startbild"], auto
