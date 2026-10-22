"""The waiting bubble and the sent bubble, measured in a real browser.

`Warteblasen.svelte` and `Nachricht.svelte` are built as they are shipped,
together with a tiny page of their own that stands them in the history's track
(a column with the gap the history has, each block in a flex column) and draws
them in headless Chrome. The page reports what the layout says:

* the text of the waiting bubble and the text of the sent bubble stand at the
  same place — the same width, the same left edge, the same top of the text,
  and a block of the same height with the row under the bubble of the same
  height (without the fix the waiting bubble was about 40 px higher in its
  block and the text jumped when the message went);
* a message out of the line comes in without moving and fills from the
  strength of the waiting bubble to full; an ordinary message stands at full
  strength at once (the probe that shows the measurement can see the fill).

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
  import Nachricht from %(nachricht)r
  import Warteblasen from %(warteblasen)r
  import { scene } from './scene.svelte.js'
</script>

<!-- The track of the history: a column with the gap of its own, every block a
     flex column (App.svelte, `.spur`). -->
<div class="spur" style="width: 640px; margin: 0 auto; display: flex; flex-direction: column; gap: 40px;">
  <div class="davor">Above</div>
  {#if scene.mode === 'waiting'}
    <Warteblasen takeBack={() => {}} />
  {:else}
    {#key scene.again}
      <div class:from-queue={scene.nachricht.fromQueue}>
        <Nachricht nachricht={scene.nachricht} istLetzteFrage={true} neuSenden={() => {}} />
      </div>
    {/key}
  {/if}
</div>
<style>
  .spur > :global(div) { display: flex; flex-direction: column; min-width: 0; }
</style>
"""

SCENE_JS = """export const scene = $state({
  mode: 'waiting', again: 0,
  nachricht: { id: 'm1', role: 'user', content: 'A short question that waits, and a second line of it to wrap around the bubble box when the width is small.' },
})
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { einreihen } from %(queue)r
import { zustand } from %(zustand)r
import %(global)r

window.scene = scene
window.einreihen = einreihen
window.zustand = zustand
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
const { scene, einreihen, zustand } = window
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const report = {}

// The first line of the text of a bubble: where its top stands on the screen.
const textTop = (bubble) => {
  const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  })
  const node = walker.nextNode()
  const range = document.createRange()
  range.selectNodeContents(node)
  return range.getClientRects()[0].top
}
const box = (el) => {
  const r = el.getBoundingClientRect()
  return { x: r.left, y: r.top, w: r.width, h: r.height }
}
const measure = (kind) => {
  const bubble = document.querySelector(kind === 'waiting' ? '.von-mir.waiting' : '.von-mir:not(.waiting)')
  const foot = document.querySelector(kind === 'waiting' ? '.zeile' : '.fuss.meine')
  const block = bubble.parentElement
  return { bubble: box(bubble), foot: box(foot), block: box(block), textTop: textTop(bubble) }
}

zustand.aktiverChat = 'c1'
einreihen('c1', { inhalt: scene.nachricht.content })
await wait(300)
report.waiting = measure('waiting')

// The message goes: the line is empty, the sent bubble stands in its place.
scene.nachricht.fromQueue = true
scene.mode = 'gesendet'
// Zero time after the switch, then frame by frame while the entrance runs.
const tops = []
const opacities = []
for (let i = 0; i < 26; i += 1) {
  const bubble = document.querySelector('.von-mir:not(.waiting)')
  if (bubble) {
    tops.push(textTop(bubble))
    opacities.push(parseFloat(getComputedStyle(bubble.parentElement).opacity))
  }
  await wait(16)
}
await wait(300)
report.gesendet = measure('gesendet')
report.eintritt = { tops, opacities }

// Any other message: no fill, it stands at full strength from the first frame.
scene.nachricht = { ...scene.nachricht, id: 'm2', fromQueue: false }
scene.again += 1
const gewohnt = []
for (let i = 0; i < 12; i += 1) {
  const bubble = document.querySelector('.von-mir:not(.waiting)')
  if (bubble) gewohnt.push(parseFloat(getComputedStyle(bubble.parentElement).opacity))
  await wait(16)
}
report.gewohnt = { opacities: gewohnt }

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>wait</title>
<style>body { margin: 0; background: #fff; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  // The page's frame clock is a timer: headless Chrome on a machine without
  // a display does not deliver animation frames.
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


async def _read_result(port: int, limit: float = 120.0) -> str:
    """Wait until the page has written its report and read it over the debug
    port; the page's animations run on the browser's real clock."""
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
        while time.monotonic() < end:
            number += 1
            await connection.send(json.dumps({
                "id": number,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.getElementById('ergebnis')?.textContent || ''",
                           "returnByValue": True},
            }))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    break
            value = response.get("result", {}).get("result", {}).get("value", "")
            if value:
                return value
            await asyncio.sleep(0.25)
    return ""


def _measure(program: str, folder: Path, address: str) -> str:
    port = _free_port()
    browser = subprocess.Popen(
        [
            program,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-background-networking",
            "--allow-file-access-from-files",
            "--window-size=900,1000",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={folder / 'profile'}",
            address,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        return asyncio.run(_read_result(port))
    finally:
        prozessstopp.beenden(browser, frist=5)


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-wait-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL
            % {
                "nachricht": "../../src/teile/Nachricht.svelte",
                "warteblasen": "../../src/teile/Warteblasen.svelte",
            },
            encoding="utf-8",
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {
                "queue": "../../src/lib/warteschlange.svelte.js",
                "zustand": "../../src/lib/zustand.svelte.js",
                "global": "../../src/stil/global.css",
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
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        raw = _measure(program, folder, page.as_uri())
        assert raw, "the page reported nothing"
        scene = json.loads(raw)
        assert "failure" not in scene, scene["failure"]
        return scene
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_text_stands_at_the_same_place_before_and_after_the_message_goes(report):
    """The top of the text differs by nothing (without the fix: about 40 px),
    and the bubble has the same left edge and width."""
    waiting, gesendet = report["waiting"], report["gesendet"]
    assert abs(waiting["textTop"] - gesendet["textTop"]) <= 0.5, (waiting, gesendet)
    assert abs(waiting["bubble"]["x"] - gesendet["bubble"]["x"]) <= 0.5
    assert abs(waiting["bubble"]["w"] - gesendet["bubble"]["w"]) <= 0.5
    assert abs(waiting["bubble"]["h"] - gesendet["bubble"]["h"]) <= 0.5


def test_the_row_under_the_bubble_is_as_high_as_the_row_of_the_sent_one(report):
    waiting, gesendet = report["waiting"], report["gesendet"]
    assert abs(waiting["foot"]["y"] - gesendet["foot"]["y"]) <= 0.5, (waiting, gesendet)
    assert abs(waiting["foot"]["h"] - gesendet["foot"]["h"]) <= 0.5, (waiting, gesendet)
    assert abs(waiting["block"]["h"] - gesendet["block"]["h"]) <= 0.5, (waiting, gesendet)


def test_a_message_out_of_the_line_comes_in_without_moving(report):
    eintritt = report["eintritt"]
    assert len(eintritt["tops"]) >= 10, eintritt
    assert max(eintritt["tops"]) - min(eintritt["tops"]) <= 0.5, eintritt["tops"]
    # it fills from the strength of the waiting bubble to full
    assert eintritt["opacities"][0] <= 0.75, eintritt["opacities"]
    assert eintritt["opacities"][-1] == 1.0, eintritt["opacities"]


def test_any_other_message_stands_at_full_strength_at_once_the_probe_that_sees_the_fill(report):
    opacities = report["gewohnt"]["opacities"]
    assert len(opacities) >= 6, opacities
    assert min(opacities) == 1.0, opacities
