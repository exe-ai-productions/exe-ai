"""The key list of the tools file, as drawn: a field of card glass with a row for
each key, its name as the file writes it, and on the right ".env" with a check or
a cross.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome, with the
tools file made up in the page (the service is not asked): one key that is set,
one that is missing, and once a file without a key. The page reports: the field
on the card glass with an edge of 1 px in the colour of the field edge, radius
9, padding 0 and 16, 83 px high with two rows; every row 40 px high with 10 px between its parts, a line
of 1 px in the field edge between two rows; the dot with a disc of 10 px in a box
of 12 px; the name as `${NAME}` in the fixed face, 12 px, in the quiet ink;
".env" in 12 px, green with a green check where the key is set and red with a
red cross where it is missing, the sign 14 px and named for a reader that cannot
see. And what stays: without a key in the file there is no block.

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
import english from %(english)r
import { zustand } from %(zustand)r
import { texte } from %(texts)r

texte.sprache = 'en'
texte.katalog = english
const answers = {
  '/dateien/zugangsdaten': { inhalt: 'KEY=value', kaputt: null },
  '/tools/config': {
    content: '{}', kaputt: null,
    platzhalter: [{ name: 'BRAVE_API_KEY', gesetzt: true }, { name: 'OTHER_KEY', gesetzt: false }],
  },
  '/agents': [], '/agent-files': [], '/skills': [], '/cronjobs': [], '/jobs': [], '/tools': [], '/werkzeuge': [],
}
window.__answers = answers
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
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const probe = (token, property = 'color') => {
  const node = document.createElement('i')
  node.style[property] = `var(${token})`
  document.body.appendChild(node)
  const value = getComputedStyle(node)[property]
  node.remove()
  return value
}
const open = async (keys) => {
  window.__zustand.promptStart = 'zugangsdaten'
  await wait(600)
  window.__answers['/tools/config'].platzhalter = keys
  window.__zustand.promptStart = 'tools_datei'
  for (let k = 0; k < 80; k += 1) {
    await wait(100)
    const field = document.querySelector('.editorboden textarea')
    if (field && field.value.startsWith('{}') && (keys.length ? document.querySelector('.keys') : !document.querySelector('.keys'))) break
    if (k === 79) throw new Error('the tools file did not show')
  }
  await wait(500)
}
await open([{ name: 'BRAVE_API_KEY', gesetzt: true }, { name: 'OTHER_KEY', gesetzt: false }])
const card = document.querySelector('.keys-card')
const look = getComputedStyle(card)
report.card = {
  ground: look.backgroundColor, glass: probe('--glass-card', 'backgroundColor'),
  edge: probe('--feldstrich'), edgeWidth: look.borderTopWidth, edgeColour: look.borderTopColor,
  height: card.getBoundingClientRect().height, radius: look.borderTopLeftRadius,
  padding: [look.paddingTop, look.paddingRight, look.paddingBottom, look.paddingLeft].join(' '),
}
report.rows = Array.from(card.querySelectorAll('.key-row')).map((row, index) => {
  const rowLook = getComputedStyle(row)
  const dot = row.querySelector('svg.lp')
  const disc = dot.querySelector('circle.scheibe')
  const name = row.querySelector('.key-name')
  const nameLook = getComputedStyle(name)
  const state = row.querySelector('.key-state')
  const stateLook = getComputedStyle(state)
  const sign = row.querySelector('.key-sign')
  const signSvg = sign.querySelector('svg')
  return {
    height: row.getBoundingClientRect().height,
    border: rowLook.borderTopWidth, borderColour: rowLook.borderTopColor,
    dot: { box: dot.getBoundingClientRect().width, disc: Math.round(parseFloat(disc.getAttribute('r')) * 2),
           colour: dot.getAttribute('data-farbe') },
    dotToName: px(name.getBoundingClientRect().left - dot.getBoundingClientRect().right),
    name: { text: name.textContent.trim(), family: nameLook.fontFamily, fixed: probe('--schrift-fest', 'fontFamily'),
            size: px(nameLook.fontSize), ink: nameLook.color, quiet: probe('--text-leise') },
    state: { text: state.textContent.replace(/\s+/g, ' ').trim(), size: px(stateLook.fontSize), ink: stateLook.color,
             signInk: getComputedStyle(sign).color, set: state.classList.contains('set') },
    sign: { width: signSvg.getBoundingClientRect().width, label: sign.getAttribute('aria-label'), role: sign.getAttribute('role') },
  }
})
report.tokens = {
  greenText: probe('--gruen-text'), redText: probe('--rot-text'), green: probe('--gruen'), red: probe('--rot'),
}
await open([])
report.empty = { keys: document.querySelectorAll('.keys').length, live: document.querySelectorAll('.lese').length }
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1100px; position: relative; }</style>
%(links)s
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


async def _drive(port: int, limit: float = 180.0) -> dict:
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
                response = json.loads(await asyncio.wait_for(connection.recv(), max(1.0, end - time.monotonic())))
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
    folder = FRONTEND / "node_modules" / f".harness-tool-keys-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"page": "../../src/teile/SystemPrompt.svelte"}, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {
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
        (folder / "measure.html").write_text(PAGE % {"cases": CASES, "links": links}, encoding="utf-8")
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


def test_the_list_is_a_field_of_card_glass_with_the_field_edge_and_padding_as_drawn(measured):
    card = measured["card"]
    assert card["ground"] == card["glass"], card
    assert card["edgeWidth"] == "1px" and card["edgeColour"] == card["edge"], card
    # Two rows, the line between them, and the edge above and below: 83 px as drawn.
    assert card["height"] == 83, card
    assert card["radius"] == "9px" and card["padding"] == "0px 16px 0px 16px", card


def test_every_row_is_40_px_high_and_two_rows_have_a_line_of_the_field_edge_between_them(measured):
    first, second = measured["rows"]
    assert first["height"] == 40 and first["border"] == "0px", first
    assert second["height"] == 41 and second["border"] == "1px", second
    assert second["borderColour"] == measured["card"]["edge"], second


def test_the_dot_is_a_disc_of_10_px_in_a_box_of_12_px_and_the_name_stands_10_px_behind_it(measured):
    for row, colour in zip(measured["rows"], ("gruen", "rot"), strict=True):
        assert row["dot"] == {"box": 12, "disc": 10, "colour": colour}, row["dot"]
        assert abs(row["dotToName"] - 10) <= 0.5, row["dotToName"]


def test_the_name_stands_as_the_file_writes_it_in_the_fixed_face_in_the_quiet_ink(measured):
    first, second = (row["name"] for row in measured["rows"])
    assert first["text"] == "${BRAVE_API_KEY}" and second["text"] == "${OTHER_KEY}", (first, second)
    for name in (first, second):
        assert name["family"] == name["fixed"] and name["size"] == 12 and name["ink"] == name["quiet"], name


def test_silence_the_word_stays_the_file_green_with_a_check_and_red_with_a_cross(measured):
    first, second = (row["state"] for row in measured["rows"])
    tokens = measured["tokens"]
    assert first["text"] == ".env" and second["text"] == ".env", (first, second)
    assert first["size"] == 12 and first["ink"] == tokens["greenText"] and first["signInk"] == tokens["green"], first
    assert second["size"] == 12 and second["ink"] == tokens["redText"] and second["signInk"] == tokens["red"], second
    assert first["set"] and not second["set"]


def test_silence_the_sign_is_14_px_and_says_its_state_to_a_reader_that_cannot_see(measured):
    first, second = (row["sign"] for row in measured["rows"])
    assert first["width"] == 14 and second["width"] == 14, (first, second)
    assert first["role"] == "img" and second["role"] == "img"
    assert first["label"] and second["label"] and first["label"] != second["label"], (first, second)


def test_silence_without_a_key_in_the_file_there_is_no_block_and_the_live_part_stays(measured):
    assert measured["empty"] == {"keys": 0, "live": 1}, measured["empty"]
