"""A PDF drawn by the program itself, measured in a real browser.

The rail beside the chat, the view over the window and the tiles of the doc
folder draw a PDF with pdf.js instead of handing it to the browser's own
viewer, so it looks and rolls the same on every system: no frame, the pages
one under the other fitted to the width, a bar-less roll, the corners of
what holds it, a line while it is read, a line when it cannot be, selectable
text, and a first page on the tile.

The real components (the rail's `ModulVorschau`, the view `Bildschau`, the
doc folder) are built as shipped and drawn in headless Chrome, which is served
the build, a PDF of five pages and the data folders of pdf.js by a small web
server of this test (a library that starts its own worker and fetches its own
fonts cannot be measured from a file address). The page reports what it
drew.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, inhaltssicherheit, prozessstopp
from tests.conftest import pdf_mit_seiten

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ENGLISH = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None
        or not (FRONTEND / "node_modules" / "vite").exists()
        or not (FRONTEND / "node_modules" / "pdfjs-dist").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

PAGE_TEXTS = [f"Page number {n}" for n in range(1, 6)]

SHELL = """<script>
  import ModulVorschau from '../../src/teile/ModulVorschau.svelte'
  import Bildschau from '../../src/teile/Bildschau.svelte'
  import DocFolder from '../../src/teile/DocFolder.svelte'
  import PdfFrame from '../../src/teile/PdfFrame.svelte'
</script>

<div id="kasten" style="position: absolute; left: 0; top: 0; width: 360px; height: 520px; display: flex; flex-direction: column;">
  <ModulVorschau />
</div>
<div id="kaputt" style="position: absolute; left: 400px; top: 0; width: 300px; height: 200px; border-radius: 9px; overflow: hidden;">
  <div style="position: relative; width: 100%; height: 100%; border-radius: 9px;"><PdfFrame address="/api/v1/broken.pdf" title="broken" /></div>
</div>
<div id="ordner" style="position: absolute; left: 400px; top: 240px; width: 340px; height: 300px;"><DocFolder /></div>
<Bildschau />
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import '../../src/stil/tiles.css'
import '../../src/stil/berichttext.css'
import english from '../../../app/locales/en.json'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import { tabEinsortieren } from '../../src/lib/vorschautabs.svelte.js'
import { showPage } from '../../src/lib/bildschau.svelte.js'
import { pdfData } from '../../src/lib/pdfDocument.js'

window.__errors = []
window.addEventListener('error', (e) => window.__errors.push(String(e.message)))
window.addEventListener('unhandledrejection', (e) => window.__errors.push(String(e.reason && e.reason.message || e.reason)))
const loudError = console.error
console.error = (...a) => { window.__errors.push(a.map(String).join(' ')); loudError(...a) }

pdfData.base = location.origin + '/pdfjs/'
texte.sprache = 'en'
texte.katalog = english
const answer = (body) => new Response(JSON.stringify(body), {
  status: 200, headers: { 'Content-Type': 'application/json' },
})
const FILES = [{ id: '1', source: 'agent', name: 'five.pdf', type: 'application/pdf', size: 1500,
                 origin: 'agent', agent: 'x', path: '/five.pdf' }]
const realFetch = window.fetch.bind(window)
window.fetch = async (address, ...rest) => {
  const url = String(address)
  if (url.includes('/doc-folder')) return answer(FILES)
  if (url.includes('/speicherorte')) return answer([{ name: 'agent_dock', pfad: '/data/dock' }])
  if (url.includes('/api/v1/') && !url.endsWith('.pdf')) return answer({})
  return realFetch(address, ...rest)
}
zustand.chats = [{ id: 'c1', title: 'Chat' }]
zustand.aktiverChat = 'c1'
tabEinsortieren('c1', { name: 'five.pdf', art: 'pdf', inhalt: '', adresse: '/api/v1/five.pdf', fakten: '' })
const holder = document.getElementById('wurzel')
mount(Shell, { target: holder })
window.openView = () => showPage({ name: 'five.pdf', adresse: '/api/v1/five.pdf', framed: true })
// The line a PDF shows until its first page stands, read at once.
window.__first = {
  note: document.querySelector('#kasten .note')?.textContent ?? null,
}
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
window.__first.note = document.querySelector('#kasten .note')?.textContent ?? window.__first.note
for (let k = 0; k < 150 && !(document.querySelectorAll('#kasten .pdf .seite canvas').length >= 5
  && document.querySelector('#kasten .pdf .textLayer span')
  && document.querySelector('#kaputt .note.failure')
  && document.querySelector('#ordner img.shell')); k += 1) await wait(100)
await wait(500)

const inkOf = (canvas) => {
  const context = canvas.getContext('2d')
  const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
  let dark = 0
  for (let i = 0; i < data.length; i += 4) if (data[i] < 128) dark += 1
  return dark
}
const rail = document.querySelector('#kasten .pdf')
const pages = Array.from(rail.querySelectorAll('.seite'))
const span = rail.querySelector('.textLayer span')
const selection = getSelection()
selection.removeAllRanges()
const range = document.createRange()
range.selectNodeContents(span)
selection.addRange(range)
const report = {
  noteAtOnce: window.__first.note,
  frames: document.querySelectorAll('iframe').length,
  rail: {
    pages: pages.length,
    firstWidth: pages[0].getBoundingClientRect().width,
    hostWidth: rail.clientWidth,
    firstInk: inkOf(pages[0].querySelector('canvas')),
    pageHeights: pages.map((page) => page.getBoundingClientRect().height),
    scrollbarWidth: getComputedStyle(rail).scrollbarWidth,
    mask: getComputedStyle(rail).maskImage,
    radius: getComputedStyle(rail).borderRadius,
    holderRadius: getComputedStyle(rail.parentElement).borderRadius,
    overflowY: getComputedStyle(rail).overflowY,
    text: span.textContent,
    textSelectable: getComputedStyle(span).userSelect,
    selected: selection.toString(),
    noteGone: !rail.querySelector('.note'),
    scrollable: rail.scrollHeight > rail.clientHeight,
  },
  broken: document.querySelector('#kaputt .note.failure').textContent,
  tile: (() => {
    const img = document.querySelector('#ordner img.shell')
    return img ? { src: img.getAttribute('src').slice(0, 22), wide: img.naturalWidth }
      : { src: null, wide: 0 }
  })(),
}
window.openView()
for (let k = 0; k < 150 && !document.querySelector('.page.framed .pdf .seite canvas'); k += 1) await wait(100)
await wait(800)
const view = document.querySelector('.page.framed .pdf')
report.view = {
  pages: view.querySelectorAll('.seite').length,
  firstInk: inkOf(view.querySelector('.seite canvas')),
  scrollbarWidth: getComputedStyle(view).scrollbarWidth,
  hostWidth: view.clientWidth,
  firstWidth: view.querySelector('.seite').getBoundingClientRect().width,
}
// Rolls: the far pages are drawn when they come into view.
const last = view.querySelectorAll('.seite')[4]
view.scrollTop = view.scrollHeight
await wait(1200)
report.view.lastInk = inkOf(last.querySelector('canvas'))
report.errors = window.__errors.slice(0, 6)
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  base: './',
  // A library build keeps `process.env.NODE_ENV` as written; the app's build replaces it.
  define: { 'process.env.NODE_ENV': '"production"' },
  logLevel: 'error',
  build: {
    outDir: 'out',
    emptyOutDir: true,
    minify: false,
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
%(links)s
<style>html { --stufenfaktor: 1; } html, body { margin: 0; } #wurzel { width: 1280px; height: 1000px; position: relative; }</style>
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


class _Handler(http.server.SimpleHTTPRequestHandler):
    """The harness folder, with the service's file address mapped onto it."""

    def translate_path(self, path: str) -> str:
        path = path.split("?", 1)[0]
        if path.startswith("/api/v1/"):
            path = path[len("/api/v1"):]
        return super().translate_path(path)

    def log_message(self, *args) -> None:
        pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 150.0) -> dict:
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


def _run() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-pdf-pages-{uuid4().hex}"
    folder.mkdir(parents=True)
    server = None
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        (folder / "measure.html").write_text(PAGE % {"cases": CASES, "links": links}, encoding="utf-8")
        (folder / "five.pdf").write_bytes(pdf_mit_seiten(PAGE_TEXTS))
        (folder / "broken.pdf").write_bytes(b"this is not a PDF at all")
        (folder / "pdfjs").mkdir()
        for name in ("cmaps", "standard_fonts", "wasm", "iccs"):
            (folder / "pdfjs" / name).symlink_to(FRONTEND / "node_modules" / "pdfjs-dist" / name)
        web_port = _free_port()
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", web_port), functools.partial(_Handler, directory=str(folder))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--window-size=1920,1080",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                f"http://127.0.0.1:{web_port}/measure.html",
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
        if server:
            server.shutdown()
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def report() -> dict:
    return _run()


def test_the_rail_and_the_view_draw_a_pdf_without_the_browsers_viewer(report):
    assert report["frames"] == 0, report["frames"]


def test_until_the_first_page_stands_the_line_for_reading_stands(report):
    assert report["noteAtOnce"] == ENGLISH["nachricht"]["dokument_liest"], report["noteAtOnce"]
    assert report["rail"]["noteGone"] is True


def test_five_pages_stand_under_each_other_fitted_to_the_width_and_the_first_is_drawn(report):
    rail = report["rail"]
    assert rail["pages"] == 5 and rail["scrollable"] is True, rail
    assert abs(rail["firstWidth"] - rail["hostWidth"]) <= 1, rail
    assert rail["firstInk"] > 20, "the first page is blank"
    assert all(abs(height - rail["pageHeights"][0]) < 2 for height in rail["pageHeights"]), rail["pageHeights"]


def test_the_pages_roll_without_a_bar_and_wear_the_corners_of_their_holder(report):
    rail = report["rail"]
    assert rail["scrollbarWidth"] == "none" and rail["overflowY"] == "auto", rail
    assert rail["mask"] == "none", rail
    assert rail["radius"] == rail["holderRadius"] != "0px", rail


def test_the_text_of_a_page_can_be_marked(report):
    rail = report["rail"]
    assert rail["text"].startswith("Page number"), rail
    assert rail["textSelectable"] == "text" and rail["selected"] == rail["text"], rail


def test_the_view_over_the_window_draws_the_same_pages_and_far_pages_come_in_when_rolled_to(report):
    view = report["view"]
    assert view["pages"] == 5 and view["firstInk"] > 20 and view["scrollbarWidth"] == "none", view
    assert abs(view["firstWidth"] - view["hostWidth"]) <= 1, view
    assert view["lastInk"] > 20, "the last page was not drawn when it came into view"


def test_a_file_that_is_no_pdf_says_what_any_failure_says(report):
    assert report["broken"] == ENGLISH["fehler"]["allgemein"], report["broken"]


def test_the_tile_of_a_pdf_in_the_doc_folder_shows_its_first_page_without_the_shell(report):
    assert report["tile"]["src"].startswith("data:image/jpeg;base64"), report["tile"]
    assert report["tile"]["wide"] > 100, report["tile"]


def test_nothing_was_refused_or_failed_while_drawing(report):
    # The library needs neither eval nor WebAssembly, whatever the policy allows.
    assert [e for e in report["errors"] if "broken" not in e.lower() and "invalid" not in e.lower()] == [], report["errors"]


def test_silence_the_policy_of_the_page_keeps_its_workers_and_its_way_out():
    rule = inhaltssicherheit.REGEL
    assert "worker-src 'self' blob:" in rule and "connect-src 'self'" in rule

