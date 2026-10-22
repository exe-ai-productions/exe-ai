"""A table wider than the answer scrolls for itself and shows a thin bar while
the pointer is over it, in a real browser.

`Nachricht.svelte` is built as shipped and drawn in headless Chrome with an
answer that holds a table of six columns with long cells in a column of 564
px, and a narrow table of two. The pointer is moved over the table with a real
mouse event (the debug port), so ``:hover`` is the browser's own. Measured:

* the wide table is wider than its surface and scrolls on its own, the narrow
  one needs no bar;
* with no pointer over it the bar is invisible (the house rule: no visible
  scrollbars), with the pointer over it a thin bar of the line colour stands;
* a horizontal wheel turn moves the table's ``scrollLeft`` on;
* a word in a cell is never broken in the middle of the word.

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

TABLE = "\n".join([
    "| Name | Description | Version | Status | Maintainer | Notes |",
    "| --- | --- | --- | --- | --- | --- |",
    *[
        f"| module_{k}_configuration_service | description_of_what_the_module_does_{k} | version_1_{k}_0_stable "
        f"| status_stable_and_supported | maintainer_platform_team_company | notes_page_for_details_{k}_long |"
        for k in range(3)
    ],
])
SMALL = "| a | b |\n| --- | --- |\n| 1 | 2 |"

CASES = r"""
const report = {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const scene = window.scene
const tables = () => Array.from(document.querySelectorAll('.antwort table'))
const ink = (variable) => {
  const probe = document.createElement('span')
  probe.style.color = 'var(' + variable + ')'
  document.body.appendChild(probe)
  const colour = getComputedStyle(probe).color
  probe.remove()
  return colour
}

scene.nachricht = {
  id: 'm1', rolle: 'assistant', content: %(content)s,
  abschnitte: [{ art: 'content', text: %(content)s }], werkzeuge: [], stats: {},
}
for (let k = 0; k < 100 && tables().length < 2; k += 1) await wait(100)
await wait(400)

const [wide, narrow] = tables()
const box = (node) => { const r = node.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height } }
const colours = (node) => getComputedStyle(node).scrollbarColor
report.wide = {
  box: box(wide), scrollWidth: wide.scrollWidth, clientWidth: wide.clientWidth,
  width: getComputedStyle(wide).scrollbarWidth, atRest: colours(wide),
  hyphens: getComputedStyle(wide.querySelector('td')).hyphens,
  wrap: getComputedStyle(wide.querySelector('td')).overflowWrap,
}
report.narrow = { scrollWidth: narrow.scrollWidth, clientWidth: narrow.clientWidth }
report.ink = { line: ink('--linie') }
// The row of the page under the table: the pointer is not over the table there.
report.outside = colours(narrow)

// Hand over to the driver: the pointer goes over the wide table.
const middle = { x: Math.round(report.wide.box.left + report.wide.box.width / 2), y: Math.round(report.wide.box.top + report.wide.box.height / 2) }
document.getElementById('koordinaten').textContent = JSON.stringify(middle)
while (!window.__hovered) await wait(50)
await wait(500)
report.hover = { over: wide.matches(':hover'), colours: colours(wide) }
report.scrollBefore = wide.scrollLeft
window.__measured = true
while (!window.__wheeled) await wait(50)
await wait(400)
report.scrollAfter = wide.scrollLeft

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>table</title>
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
    """Moves the real pointer over the table when the page asks for it, turns
    the wheel sideways once it has measured the hover, and reads the report."""
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

        middle = None
        while time.monotonic() < end and not middle:
            middle = await read("document.getElementById('koordinaten')?.textContent || ''")
            if not middle:
                await asyncio.sleep(0.25)
        assert middle, "the page never asked for the pointer"
        spot = json.loads(middle)
        await call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": spot["x"], "y": spot["y"]})
        await read("window.__hovered = true")
        while time.monotonic() < end and not await read("window.__measured === true"):
            await asyncio.sleep(0.25)
        await call("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": spot["x"], "y": spot["y"], "deltaX": 240, "deltaY": 0,
        })
        await read("window.__wheeled = true")
        while time.monotonic() < end:
            value = await read("document.getElementById('ergebnis')?.textContent || ''")
            if value:
                return value
            await asyncio.sleep(0.25)
    return ""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-table-{uuid4().hex}"
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
        content = json.dumps(TABLE + "\n\nBetween the two tables.\n\n" + SMALL)
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES % {"content": content}}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=900,1400", f"--remote-debugging-port={port}",
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


def test_a_table_wider_than_the_answer_scrolls_on_its_own(report):
    wide = report["wide"]
    assert wide["scrollWidth"] > wide["clientWidth"] + 100


def test_a_narrow_table_needs_no_bar(report):
    narrow = report["narrow"]
    assert narrow["scrollWidth"] <= narrow["clientWidth"]


def test_without_the_pointer_the_bar_is_invisible(report):
    wide = report["wide"]
    assert wide["width"] == "thin"
    assert wide["atRest"] == "rgba(0, 0, 0, 0) rgba(0, 0, 0, 0)"
    assert report["outside"] == "rgba(0, 0, 0, 0) rgba(0, 0, 0, 0)"


def test_with_the_pointer_over_the_table_a_thin_bar_of_the_line_colour_stands(report):
    hover = report["hover"]
    assert hover["over"] is True
    assert hover["colours"] == report["ink"]["line"] + " rgba(0, 0, 0, 0)"


def test_a_sideways_wheel_turn_moves_the_table_on(report):
    assert report["scrollAfter"] > report["scrollBefore"]


def test_a_cell_still_never_breaks_in_the_middle_of_a_word(report):
    wide = report["wide"]
    assert wide["wrap"] == "normal"
    assert wide["hyphens"] == "auto"
