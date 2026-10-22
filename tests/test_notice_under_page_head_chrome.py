"""The notices begin under the head of the page that stands open, in a real
browser.

Over the chat the stack of notices begins 46 px under the edge of the chat
tile. Over a menu page (the cloud providers, the local models, the catalogue,
the settings) the head of the page is taller, and the stack began in the
middle of its title; in the picture studio it lay over the zoom and the
button of the row of pictures. Now the stack begins under the head of the
page, and under the bars of the studio — also in a window so narrow that the
head breaks into two lines — and under the chat's own head, as before, where
no page stands open. The head and the bars stay free; two notices stand 8 px
apart; the cross closes a notice.

`App.svelte` is built as shipped and drawn in headless Chrome with the global
stylesheet; the service is not asked: the page answers every request itself,
with empty lists, and the notices are made up (two that stay). Skipped where
there is no Chrome or no node, like the other browser tests.
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
import { zustand, seiteZeigen, seitenSchliessen } from '../../src/lib/zustand.svelte.js'
import { melde } from '../../src/lib/meldewesen.svelte.js'
import { studioOeffnen, studioSchliessen } from '../../src/lib/studio.svelte.js'

texte.katalog = german
texte.sprache = 'de'
window.__zustand = zustand
window.__api = { melde, seiteZeigen, seitenSchliessen, studioOeffnen, studioSchliessen }
const LISTS = ['/models', '/agents', '/skills', '/jobs', '/cronjobs', '/chats', '/projects', '/endpoints']
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = LISTS.includes(path) ? [] : path === '/runner' ? { speicher_gb: 64, modelle: [], mmproj: [], mtp: [] } : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
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
const zustand = window.__zustand
const api = window.__api
// Waits for what the script is about to check, with a ceiling, instead of for a fixed time.
const until = async (ready, limit = 15000) => {
  for (let waited = 0; waited < limit; waited += 50) {
    if (ready()) return true
    await wait(50)
  }
  return false
}
// The notices move while they slide in or settle: wait until their boxes stand still.
const still = async () => {
  let last = null
  for (let k = 0; k < 200; k += 1) {
    const now = JSON.stringify(Array.from(document.querySelectorAll('.stapel .meldung, .stapel')).map((node) => rect(node)))
    if (now === last) return
    last = now
    await wait(100)
  }
}
await until(() => document.querySelector('.chatkopf'))
await still()

const notes = () => Array.from(document.querySelectorAll('.stapel .meldung'))
const topOfNotes = () => Math.min(...notes().map((note) => note.getBoundingClientRect().top))
const overlapping = (head) => {
  const boxes = notes().map(rect)
  return Array.from(head.querySelectorAll('*')).filter((node) => {
    const r = rect(node)
    return r.width > 0 && r.height > 0 && boxes.some((b) => r.x < b.right && r.right > b.x && r.y < b.bottom && r.bottom > b.y)
  }).length
}

// Over the chat: two notices that stay.
api.melde('First notice', 'hinweis', { dauerhaft: true })
api.melde('Second notice', 'hinweis', { dauerhaft: true })
await until(() => notes().length === 2)
await still()
const stack = document.querySelector('.stapel')
const sorted = notes().map(rect).sort((a, b) => a.y - b.y)
report.chat = {
  count: notes().length,
  fromEdge: Math.round((sorted[0].y - rect(stack).y) * 10) / 10,
  gap: Math.round((sorted[1].y - sorted[0].bottom) * 10) / 10,
  centred: Math.abs((sorted[0].x + sorted[0].width / 2) - (rect(stack).x + rect(stack).width / 2)) <= 1,
  menuHeadBottom: zustand.menuHeadBottom,
  chatHeadBottom: rect(document.querySelector('.chatkopf')).bottom,
  stackTop: rect(stack).y,
}

// Over each menu page.
report.pages = {}
for (const name of ['cloud', 'lokal', 'katalog', 'prompt']) {
  api.seiteZeigen(name)
  await until(() => Array.from(document.querySelectorAll('.rechts .kopf')).some((node) => node.getBoundingClientRect().height > 0))
  await still()
  // A page whose frame stays mounted while closed (the catalogue) leaves a head
  // of no size behind: the head that is drawn is the one with a size.
  const head = Array.from(document.querySelectorAll('.rechts .kopf')).find((node) => node.getBoundingClientRect().height > 0)
  report.pages[name] = head ? {
    head: rect(head), noteTop: topOfNotes(), overlaps: overlapping(head),
    menuHeadBottom: zustand.menuHeadBottom, stackTop: rect(document.querySelector('.stapel')).y,
  } : null
}

// Over the studio.
api.studioOeffnen()
await until(() => document.querySelector('.studio .gallery .kopf') && document.querySelector('.studio .zoom'))
await still()
const gallery = document.querySelector('.studio .gallery .kopf')
const zoom = document.querySelector('.studio .zoom')
report.studio = gallery ? {
  gallery: rect(gallery), zoom: rect(zoom), noteTop: topOfNotes(), menuHeadBottom: zustand.menuHeadBottom,
} : null

// Back over the chat.
api.studioSchliessen()
api.seitenSchliessen()
await until(() => !document.querySelector('.studio'))
await still()
const back = notes().map(rect).sort((a, b) => a.y - b.y)
report.back = {
  fromEdge: back.length ? Math.round((back[0].y - rect(document.querySelector('.stapel')).y) * 10) / 10 : null,
  menuHeadBottom: zustand.menuHeadBottom,
}

// The cross closes a notice.
const before = notes().length
document.querySelector('.stapel .meldung .zu').click()
await until(() => notes().length < before)
report.cross = { before, after: notes().length }
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: @@WIDTH@@px; height: @@HEIGHT@@px; position: relative; }</style>
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


def _run_case(width: int, height: int) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-notice-under-head-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        entry = ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
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
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", CASES).replace("@@WIDTH@@", str(width)).replace("@@HEIGHT@@", str(height)), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                f"--window-size={width},{height}",
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
def wide() -> dict:
    return _run_case(1920, 1080)


@pytest.fixture(scope="module")
def narrow() -> dict:
    return _run_case(520, 900)


PAGES = ("cloud", "lokal", "katalog", "prompt")


@pytest.mark.parametrize("name", PAGES)
def test_over_a_menu_page_the_notices_begin_under_its_head(wide, name):
    page = wide["pages"][name]
    assert page, f"the page {name} drew no head"
    assert page["noteTop"] >= page["head"]["bottom"] - 0.5, page
    assert page["overlaps"] == 0, page


@pytest.mark.parametrize("name", PAGES)
def test_the_same_in_a_window_so_narrow_that_the_head_breaks(narrow, name):
    page = narrow["pages"][name]
    assert page, f"the page {name} drew no head in the narrow window"
    assert page["noteTop"] >= page["head"]["bottom"] - 0.5, page
    assert page["overlaps"] == 0, page


def test_in_the_narrow_window_the_head_of_the_cloud_page_has_two_lines(narrow, wide):
    assert narrow["pages"]["cloud"]["head"]["height"] > wide["pages"]["cloud"]["head"]["height"] + 5, (
        narrow["pages"]["cloud"], wide["pages"]["cloud"],
    )


def test_over_the_studio_the_notices_begin_under_the_bars(wide):
    studio = wide["studio"]
    assert studio, "the studio drew no row of pictures"
    assert studio["noteTop"] >= studio["gallery"]["bottom"] - 0.5, studio
    assert studio["noteTop"] >= studio["zoom"]["bottom"] - 0.5, studio


def test_silence_over_the_chat_the_notices_stand_46_px_under_the_edge_and_8_px_apart(wide):
    chat = wide["chat"]
    assert chat["count"] == 2, chat
    assert abs(chat["fromEdge"] - 46) <= 1, chat
    assert abs(chat["gap"] - 8) <= 1, chat
    assert chat["centred"], chat
    assert chat.get("menuHeadBottom") is None, chat


def test_silence_after_the_page_or_the_studio_closes_the_stack_stands_under_the_chat_head_again(wide):
    back = wide["back"]
    assert back.get("menuHeadBottom") is None, back
    assert abs(back["fromEdge"] - 46) <= 1, back


def test_silence_the_cross_still_closes_a_notice(wide):
    assert wide["cross"]["after"] == wide["cross"]["before"] - 1, wide["cross"]
