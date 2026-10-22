"""The large text fields wear the field of the house, measured in a real browser.

Every big text area — the instruction, the memory, the credentials, the
configuration and the tools file on the settings pages, and the fields of the
server windows and the job window (`WachsendesFeld.svelte`) — is the glass of
the cards (`--glass-card`, as the tool rows carry it) with the outline of the
other fields and a radius of 9, in the looks Exe and Pearl. The
outline stays while one writes in it; the glass lightens. A suspended field
stays dimmed, and the box is as high with the cursor in it as without.

`SystemPrompt.svelte` and the field itself in the forms the windows use are built
as shipped and drawn in headless Chrome with the answers of the service made up
in the page. Skipped where there is no Chrome or no node, like the other
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
  import WachsendesFeld from %(field)r

  let { offen = true } = $props()
  let one = $state('A line of text.')
  let two = $state('Another line.')
  let three = $state('A third one.')
  let four = $state('{}')
</script>

<div id="frame" style="width: 1100px; height: 800px; position: relative;">
  <SystemPrompt {offen} />
</div>
<!-- The field in the forms the windows give it: the server windows' instruction
     (knapp), the job window's (volleHoehe), a source view, a dimmed one. -->
<div id="forms" style="width: 700px; display: flex; flex-direction: column; gap: 12px; padding: 12px;">
  <div class="form-knapp"><WachsendesFeld knapp zeilen={3} bind:wert={one} beschriftung="one" /></div>
  <div class="form-hoch" style="height: 120px; display: flex; flex-direction: column;"><WachsendesFeld volleHoehe bind:wert={two} beschriftung="two" /></div>
  <div class="form-quelle"><WachsendesFeld quelle bind:wert={four} beschriftung="four" /></div>
  <div class="form-gedimmt"><WachsendesFeld gedimmt bind:wert={three} beschriftung="three" /></div>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { zustand } from %(zustand)r

const longText = Array.from({ length: 30 }, (_, line) => 'key_' + line + ': value_' + line).join('\\n')
const answers = {
  '/dateien/zugangsdaten': { inhalt: 'TEST_KEY=value\\nOTHER_KEY=value', kaputt: null },
  '/dateien/konfiguration': { inhalt: longText, kaputt: null },
  '/tools/config': { content: '{}', kaputt: null, platzhalter: [] },
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
zustand.promptStart = 'system'
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
const OWN = { system: 'A short instr', memory: 'A short note', zugangsdaten: 'TEST_KEY', konfiguration: 'key_0', tools_datei: '{}' }
const probe = document.createElement('span')
document.body.appendChild(probe)
const resolved = (property, variable) => {
  probe.style.cssText = (property === 'border-color' ? 'border: 1px solid ' : 'background-color: ') + 'var(' + variable + ');'
  const style = getComputedStyle(probe)
  return property === 'border-color' ? style.borderTopColor : style.backgroundColor
}
const styleOf = (box) => {
  const s = getComputedStyle(box)
  return {
    width: s.borderTopWidth, style: s.borderTopStyle, color: s.borderTopColor,
    background: s.backgroundColor, radius: s.borderTopLeftRadius, opacity: s.opacity,
    height: box.getBoundingClientRect().height,
  }
}
for (const look of ['dunkel', 'hell']) {
  document.documentElement.setAttribute('data-modus', look)
  await wait(150)
  report[look] = { outline: resolved('border-color', '--feldstrich'), glass: resolved('background-color', '--glass-card'), pages: {}, forms: {} }
  for (const page of Object.keys(OWN)) {
    window.__zustand.promptStart = page
    let box = null
    for (let k = 0; k < 80; k += 1) {
      await wait(100)
      box = document.querySelector('.editorboden .feld')
      const area = box && box.querySelector('textarea')
      if (area && area.value.startsWith(OWN[page])) break
    }
    await wait(300)
    const area = box.querySelector('textarea')
    area.blur()
    await wait(200)
    const resting = styleOf(box)
    area.focus()
    await wait(350)
    report[look].pages[page] = { resting, focused: styleOf(box) }
    area.blur()
  }
  for (const form of ['knapp', 'hoch', 'quelle', 'gedimmt']) {
    const box = document.querySelector('.form-' + form + ' .feld')
    const area = box.querySelector('textarea')
    const resting = styleOf(box)
    area.focus()
    await wait(350)
    report[look].forms[form] = { resting, focused: styleOf(box) }
    area.blur()
  }
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/%(style)s">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1400px; position: relative; }</style>
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
    folder = FRONTEND / "node_modules" / f".harness-text-area-frame-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL
            % {
                "page": "../../src/teile/SystemPrompt.svelte",
                "field": "../../src/teile/WachsendesFeld.svelte",
            }, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {
                "global": "../../src/stil/global.css",
                "zustand": "../../src/lib/zustand.svelte.js",
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
        # The build writes the sheet of the global styles beside the script.
        style = next((folder / "out").glob("*.css")).name
        (folder / "measure.html").write_text(PAGE % {"cases": CASES, "style": style}, encoding="utf-8")
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


LOOKS = ("dunkel", "hell")
PAGES = ("system", "memory", "zugangsdaten", "konfiguration", "tools_datei")
FORMS = ("knapp", "hoch", "quelle", "gedimmt")


def _boxes(measured: dict, look: str):
    for page in PAGES:
        yield f"page {page}", measured[look]["pages"][page]
    for form in FORMS:
        yield f"form {form}", measured[look]["forms"][form]


@pytest.mark.parametrize("look", LOOKS)
def test_every_large_text_area_wears_the_field_outline(measured, look):
    outline, glass = measured[look]["outline"], measured[look]["glass"]
    assert outline != "rgba(0, 0, 0, 0)", "the outline of the field resolves to a colour"
    for name, states in _boxes(measured, look):
        resting = states["resting"]
        assert resting["width"] == "1px" and resting["style"] == "solid", (look, name, resting)
        assert resting["color"] == outline, (look, name, resting)
        assert resting["background"] == glass, (look, name, resting)
        assert resting["radius"] == "9px", (look, name, resting)


@pytest.mark.parametrize("look", LOOKS)
def test_with_the_cursor_in_the_field_the_outline_stays_and_the_glass_changes(measured, look):
    outline = measured[look]["outline"]
    for name, states in _boxes(measured, look):
        resting, focused = states["resting"], states["focused"]
        assert focused["color"] == outline and focused["width"] == "1px", (look, name, focused)
        assert focused["background"] != resting["background"], (look, name)
        # The box is as high with the cursor in it as without.
        assert abs(focused["height"] - resting["height"]) <= 1, (look, name)


@pytest.mark.parametrize("look", LOOKS)
def test_silence_the_suspended_field_stays_dimmed_and_the_others_are_not(measured, look):
    forms = measured[look]["forms"]
    assert forms["gedimmt"]["resting"]["opacity"] == "0.35"
    for name in ("knapp", "hoch", "quelle"):
        assert forms[name]["resting"]["opacity"] == "1", name


def test_the_two_looks_draw_the_outline_in_their_own_colour(measured):
    assert measured["dunkel"]["outline"] != measured["hell"]["outline"]


def test_the_phone_text_pages_wear_the_same_field():
    source = (FRONTEND / "src" / "phone" / "settings" / "TextFile.svelte").read_text(encoding="utf-8")
    rule = source.split("<style>", 1)[1].split(".text {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid var(--feldstrich)" in rule and "background: var(--glass-card)" in rule
    assert "border-radius: 9px" in rule
    focus = source.split(".text:focus {", 1)[1].split("}", 1)[0]
    assert "var(--glass-card)" in focus
    # Size and type stay: the height of the field and the 16 px that keeps the phone from zooming in.
    assert "min-height: 38dvh" in rule and "font: 16px/1.5 var(--schrift)" in rule


def test_the_lists_of_keys_and_of_live_values_wear_the_glass_of_the_cards():
    source = (FRONTEND / "src" / "teile" / "SystemPrompt.svelte").read_text(encoding="utf-8")
    rule = source.split("<style>", 1)[1].split(".keys-card,\n  .live-card {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid var(--feldstrich)" in rule and "border-radius: 9px" in rule
    assert "background: var(--glass-card)" in rule and "--glass-button" not in rule
