"""The text field of the credentials and the configuration down to the foot,
measured in a real browser.

On both pages the field fills the page: it ends 32 px above the foot with the
note, the cross and the save sign, and it grows and shrinks with the window.
The tools file stays a block (a field of 420 px) with the keys under it, and the system
prompt and the memory grow as before.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome, with
the files made up in the page (the service is not asked), in a frame 800 and
1100 px high. Skipped where there is no Chrome or no node, like the other
browser tests.
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
  import SystemPrompt from %(page)r

  let { offen = true } = $props()
</script>

<div id="frame" style="width: 1100px; height: 800px; position: relative;">
  <SystemPrompt {offen} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { zustand } from %(zustand)r

const longText = Array.from({ length: 90 }, (_, line) => 'key_' + line + ': value_' + line).join('\\n')
const answers = {
  '/dateien/zugangsdaten': { inhalt: 'TEST_KEY=value\\nOTHER_KEY=value', kaputt: null },
  '/dateien/konfiguration': { inhalt: longText, kaputt: null },
  '/tools/config': {
    content: '{}', kaputt: null,
    platzhalter: [{ name: 'BRAVE_API_KEY', gesetzt: true }, { name: 'OTHER_KEY', gesetzt: false }],
  },
  '/system-prompt': { text: 'A short instruction.' },
  '/gedaechtnis': { text: 'A short note.' },
  '/agents': [], '/skills': [], '/cronjobs': [], '/jobs': [],
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
zustand.promptOffen = true
zustand.promptStart = 'zugangsdaten'
window.__zustand = zustand
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
const box = (node) => {
  const r = node.getBoundingClientRect()
  return { top: r.top, bottom: r.bottom, height: r.height }
}
// What the page's own file starts with: the wait is over only once it shows.
const OWN = { zugangsdaten: 'TEST_KEY', konfiguration: 'key_0', tools_datei: '{}', system: 'A short instr', memory: 'A short note' }
for (const page of Object.keys(OWN)) {
  window.__zustand.promptStart = page
  report[page] = {}
  for (const height of [800, 1100, 420]) {
    document.getElementById('frame').style.height = height + 'px'
    let ground = null
    for (let k = 0; k < 80; k += 1) {
      await wait(100)
      ground = document.querySelector('.editorboden')
      const own = ground && ground.querySelector('textarea') && ground.querySelector('textarea').value.startsWith(OWN[page])
      const keysThere = page !== 'tools_datei' || ground?.parentElement.querySelector('.keys')
      if (own && keysThere) break
    }
    await wait(300)
    const field = ground.querySelector('textarea')
    const foot = ground.parentElement.querySelector('.fuss')
    const keys = ground.parentElement.querySelector('.keys')
    const scroller = document.querySelector('.inhalt')
    scroller.scrollTop = scroller.scrollHeight
    await wait(100)
    report[page][height] = {
      ground: box(ground),
      field: box(field),
      firstSign: box(foot.querySelector('.symbolknopf') || foot.querySelector('button')),
      foot: box(foot),
      keys: keys ? box(keys) : null,
      cssHeight: parseFloat(getComputedStyle(field).height),
      scroller: box(scroller),
      value: field.value.slice(0, 12),
    }
    scroller.scrollTop = 0
  }
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1100px; position: relative; }</style>
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
    folder = FRONTEND / "node_modules" / f".harness-credentials-field-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"page": "../../src/teile/SystemPrompt.svelte"}, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css", "zustand": "../../src/lib/zustand.svelte.js"},
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
        (folder / "measure.html").write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1100,1200",
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


FILE_PAGES = ("zugangsdaten", "konfiguration")


def _gap_to_foot(case: dict) -> float:
    """From the bottom of the field's ground to the top of the first sign.

    Measured on a page without a warning: the warning box of a faulty file
    stands between the field and the foot and takes its own room.
    """
    return case["firstSign"]["top"] - case["ground"]["bottom"]


@pytest.mark.parametrize("page", FILE_PAGES)
@pytest.mark.parametrize("height", ("800", "1100"))
def test_the_field_ends_32_px_above_the_foot(measured, page, height):
    case = measured[page][height]
    assert case["value"], "the file was not shown"
    assert abs(_gap_to_foot(case) - 32) <= 2, (page, height, _gap_to_foot(case))


@pytest.mark.parametrize("page", FILE_PAGES)
def test_the_field_grows_with_the_window(measured, page):
    low, high = measured[page]["800"], measured[page]["1100"]
    assert high["field"]["height"] - low["field"]["height"] >= 295, (page, low["field"], high["field"])
    # The foot stays in the picture at both heights, the field takes the room.
    assert low["foot"]["bottom"] <= 800 and high["foot"]["bottom"] <= 1100


@pytest.mark.parametrize("page", FILE_PAGES)
def test_in_a_short_window_the_field_keeps_its_floor_and_the_foot_can_be_reached(measured, page):
    case = measured[page]["420"]
    assert case["cssHeight"] >= 160 - 1, case["cssHeight"]
    # Scrolled to the end, the signs of the foot stand inside the scroll area.
    assert case["firstSign"]["bottom"] <= case["scroller"]["bottom"] + 1, case
    assert case["firstSign"]["top"] >= case["scroller"]["top"], case


def test_the_credentials_field_is_no_block(measured):
    assert measured["zugangsdaten"]["800"]["field"]["height"] > 400


def test_the_tools_file_stays_a_block_with_the_keys_under_it(measured):
    for height in ("800", "1100"):
        case = measured["tools_datei"][height]
        # The text area is 410 high: with 4 of padding and 1 of rim on both
        # sides the field of the page is 420, whatever the window.
        assert abs(case["cssHeight"] - 410) <= 1, (height, case["cssHeight"])
        assert case["keys"] and case["keys"]["top"] >= case["field"]["bottom"], case


@pytest.mark.parametrize("page", ("system", "memory"))
def test_silence_the_system_prompt_and_the_memory_keep_their_way_of_growing(measured, page):
    """They share the page with other blocks under the field, as before: the
    field takes the 300 px the window gained, and the gap to the foot stays
    the one those blocks leave."""
    low, high = measured[page]["800"], measured[page]["1100"]
    assert abs(high["field"]["height"] - low["field"]["height"] - 300) <= 2
    assert abs(_gap_to_foot(high) - _gap_to_foot(low)) <= 2
