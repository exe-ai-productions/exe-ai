"""The info mark in the head of the page Cronjobs, measured in a real browser.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome with
the answers of the service made up in the page (empty lists), on the page
Cronjobs and, for the silence probe, on the pages Memory and Instructions.
The head of the page Cronjobs carries exactly one mark, 14 by 14 px, 6 px
after the title and centred on its line; pressed, it shows its approved
sentence under the title, first in English, then (the catalogue switched) in
German. The heads of the other pages carry none. And what stays: a press on
the mark switches nothing and calls no route, and the title keeps its text.

The build of the harness links the built stylesheet, so every size probe
reads the real tokens.

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

# The approved sentence (English, German) of the page.
SENTENCE = (
    "Runs an agent on a schedule, for example every morning at 8:00.",
    "Startet einen Agenten nach Zeitplan, zum Beispiel jeden Morgen um 8:00 Uhr.",
)

SHELL = """<script>
  import SystemPrompt from %(page)r
</script>

<div id="frame" style="width: 1400px; height: 900px; position: relative;">
  <SystemPrompt offen={true} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import german from %(german)r
import { texte } from %(texts)r
import { zustand } from %(zustand)r

texte.sprache = 'en'
texte.katalog = english
window.calls = []
window.fetch = async (address, options = {}) => {
  const method = (options.method || 'GET').toUpperCase()
  if (method !== 'GET') window.calls.push(method + ' ' + String(address))
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const lists = ['/cronjobs', '/agents', '/skills', '/jobs', '/cronjobs/runs/all']
  return new Response(JSON.stringify(lists.includes(path) ? [] : {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
window.texte = texte
window.german = german
zustand.promptOffen = true
zustand.promptStart = %(start)r
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
const root = document.getElementById('frame')
const text = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim()
const round = (value) => Math.round(value * 10) / 10
for (let k = 0; k < 80 && !root.querySelector('.set-kopf h3'); k += 1) await wait(100)
await wait(600)
const marks = () => Array.from(root.querySelectorAll('.set-kopf .mark'))
const measure = (mark) => {
  const title = mark.closest('.set-kopf').querySelector('h3')
  const range = document.createRange()
  range.selectNodeContents(title)
  const name = range.getBoundingClientRect()
  const box = mark.getBoundingClientRect()
  return {
    title: text(title),
    width: round(box.width), height: round(box.height),
    gap: round(box.left - name.right),
    off: round(Math.abs(box.top + box.height / 2 - (name.top + name.height / 2))),
  }
}
const sentence = async () => {
  const mark = marks()[0]
  mark.click()
  await wait(80)
  const bubble = root.querySelector('.set-kopf .bubble')
  const found = {
    sentence: text(bubble),
    below: bubble ? bubble.getBoundingClientRect().top >= mark.getBoundingClientRect().bottom - 1 : false,
  }
  document.body.click()
  await wait(80)
  return found
}
const report = {}
report.count = marks().length
report.marks = marks().map(measure)
report.headings = root.querySelectorAll('.set-kopf h3').length
report.closedBubbles = root.querySelectorAll('.set-kopf .bubble').length
window.calls.length = 0
if (report.count) {
  report.english = await sentence()
  texte.sprache = 'de'
  texte.katalog = german
  await wait(100)
  report.german = await sentence()
}
report.calls = window.calls
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


def _run_case(start: str) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-cronjobs-page-info-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"page": "../../src/teile/SystemPrompt.svelte"},
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "german": "../../../app/locales/de.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "start": start,
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
def cronjobs() -> dict:
    return _run_case("cronjobs")


@pytest.fixture(scope="module")
def memory() -> dict:
    return _run_case("memory")


@pytest.fixture(scope="module")
def instructions() -> dict:
    return _run_case("system")


def test_the_head_of_the_cronjobs_page_has_one_mark_14_px_wide_6_px_after_the_title(cronjobs):
    assert cronjobs["count"] == 1, cronjobs
    mark = cronjobs["marks"][0]
    assert mark["title"] == "Cronjobs", mark
    assert mark["width"] == 14 and mark["height"] == 14, mark
    assert abs(mark["gap"] - 6) <= 0.5, mark
    assert mark["off"] <= 1, mark


def test_the_mark_shows_its_sentence_in_english_and_then_in_german_under_the_title(cronjobs):
    assert cronjobs["english"]["sentence"] == SENTENCE[0], cronjobs["english"]
    assert cronjobs["german"]["sentence"] == SENTENCE[1], cronjobs["german"]
    assert cronjobs["english"]["below"] and cronjobs["german"]["below"], cronjobs


def test_the_key_is_in_both_catalogues_with_the_approved_sentence():
    english = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    german = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    assert english["cronjobs"]["info_page"] == SENTENCE[0]
    assert german["cronjobs"]["info_page"] == SENTENCE[1]


def test_silence_the_heads_of_the_memory_and_instructions_pages_carry_no_mark(memory, instructions):
    for report in (memory, instructions):
        assert report["count"] == 0 and report["headings"] == 1, report


def test_silence_a_press_calls_nothing_and_the_closed_mark_shows_no_sentence(cronjobs):
    assert cronjobs["calls"] == [], cronjobs["calls"]
    assert cronjobs["closedBubbles"] == 0, cronjobs
