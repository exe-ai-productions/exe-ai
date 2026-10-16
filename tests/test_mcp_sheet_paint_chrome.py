"""The server page of the settings, measured in a real browser: once the small
menu of a connected card is open, nothing paints the page black.

The page's content scroller wears a soft mask at its edges (`rollfade.js`).
The menu of a card and its click-away shield used to stand inside that
scroller, and in the app's own window the whole area under the first row of
cards turned black while the menu was open. The browser used for the test
paints it correctly either way (the fault shows only in the program's own
window), so two things are measured here:

* the cause, in the document: no element with `position: fixed` has an
  ancestor that wears a mask — the menu and its click-away shield stand at the
  page's root;
* the result, in the picture: the pixels under the first row of cards are not
  black, the menu is where the card's foot puts it, and the layers go away
  again when the shield is clicked.

`Menueseite.svelte` and `Verbindungen.svelte` are built as shipped, together
with a tiny page of their own, and drawn in headless Chrome. Skipped where
there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import base64
import io
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
  import Menueseite from %(page)r
  import Verbindungen from %(connections)r
</script>

<div style="width: 1200px; height: 680px; display: flex; flex-direction: column; position: relative;">
  <Menueseite offen={true} beschriftung="servers">
    {#snippet kopf()}<h2 style="margin: 0; height: 40px;">Servers</h2>{/snippet}
    {#snippet inhalt()}<Verbindungen zuWerkzeugen={() => {}} />{/snippet}
  </Menueseite>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r

const servers = [{
  name: 'websuche', enabled: true, laeuft: true, type: 'stdio',
  alle_werkzeuge: [{ name: 'search' }, { name: 'fetch' }], allowed_tools: [],
}]
const answers = { '/tools/servers': servers, '/tools/oauth/status': [] }
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
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
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const rectOf = (node) => {
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, bottom: r.bottom }
}
for (let k = 0; k < 60 && document.querySelectorAll('.galerie .card').length === 0; k += 1) await wait(100)
await wait(500)
const masked = (node) => {
  const style = getComputedStyle(node)
  return [style.maskImage, style.webkitMaskImage].some((v) => v && v !== 'none')
}
report.cards = document.querySelectorAll('.galerie .card').length
// The setting that makes the case: the page's scroller is masked.
report.scrollerMasked = Array.from(document.querySelectorAll('.inhalt')).some(masked)
const foot = document.querySelector('.galerie .card .state')
report.footFound = Boolean(foot)
foot.click()
await wait(500)
const menu = document.querySelector('.menue')
const shield = document.querySelector('.schirm')
report.menuOpen = Boolean(menu)
report.shieldOpen = Boolean(shield)
const fixedInsideMask = []
for (const node of document.querySelectorAll('*')) {
  if (getComputedStyle(node).position !== 'fixed') continue
  for (let up = node.parentElement; up; up = up.parentElement) {
    if (masked(up)) { fixedInsideMask.push(String(node.className)); break }
  }
}
report.fixedInsideMask = fixedInsideMask
report.menuRect = menu ? rectOf(menu) : null
report.footRect = rectOf(foot)
report.firstRowBottom = Math.max(...Array.from(document.querySelectorAll('.galerie .card')).slice(0, 3).map((n) => n.getBoundingClientRect().bottom))
const frame = document.querySelector('.rechts')
report.frameRect = frame ? rectOf(frame) : null
report.scrollerRect = rectOf(document.querySelector('.inhalt'))
report.viewport = [innerWidth, innerHeight]
// Everything the picture is taken of is on record; the layers go away on a click on the shield.
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
// The click on the shield is made after the picture, by a second call of the harness.
window.__closeShield = async () => {
  document.querySelector('.schirm')?.click()
  await wait(400)
  return {
    menus: document.querySelectorAll('.menue').length,
    shields: document.querySelectorAll('.schirm').length,
    layers: document.querySelectorAll('.menu-layer').length,
  }
}
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; height: 800px; position: relative; }</style>
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
    """Read the page's report over the debug port, take the picture of the
    open menu, then click the shield and read what is left."""
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

        async def call(method: str, **params):
            nonlocal number
            number += 1
            await connection.send(json.dumps({"id": number, "method": method, "params": params}))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response.get("result", {})

        async def value_of(expression: str, wait: bool = False):
            result = await call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=wait)
            return result.get("result", {}).get("value")

        raw = ""
        while time.monotonic() < end and not raw:
            raw = await value_of("document.getElementById('ergebnis')?.textContent || ''")
            if not raw:
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        shot = await call("Page.captureScreenshot", format="png")
        report["picture"] = shot["data"]
        report["after_click"] = await value_of("window.__closeShield()", wait=True)
        return report


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-mcp-sheet-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL
            % {
                "page": "../../src/teile/Menueseite.svelte",
                "connections": "../../src/teile/Verbindungen.svelte",
            },
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css"}, encoding="utf-8"
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [str(FRONTEND / "node_modules" / ".bin" / "vite"), "build", "--config", "vite.config.js"],
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
                "--window-size=1280,800",
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


def test_the_case_stands_a_masked_scroller_and_an_open_menu(report):
    assert report["cards"] >= 3
    assert report["scrollerMasked"], "the page's scroller must wear the scroll-fade mask for this case"
    assert report["menuOpen"] and report["shieldOpen"]


def test_no_fixed_layer_stands_inside_a_masked_scroller(report):
    assert report["fixedInsideMask"] == []


def test_the_menu_sits_under_the_foot_of_its_card(report):
    menu, foot = report["menuRect"], report["footRect"]
    assert abs(menu["y"] - (foot["bottom"] + 8)) < 2
    assert abs(menu["x"] - foot["x"]) < 2


def test_the_area_under_the_first_row_of_cards_is_not_black(report):
    image_module = pytest.importorskip("PIL.Image")
    picture = image_module.open(io.BytesIO(base64.b64decode(report["picture"]))).convert("RGB")
    scale = picture.width / report["viewport"][0]
    top = int(report["firstRowBottom"] * scale) + 2
    left = int(report["scrollerRect"]["x"] * scale)
    right = int((report["scrollerRect"]["x"] + report["scrollerRect"]["width"]) * scale)
    bottom = int(min(report["scrollerRect"]["bottom"], report["viewport"][1]) * scale)
    black = total = 0
    for y in range(top, bottom, 4):
        for x in range(left, right, 4):
            total += 1
            if max(picture.getpixel((x, y))) <= 6:
                black += 1
    assert total > 100
    assert black / total < 0.02, f"{black} of {total} samples are pure black"


def test_a_click_on_the_shield_takes_both_layers_away(report):
    assert report["after_click"] == {"menus": 0, "shields": 0, "layers": 0}
