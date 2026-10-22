"""Task boxes, deep headings and quotes of several paragraphs, in a real browser.

`Nachricht.svelte` is built as shipped and drawn in headless Chrome with an
answer that holds a task list (open, ticked, nested), a heading of five
hashes beside one of four, a quote of two paragraphs and a quote of one. The
pointer is moved over the first box and pressed with a real mouse event (the
debug port). Measured:

* the boxes stand in front of their text, locked, ticked where the item says
  x, and a press on one changes nothing;
* the heading of five hashes is drawn exactly as the one of four;
* the two paragraphs of a quote stand apart inside one quote, and the quote
  ends flush under the last one;
* a quote of one paragraph is as high as it was before the change (a line of
  the answer's text and the quote's own padding);
* a bracket in the middle of a sentence is still text.

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

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import Nachricht from '../../src/teile/Nachricht.svelte'
  import { scene } from './scene.svelte.js'
</script>

<div style="width: 564px; margin: 0 auto;">
  <Nachricht
    nachricht={scene.nachricht}
    laeuft={false}
    istLetzte={true}
    marke={null}
    neuErzeugen={() => {}}
    neuSenden={() => {}}
  />
</div>
"""

SCENE_JS = """export const scene = $state({ nachricht: { id: 'm1', rolle: 'assistant', content: '' } })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import '../../src/stil/global.css'

window.scene = scene
mount(Shell, { target: document.getElementById('root') })
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

CONTENT = "\n".join([
    "A note before the list, with [x] in the middle of a sentence.",
    "",
    "- [ ] open task",
    "- [x] done task",
    "  - [ ] nested task",
    "",
    "#### Four hashes",
    "",
    "##### Five hashes",
    "",
    "> first paragraph of the quote",
    ">",
    "> second paragraph of the quote",
    "",
    "Between the two quotes.",
    "",
    "> a quote of one paragraph",
])

CASES = r"""
const report = {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const scene = window.scene
const answer = () => document.querySelector('.antwort')

scene.nachricht = {
  id: 'm1', rolle: 'assistant', content: %(content)s,
  abschnitte: [{ art: 'content', text: %(content)s }], werkzeuge: [], stats: {},
}
for (let k = 0; k < 100 && !document.querySelector('.antwort blockquote'); k += 1) await wait(100)
await wait(400)

const box = (node) => { const r = node.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, height: r.height } }
const boxes = Array.from(answer().querySelectorAll('input[type=checkbox]'))
report.boxes = boxes.map((input) => ({
  disabled: input.disabled, checked: input.checked, inItem: input.parentElement.tagName,
  before: input.parentElement.textContent.trim(),
}))
report.sentence = answer().querySelector('p').textContent
report.nestedUnder = boxes.length > 2 ? boxes[2].closest('ul').parentElement.tagName : null

const four = answer().querySelector('h5')
const heads = Array.from(answer().querySelectorAll('h5'))
const look = (node) => {
  const s = getComputedStyle(node)
  return [s.fontSize, s.fontWeight, s.marginTop, s.marginBottom, s.letterSpacing].join('|')
}
report.heads = heads.map((h) => ({ text: h.textContent, look: look(h) }))

const quotes = Array.from(answer().querySelectorAll('blockquote'))
report.quotes = quotes.length
const two = quotes[0]
const paragraphs = Array.from(two.querySelectorAll(':scope > p'))
report.two = {
  paragraphs: paragraphs.length,
  gap: paragraphs.length === 2 ? box(paragraphs[1]).top - box(paragraphs[0]).bottom : 0,
  endGap: paragraphs.length ? box(two).bottom - box(paragraphs[paragraphs.length - 1]).bottom : null,
  startGap: paragraphs.length ? box(paragraphs[0]).top - box(two).top : null,
  paddingBottom: parseFloat(getComputedStyle(two).paddingBottom),
  paddingTop: parseFloat(getComputedStyle(two).paddingTop),
}
const one = quotes[quotes.length - 1]
report.one = {
  height: box(one).height, paragraphs: one.querySelectorAll('p').length,
  lineHeight: parseFloat(getComputedStyle(one).lineHeight), text: one.textContent,
  padding: parseFloat(getComputedStyle(one).paddingTop) + parseFloat(getComputedStyle(one).paddingBottom),
}

// Hand over to the driver: a real press on the first box.
const spot = boxes.length ? box(boxes[0]) : box(answer())
document.getElementById('koordinaten').textContent = JSON.stringify({
  x: Math.round((spot.left + spot.right) / 2), y: Math.round((spot.top + spot.bottom) / 2),
})
while (!window.__pressed) await wait(50)
await wait(300)
report.after = boxes.map((input) => input.checked)

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>tasks</title>
<style>body { margin: 0; background: #fff; }</style>
<div id="root"></div><pre id="ergebnis"></pre><pre id="koordinaten"></pre>
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 120.0) -> str:
    """Presses the real pointer on the first box when the page asks for it,
    and reads the report."""
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

        async def call(method: str, params: dict) -> dict:
            nonlocal number
            number += 1
            await connection.send(json.dumps({"id": number, "method": method, "params": params}))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response

        async def read(expression: str):
            answer = await call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
            return answer.get("result", {}).get("result", {}).get("value", "")

        spot = None
        while time.monotonic() < end and not spot:
            spot = await read("document.getElementById('koordinaten')?.textContent || ''")
            if not spot:
                await asyncio.sleep(0.25)
        assert spot, "the page never asked for the pointer"
        point = json.loads(spot)
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            await call("Input.dispatchMouseEvent", {
                "type": kind, "x": point["x"], "y": point["y"], "button": "left", "clickCount": 1,
            })
        await read("window.__pressed = true")
        while time.monotonic() < end:
            value = await read("document.getElementById('ergebnis')?.textContent || ''")
            if value:
                return value
            await asyncio.sleep(0.25)
    return ""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-tasks-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES % {"content": json.dumps(CONTENT)}}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1920,1080", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
        assert raw, "the page reported nothing"
        result = json.loads(raw)
        assert "failure" not in result, result["failure"]
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_boxes_stand_in_front_of_their_text_locked_and_ticked_where_the_item_says_x(report):
    boxes = report["boxes"]
    assert [b["checked"] for b in boxes] == [False, True, False]
    assert all(b["disabled"] and b["inItem"] == "LI" for b in boxes)
    assert [b["before"].startswith(text) for b, text in zip(boxes, ("open task", "done task", "nested task"), strict=True)] == [True] * 3
    assert report["nestedUnder"] == "LI"


def test_a_press_on_a_box_changes_nothing(report):
    assert report["after"] == [False, True, False]


def test_a_bracket_in_the_middle_of_a_sentence_stays_text(report):
    assert "[x] in the middle" in report["sentence"]


def test_the_heading_of_five_hashes_is_drawn_like_the_one_of_four(report):
    heads = report["heads"]
    assert [h["text"] for h in heads] == ["Four hashes", "Five hashes"]
    assert heads[0]["look"] == heads[1]["look"]


def test_the_two_paragraphs_of_a_quote_stand_apart_inside_one_quote(report):
    two = report["two"]
    assert report["quotes"] == 2
    assert two["paragraphs"] == 2
    assert two["gap"] >= 8, two


def test_a_quote_of_several_blocks_ends_flush_under_the_last_one(report):
    two = report["two"]
    assert abs(two["endGap"] - two["paddingBottom"]) <= 0.5, two
    assert abs(two["startGap"] - two["paddingTop"]) <= 0.5, two


def test_a_quote_of_one_paragraph_is_as_high_as_it_was(report):
    one = report["one"]
    assert one["paragraphs"] == 0
    assert one["text"] == "a quote of one paragraph"
    # One line of the answer's text and the quote's own padding, nothing else
    # (the same at HEAD, where the quote reads no blocks).
    assert abs(one["height"] - (one["lineHeight"] + one["padding"])) <= 0.5, one
