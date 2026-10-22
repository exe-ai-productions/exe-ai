"""The sign of a running download in the head of the chat, measured in a
real browser.

While a download runs or waits, a small glass button with the sign `download`
in the blue of "running" stands at the right end of the chat's head — 26 px,
8 px from the right edge of the chat, in the middle of the head's row; a click
opens the catalogue on its downloads page without a way back. Nothing runs or
waits: nothing stands there. The catalogue asks the service for the state
while its page is closed, as long as something runs or waits — and not a
moment longer.

`App.svelte` is built as shipped and drawn in headless Chrome with the global
stylesheet; the service is not asked — the page answers every request itself,
with a download that runs (made up). Skipped where there is no Chrome or no
node, like the other browser tests.
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

ENTRY_JS = """import { mount } from 'svelte'
import App from '../../src/App.svelte'
import '../../src/stil/global.css'
import german from '@@GERMAN@@'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import { weg } from '../../src/lib/fensterweg.svelte.js'
import { downloads, einreihen } from '../../src/lib/downloads.svelte.js'

texte.katalog = german
texte.sprache = 'de'
const start = location.hash.slice(1)
const STARTS = {
  running: { datei: 'before-the-reload.gguf', fertig: false, fehler: null, geladen: 1e9, gesamt: 4e9, anteil: 0.25 },
  done: { datei: 'before-the-reload.gguf', fertig: true, fehler: null, geladen: 4e9, gesamt: 4e9, anteil: 1 },
  cancelled: { datei: 'before-the-reload.gguf', fertig: false, fehler: 'abgebrochen', geladen: 1e9, gesamt: 4e9, anteil: 0.25 },
}
const scenario = { stand: STARTS[start] ?? null, gets: 0, posts: [] }
window.__scenario = scenario
window.__zustand = zustand
window.__weg = weg
window.__downloads = downloads
window.__enqueue = einreihen
window.fetch = async (address, options = {}) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const method = (options.method || 'GET').toUpperCase()
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  if (path === '/runner/download') {
    if (method === 'POST') {
      const body = JSON.parse(options.body || '{}')
      scenario.posts.push(body.datei)
      scenario.stand = { datei: body.datei, fertig: false, fehler: null, geladen: 1e9, gesamt: 4e9, anteil: 0.25 }
      return json(scenario.stand)
    }
    scenario.gets += 1
    return json(scenario.stand)
  }
  if (path === '/runner') return json({ speicher_gb: 64, modelle: [], mmproj: [], mtp: [] })
  if (path === '/models/token') return json({ gesetzt: false })
  return json({})
}
mount(App, { target: document.getElementById('wurzel') })
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
const scenario = window.__scenario
const downloads = window.__downloads
const zustand = window.__zustand
const weg = window.__weg
const probe = document.createElement('span')
probe.style.color = 'var(--blau)'
document.body.appendChild(probe)
report.blue = getComputedStyle(probe).color
const poll = () => wait(2600)
const indicator = () => document.querySelector('.chatkopf .download-indicator')

for (let k = 0; k < 100 && !document.querySelector('.chatkopf'); k += 1) await wait(100)
await wait(800)

// Nothing runs: no sign; the window asked the service once when it started,
// and the closed catalogue does not ask for 5 s after that.
report.idle = { sign: Boolean(indicator()), atStart: scenario.gets }
const asked = scenario.gets
await wait(5000)
report.idle.asked = scenario.gets - asked

// One runs (the service says so), one waits: the sign stands in the head.
scenario.stand = { datei: 'first-model.gguf', fertig: false, fehler: null, geladen: 1e9, gesamt: 4e9, anteil: 0.25 }
window.__enqueue({ repo: 'maker/Second-GGUF', datei: 'second-model.gguf' })
await poll()
const sign = indicator()
const head = document.querySelector('.chatkopf')
const chat = head.parentElement
report.sign = {
  present: Boolean(sign),
  rect: rect(sign),
  head: rect(head),
  chat: rect(chat),
  color: sign ? getComputedStyle(sign).color : null,
  radius: sign ? getComputedStyle(sign).borderTopLeftRadius : null,
  label: sign ? sign.getAttribute('aria-label') : null,
  title: sign ? sign.getAttribute('title') : null,
  icon: Boolean(sign && sign.querySelector('svg')),
}

// A click opens the catalogue on its downloads page, with no way back.
sign?.click()
await wait(800)
report.click = {
  catalogueOpen: zustand.katalogOffen === true,
  wish: zustand.katalogArtWunsch,
  back: Boolean(weg.zurueck),
  backButton: Boolean(document.querySelector('.markenzeile .zurueck')),
  current: document.querySelector('.kinds .menuezeile[aria-current="true"]')?.textContent.trim() ?? null,
}

// The page closed, the first one is done: the second is asked for within 4 s.
zustand.katalogOffen = false
await wait(500)
scenario.stand = { datei: 'first-model.gguf', fertig: true, fehler: null, geladen: 4e9, gesamt: 4e9, anteil: 1 }
for (let k = 0; k < 40 && scenario.posts.length === 0; k += 1) await wait(100)
report.next = { posts: [...scenario.posts] }

// The second is done as well: the sign is gone within 3 s, and the asking stops.
scenario.stand = { datei: 'second-model.gguf', fertig: true, fehler: null, geladen: 4e9, gesamt: 4e9, anteil: 1 }
let gone = null
const began = Date.now()
for (let k = 0; k < 80 && gone === null; k += 1) {
  await wait(100)
  if (!indicator()) gone = Date.now() - began
}
report.gone = { ms: gone, sign: Boolean(indicator()), active: downloads.warteschlange.length + (downloads.laufend ? 1 : 0) }
const after = scenario.gets
await wait(5000)
report.gone.asked = scenario.gets - after
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

RELOAD_CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const scenario = window.__scenario
const downloads = window.__downloads
const zustand = window.__zustand
const indicator = () => document.querySelector('.chatkopf .download-indicator')

for (let k = 0; k < 100 && !document.querySelector('.chatkopf'); k += 1) await wait(100)
// The window has just started, the catalogue has never been opened, nothing was
// queued: what the service says is all there is.
await wait(2500)
report.start = {
  sign: Boolean(indicator()),
  open: zustand.katalogOffen === true,
  queued: downloads.warteschlange.length,
  receipts: downloads.fertig.length,
  asked: scenario.gets,
}

// The service reports the download done: the sign goes, and the asking stops.
scenario.stand = { datei: 'before-the-reload.gguf', fertig: true, fehler: null, geladen: 4e9, gesamt: 4e9, anteil: 1 }
let gone = null
const began = Date.now()
for (let k = 0; k < 80 && gone === null; k += 1) {
  await wait(100)
  if (!indicator()) gone = Date.now() - began
}
const after = scenario.gets
await wait(5000)
report.end = { ms: gone, sign: Boolean(indicator()), asked: scenario.gets - after, receipts: downloads.fertig.length }
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; height: 700px; position: relative; }</style>
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


def _run_case(cases: str = CASES, start: str = "") -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-download-indicator-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        entry = (
            ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
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
                "--window-size=1280,700",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri() + (f"#{start}" if start else ""),
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
def reloaded_running() -> dict:
    return _run_case(RELOAD_CASES, "running")


@pytest.fixture(scope="module")
def reloaded_done() -> dict:
    return _run_case(RELOAD_CASES, "done")


@pytest.fixture(scope="module")
def reloaded_cancelled() -> dict:
    return _run_case(RELOAD_CASES, "cancelled")


def test_the_harness_has_the_house_colours(measured):
    # Without the global stylesheet every colour reads black and the colour
    # check below would compare black with black.
    assert measured["blue"] not in ("rgb(0, 0, 0)", "")


def test_silence_without_a_download_there_is_no_sign_and_no_asking(measured):
    # One question when the window starts (a download that runs across a
    # reload), none after it.
    assert measured["idle"] == {"sign": False, "atStart": 1, "asked": 0}


def test_a_running_download_shows_a_sign_of_26_px_in_the_head(measured):
    sign = measured["sign"]
    assert sign["present"] and sign["icon"]
    assert abs(sign["rect"]["width"] - 26) <= 0.5 and abs(sign["rect"]["height"] - 26) <= 0.5
    assert sign["radius"] == "9px"


def test_the_sign_stands_8_px_from_the_right_edge_of_the_chat(measured):
    sign = measured["sign"]
    assert abs(sign["chat"]["right"] - sign["rect"]["right"] - 8) <= 1, sign


def test_the_sign_stands_in_the_middle_of_the_row_of_the_head(measured):
    sign = measured["sign"]
    middle = sign["rect"]["y"] + sign["rect"]["height"] / 2
    assert abs(middle - (sign["head"]["y"] + sign["head"]["height"] / 2)) <= 1, sign


def test_the_sign_is_blue_and_named_downloads(measured):
    sign = measured["sign"]
    assert sign["color"] == measured["blue"]
    assert sign["label"] == "Downloads" and sign["title"] == "Downloads"


def test_a_click_opens_the_downloads_page_without_a_way_back(measured):
    click = measured["click"]
    assert click["catalogueOpen"] and not click["back"] and not click["backButton"], click
    assert click["current"] and click["current"].startswith("Downloads"), click


def test_a_download_waiting_with_the_catalogue_closed_is_started_after_the_first(measured):
    assert measured["next"]["posts"] == ["second-model.gguf"]


def test_the_sign_goes_when_nothing_runs_or_waits_and_the_asking_stops_with_it(measured):
    gone = measured["gone"]
    assert gone["ms"] is not None and gone["ms"] <= 3000, gone
    assert gone["active"] == 0 and gone["asked"] == 0, gone


def test_the_phone_page_has_no_such_sign():
    for path in sorted((FRONTEND / "src" / "phone").rglob("*.svelte")):
        assert "DownloadIndicator" not in path.read_text(encoding="utf-8"), path.name


# --- A window that starts while the service is loading ------------------------


def test_a_download_running_before_the_reload_shows_the_sign_without_the_catalogue(reloaded_running):
    start = reloaded_running["start"]
    assert start["sign"] and not start["open"], start
    # Nothing was queued in this session and no receipt is made of it.
    assert start["queued"] == 0 and start["receipts"] == 0, start


def test_the_sign_of_a_download_from_before_the_reload_goes_when_the_service_says_done(reloaded_running):
    end = reloaded_running["end"]
    assert end["ms"] is not None and end["ms"] <= 3000, end
    assert end["asked"] == 0, end
    # Finished while the window watched, it is a receipt of this session — the
    # catalogue's poll writes it, as for any download that ends under it.
    assert end["receipts"] == 1, end


@pytest.mark.parametrize("fixture", ["reloaded_done", "reloaded_cancelled"])
def test_a_finished_or_cancelled_download_from_before_the_reload_shows_nothing(request, fixture):
    start = request.getfixturevalue(fixture)["start"]
    assert not start["sign"] and start["receipts"] == 0 and start["queued"] == 0, start
    # The one question at the start, and nothing after it.
    assert start["asked"] == 1, start
