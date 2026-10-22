"""The head of the chosen model under the quick picker of "Local models": the
maker's mark in place of the cube, measured in a real browser.

`ModelleLokal.svelte` is built as shipped, with a sidebar column of its own,
and drawn in headless Chrome with the answers of the service made up in the
page: two local models, one with a known family (Qwen) and one without (a
name no family word is in). The page picks each in the quick picker and
reports, for the head under it: for the known family one mark of 30 px with
the same view box and the same paths as the row's own mark above, no tile
behind it and no cube beside it; for the other the cube on its 36 px tile and
no mark. And what stays: the name, the line under it with the context and the
framework, the state pill, and the marks of the quick picker's rows.

The build of the harness links the built stylesheet, so every colour and size
probe reads the real tokens.

Skipped where there is no Chrome or no node, like the other browser tests.
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
LOCALES = ROOT / "app" / "locales"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import ModelleLokal from %(local)r
  import { zustand } from %(zustand)r
</script>

<div style="display: flex; width: 1280px; height: 860px;">
  <nav id="leiste" style="width: 320px; flex: none; overflow: auto;">
    {#if zustand.menuSections}{@render zustand.menuSections.snippet?.()}{/if}
  </nav>
  <main id="seite" style="flex: 1; min-width: 0; overflow: auto; position: relative;">
    <ModelleLokal offen={true} />
  </main>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { zustand } from %(zustand)r
import { texte } from %(texts)r

texte.sprache = 'en'
texte.katalog = english
const base = { group: 'local', anbieter: 'runner', anbieter_name: 'Local', erreichbar: true, dialekt: 'llama_cpp',
  context_tokens: 32768, capabilities: {} }
const all = [
  { ...base, id: 'runner/qwen', modell: 'qwen', name: 'Qwen3-8B-Q4' },
  { ...base, id: 'runner/plain', modell: 'plain', name: 'zzzmodel-7b', anbieter_name: 'Mystery' },
]
zustand.modelle = all
window.fetch = async (address) => {
  const full = String(address)
  const path = full.replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path === '/models' ? all : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
window.zustand = zustand
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
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const page = () => document.getElementById('seite')
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
const look = (node) => getComputedStyle(node)
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const rows = () => Array.from(page().querySelectorAll('[role=row].line'))
for (let k = 0; k < 60 && rows().length !== 2; k += 1) await wait(100)
if (rows().length !== 2) throw new Error('the quick picker did not render its two rows')
await wait(600)
const rowOf = (name) => rows().find((row) => text(row.querySelector('.model')).includes(name))
const report = {}

const measure = async (name) => {
  const row = rowOf(name)
  const rowMark = row.querySelector('.logo svg')
  row.click()
  const headOf = () => Array.from(page().querySelectorAll('.kopf')).find((h) => text(h.querySelector('.titel')) === name)
  for (let k = 0; k < 40 && !headOf(); k += 1) await wait(100)
  await wait(200)
  const head = headOf()
  if (!head) throw new Error('no head under the quick picker for ' + name)
  const mark = head.querySelector('.marke')
  const markSvg = mark?.querySelector('svg')
  const tile = head.querySelector('.kachel')
  const box = mark?.getBoundingClientRect()
  return {
    title: text(head.querySelector('.titel')),
    under: text(head.querySelector('.unter')),
    pill: text(head.querySelector('.standpille, [class*=pille]')),
    mark: markSvg ? {
      width: Math.round(box.width), height: Math.round(box.height),
      viewBox: markSvg.getAttribute('viewBox'), markup: markSvg.innerHTML,
      background: look(mark).backgroundColor, svgWidth: markSvg.getAttribute('width'),
    } : null,
    rowMark: rowMark ? { viewBox: rowMark.getAttribute('viewBox'), markup: rowMark.innerHTML } : null,
    rowLetter: text(row.querySelector('.logo .letter')),
    tile: tile ? {
      width: Math.round(tile.getBoundingClientRect().width), height: Math.round(tile.getBoundingClientRect().height),
      background: look(tile).backgroundColor, sign: Boolean(tile.querySelector('svg')),
    } : null,
    marks: head.querySelectorAll('.marke').length, tiles: head.querySelectorAll('.kachel').length,
  }
}
report.known = await measure('Qwen3-8B-Q4')
report.unknown = await measure('zzzmodel-7b')
report.tileInk = (() => {
  const node = document.createElement('i')
  node.style.backgroundColor = 'var(--bg-erhoben)'
  document.body.appendChild(node)
  const value = getComputedStyle(node).backgroundColor
  node.remove()
  return value
})()
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
%(links)s
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; position: relative; }</style>
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


async def _drive(port: int, limit: float = 120.0) -> dict:
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


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-local-head-mark-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {
                "local": "../../src/teile/ModelleLokal.svelte",
                "zustand": "../../src/lib/zustand.svelte.js",
            },
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "texts": "../../src/lib/texte.svelte.js",
            },
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
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        assert links, "the build emitted no stylesheet: the colour probes would measure nothing"
        (folder / "measure.html").write_text(
            PAGE % {"cases": CASES, "links": links}, encoding="utf-8"
        )
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1280,900",
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


def test_the_head_of_a_model_of_a_known_family_wears_its_mark_in_30_px_without_a_tile(measured):
    head = measured["known"]
    assert head["marks"] == 1 and head["tiles"] == 0 and head["tile"] is None, head
    mark = head["mark"]
    assert mark["width"] == 30 and mark["height"] == 30 and mark["svgWidth"] == "30", mark
    assert mark["background"] in ("rgba(0, 0, 0, 0)", "transparent"), mark


def test_it_is_the_mark_the_row_of_the_quick_picker_above_finds(measured):
    head = measured["known"]
    assert head["rowMark"], head
    assert head["mark"]["viewBox"] == head["rowMark"]["viewBox"], head
    assert head["mark"]["markup"] == head["rowMark"]["markup"], head


def test_without_a_known_mark_the_cube_stays_on_its_tile(measured):
    head = measured["unknown"]
    assert head["mark"] is None and head["marks"] == 0 and head["tiles"] == 1, head
    tile = head["tile"]
    assert tile["width"] == 36 and tile["height"] == 36 and tile["sign"], tile
    assert tile["background"] == measured["tileInk"], tile
    assert head["rowLetter"] == "Z", head


def test_silence_name_line_and_state_of_the_head_are_as_before(measured):
    assert measured["known"]["title"] == "Qwen3-8B-Q4" and measured["unknown"]["title"] == "zzzmodel-7b"
    for head in (measured["known"], measured["unknown"]):
        assert head["under"] == "32.8k Context \u00b7 llama.cpp", head
        assert head["pill"] == "connected", head
