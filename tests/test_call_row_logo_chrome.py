"""The call row of a server wears its logo, measured in a real browser.

`Nachricht.svelte` is built as shipped and drawn in headless Chrome with a
stored answer made up in the page: five calls, run by `github`, `searxng`, the
shipped search `websuche`, a server of one's own with a logo of its own, and a
built-in tool whose source is called `shell` — as is a server of one's own
that has a logo. In the open block the first four rows carry a mark of 14 x 14 px
behind the dot — three vectors and one image with an empty `alt` — and the
built-in tool carries none; the name of each stands one gap to the right of
what stands before it. Closed, no logo is drawn. Skipped where there is no
Chrome or no node, like the other browser tests.
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
  import Nachricht from %(nachricht)r
  import { scene } from './scene.svelte.js'
</script>

<div style="width: 640px; margin: 0 auto;">
  {#key scene.again}
    <Nachricht
      nachricht={scene.nachricht}
      laeuft={false}
      istLetzte={true}
      marke={null}
      neuErzeugen={() => {}}
      neuSenden={() => {}}
    />
  {/key}
</div>
"""

SCENE_JS = """export const scene = $state({ nachricht: { id: 'm1', rolle: 'assistant', content: '' }, again: 0 })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import %(global)r

const OWN_LOGO = 'data:image/svg+xml;utf8,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#c33"/></svg>')
const answers = {
  '/tools/servers': [{ name: 'ownserver', logo: OWN_LOGO }, { name: 'shell', logo: OWN_LOGO }],
  '/tools': { werkzeuge: [] },
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
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

CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const box = (node) => {
  const r = node.getBoundingClientRect()
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }
}
// The built-in tool names its source, and a server of one's own is called the same.
const servers = ['github', 'searxng', 'websuche', 'ownserver', 'shell']
const tools = ['search_code', 'web_search', 'read_webpage', 'own_tool', 'read_file']
const calls = servers.map((server, k) => ({
  aufruf_id: 'c' + k, name: tools[k], server, argumente: { query: 'lighthouse at dawn' },
  ergebnis: 'ok', fehlgeschlagen: false,
}))
scene.nachricht = {
  id: 'm1', rolle: 'assistant', content: 'x',
  abschnitte: [
    { art: 'content', text: 'I look things up. ' },
    ...calls.map((c) => ({ art: 'werkzeug', aufruf_id: c.aufruf_id })),
    { art: 'content', text: 'These are the results.' },
  ],
  werkzeuge: calls, stats: {},
}
await wait(800)
report.closed = {
  rows: document.querySelectorAll('.aufruf').length,
  logos: document.querySelectorAll('.call-logo').length,
  head: document.querySelectorAll('.block-head').length,
}
document.querySelector('.block-head').click()
await wait(500)
const window_ = document.querySelector('.block-window')
for (let k = 0; k < 40 && window_.style.overflow === 'hidden'; k += 1) {
  window_.getAnimations().forEach((a) => a.finish())
  await wait(50)
}
// The service answers for the server of one's own a moment after the first
// row asked for it: wait until its image is there.
for (let k = 0; k < 60 && !document.querySelector('.call-logo img'); k += 1) await wait(100)
await wait(300)
report.rows = Array.from(window_.querySelectorAll('.aufruf')).map((row) => {
  const logo = row.querySelector('.call-logo')
  return {
    name: row.querySelector('.wz-name').textContent.trim(),
    label: row.getAttribute('aria-label'),
    row: box(row),
    column: box(row.querySelector('.call-column')),
    logo: logo ? box(logo) : null,
    ariaHidden: logo ? logo.getAttribute('aria-hidden') : null,
    kind: logo ? (logo.querySelector('svg') ? 'svg' : logo.querySelector('img') ? 'img' : 'empty') : null,
    alt: logo && logo.querySelector('img') ? logo.querySelector('img').getAttribute('alt') : null,
    mark: logo ? box(logo.querySelector('svg, img')) : null,
    nameBox: box(row.querySelector('.wz-name')),
  }
})
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; }</style>
</head><body>
<div id="root"></div>
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
    folder = FRONTEND / "node_modules" / f".harness-call-row-logo-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"nachricht": "../../src/teile/Nachricht.svelte"}, encoding="utf-8"
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS % {"global": "../../src/stil/global.css"}, encoding="utf-8")
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
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=900,900",
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


WITH_LOGO = {"search_code": "svg", "web_search": "svg", "read_webpage": "svg", "own_tool": "img"}


def _row(measured: dict, name: str) -> dict:
    return next(row for row in measured["rows"] if row["name"] == name)


def test_closed_no_logo_is_drawn(measured):
    assert measured["closed"]["head"] == 1
    assert measured["closed"]["rows"] == 0 and measured["closed"]["logos"] == 0


@pytest.mark.parametrize("name", sorted(WITH_LOGO))
def test_a_server_row_carries_a_mark_of_14_pixels_behind_the_dot(measured, name):
    row = _row(measured, name)
    assert row["kind"] == WITH_LOGO[name], row
    assert abs(row["mark"]["width"] - 14) <= 0.5 and abs(row["mark"]["height"] - 14) <= 0.5, row["mark"]
    # One gap behind the dot's column, one gap before the name.
    assert abs(row["logo"]["left"] - row["column"]["right"] - 8) <= 1, row
    assert abs(row["nameBox"]["left"] - row["logo"]["right"] - 8) <= 1, row


def test_the_image_of_a_server_of_ones_own_is_decoration_for_the_reader(measured):
    row = _row(measured, "own_tool")
    assert row["alt"] == ""
    for name in WITH_LOGO:
        assert _row(measured, name)["ariaHidden"] == "true"


def test_a_built_in_tool_carries_no_mark_and_its_name_follows_the_dot(measured):
    row = _row(measured, "read_file")
    assert row["logo"] is None and row["kind"] is None
    assert abs(row["nameBox"]["left"] - row["column"]["right"] - 8) <= 1, row


def test_silence_the_rows_keep_their_height_and_their_label(measured):
    for row in measured["rows"]:
        assert abs(row["row"]["height"] - 19) <= 1, row
        assert row["name"] in row["label"], row
