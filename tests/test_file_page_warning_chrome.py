"""The warning box of a faulty file stands over the field, as drawn.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome, with
the files made up in the page (the service is not asked): the configuration
and the tools file, each once sound and once with the reason the service gives
for a faulty file, the credentials sound (the service never calls them faulty), and an agent's file
sound and faulty. The page reports, where a file of the two pages is faulty: the box
is the first thing in the content, before the field, 32 px above it; a red edge
of 1 px, no ground, radius 9, padding 12 and 16, the red dot of 10 px in a box of 12 px, the box 10 px
from the sentence, the sentence of 12.5 px in the quiet ink; the field starts
lower by the box and its gap and still ends 32 px above the foot. And what
stays: no box without a fault and the field where it was, the agent's file keeps
its box under the field with its own look, and the sentence of the file pages
names the file.

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

REASON = (
    'Invalid YAML: while scanning a simple key in "<unicode string>", line 3, column 3: port 8090 ^ '
    'could not find expected \':\' in "<unicode string>", line 4, column 3: language: de ^'
)

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
const longText = Array.from({ length: 90 }, (_, line) => 'key_' + line + ': value_' + line).join('\\n')
const answers = {
  '/dateien/zugangsdaten': { inhalt: 'TEST_KEY=value', kaputt: null },
  '/dateien/konfiguration': { inhalt: longText, kaputt: null },
  '/tools/config': { content: '{}', kaputt: null, platzhalter: [{ name: 'BRAVE_API_KEY', gesetzt: true }] },
  '/agents/broken': { content: 'name: broken', kaputt: null },
  '/system-prompt': { text: 'A short instruction.' },
  '/agents': [], '/skills': [], '/cronjobs': [], '/jobs': [],
}
window.__answers = answers
window.__reason = %(reason)s
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
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const probe = (token, property = 'color') => {
  const node = document.createElement('i')
  node.style[property] = `var(${token})`
  document.body.appendChild(node)
  const value = getComputedStyle(node)[property]
  node.remove()
  return value
}
const FILES = {
  konfiguration: { key: '/dateien/konfiguration', own: 'key_0', other: 'zugangsdaten' },
  tools_datei: { key: '/tools/config', own: '{}', other: 'zugangsdaten' },
  zugangsdaten: { key: '/dateien/zugangsdaten', own: 'TEST_KEY', other: 'konfiguration' },
  'agent:broken': { key: '/agents/broken', own: 'name: broken', other: 'zugangsdaten' },
}
const open = async (page, fault) => {
  // Leave for another page first, so the page reads its file anew.
  window.__zustand.promptStart = FILES[page].other
  await wait(600)
  window.__answers[FILES[page].key].kaputt = fault ? window.__reason : null
  window.__zustand.promptStart = page
  let ground = null
  for (let k = 0; k < 80; k += 1) {
    await wait(100)
    ground = document.querySelector('.editorboden')
    const field = ground && ground.querySelector('textarea')
    if (field && field.value.startsWith(FILES[page].own) && (!fault || document.querySelector('.warnung'))) break
    if (k === 79) throw new Error('the page ' + page + (fault ? ' (faulty)' : '') + ' did not show its file')
  }
  await wait(500)
  return ground
}
const measure = (ground) => {
  const content = document.querySelector('.breite')
  const field = ground.querySelector('textarea')
  const foot = content.querySelector('.fuss')
  const warning = content.querySelector('.warnung')
  const sign = foot.querySelector('.symbolknopf') || foot.querySelector('button')
  const out = {
    warnings: content.querySelectorAll('.warnung').length,
    groundTop: ground.getBoundingClientRect().top,
    groundBottom: ground.getBoundingClientRect().bottom,
    toFoot: sign.getBoundingClientRect().top - ground.getBoundingClientRect().bottom,
    first: content.firstElementChild === warning,
    value: field.value.slice(0, 12),
  }
  if (warning) {
    const box = warning.getBoundingClientRect()
    const look = getComputedStyle(warning)
    const dot = warning.querySelector('svg.lp')
    const disc = dot && dot.querySelector('circle.scheibe')
    const span = warning.querySelector('span') || warning
    out.warning = {
      before: Boolean(warning.compareDocumentPosition(ground) & Node.DOCUMENT_POSITION_FOLLOWING),
      top: box.top, height: box.height, gapToGround: ground.getBoundingClientRect().top - box.bottom,
      edgeWidth: look.borderTopWidth, edgeColour: look.borderTopColor, red: probe('--rot'),
      background: look.backgroundColor, radius: look.borderTopLeftRadius,
      padding: [look.paddingTop, look.paddingRight, look.paddingBottom, look.paddingLeft].join(' '),
      size: px(look.fontSize), ink: look.color, quiet: probe('--text-leise'), redInk: probe('--rot-text'),
      lineHeight: look.lineHeight,
      dot: disc ? {
        diameter: Math.round(parseFloat(disc.getAttribute('r')) * 2),
        fill: getComputedStyle(disc).fill, colour: dot.getAttribute('data-farbe'),
      } : null,
      dotToText: disc ? px(span.getBoundingClientRect().left - disc.getBoundingClientRect().left) : null,
      dotFromEdge: disc ? px(disc.getBoundingClientRect().left - box.left) : null,
      dotFromTop: disc ? px(disc.getBoundingClientRect().top - box.top) : null,
      text: span.textContent.replace(/\s+/g, ' ').trim(),
    }
  }
  return out
}
for (const page of Object.keys(FILES)) {
  report[page] = {}
  report[page].sound = measure(await open(page, false))
  // The service never calls the credentials faulty: the page keeps to what is said.
  if (page !== 'zugangsdaten') report[page].faulty = measure(await open(page, true))
}
// A long word in the reason breaks inside the box.
window.__reason = 'Invalid YAML: ' + 'x'.repeat(400)
{
  const ground = await open('konfiguration', true)
  const warning = document.querySelector('.warnung')
  report.long = { scrollWidth: warning.scrollWidth, clientWidth: warning.clientWidth, spanRight: warning.querySelector('span').getBoundingClientRect().right, boxRight: warning.getBoundingClientRect().right }
}
document.title = 'open'
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
    folder = FRONTEND / "node_modules" / f".harness-file-warning-{uuid4().hex}"
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
                "reason": json.dumps(REASON),
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


FILE_PAGES = ("konfiguration", "tools_datei")
TRANSPARENT = ("rgba(0, 0, 0, 0)", "transparent")


@pytest.mark.parametrize("page", FILE_PAGES)
def test_the_box_is_the_first_thing_in_the_content_and_stands_before_the_field(measured, page):
    case = measured[page]["faulty"]
    assert case["value"] and case["warnings"] == 1, case
    assert case["first"] and case["warning"]["before"], case["warning"]
    assert case["warning"]["text"].startswith("Invalid file: Invalid YAML:"), case["warning"]["text"]


@pytest.mark.parametrize("page", FILE_PAGES)
def test_it_stands_32_px_above_the_field(measured, page):
    warning = measured[page]["faulty"]["warning"]
    assert abs(warning["gapToGround"] - 32) <= 1, warning["gapToGround"]


@pytest.mark.parametrize("page", FILE_PAGES)
def test_it_has_the_red_edge_no_ground_and_the_padding_as_drawn(measured, page):
    warning = measured[page]["faulty"]["warning"]
    assert warning["edgeWidth"] == "1px" and warning["edgeColour"] == warning["red"], warning
    assert warning["background"] in TRANSPARENT, warning
    assert warning["radius"] == "9px" and warning["padding"] == "12px 16px 12px 16px", warning


@pytest.mark.parametrize("page", FILE_PAGES)
def test_it_has_the_red_dot_of_10_px_and_the_sentence_in_the_quiet_ink(measured, page):
    warning = measured[page]["faulty"]["warning"]
    assert warning["dot"] == {"diameter": 10, "fill": warning["red"], "colour": "rot"}, warning["dot"]
    # 1 px edge and 16 px padding to the dot's box of 12 px (the disc a pixel in),
    # 10 px from the box to the sentence.
    assert abs(warning["dotFromEdge"] - 18) <= 0.5 and abs(warning["dotToText"] - 21) <= 0.5, warning
    assert abs(warning["dotFromTop"] - 14) <= 0.5, warning
    assert warning["size"] == 12.5 and warning["ink"] == warning["quiet"], warning
    assert warning["ink"] != warning["redInk"], warning


@pytest.mark.parametrize("page", FILE_PAGES)
def test_its_height_is_whole_lines_of_15_px_between_two_edges_of_12_px_padding(measured, page):
    warning = measured[page]["faulty"]["warning"]
    assert warning["lineHeight"] == "15px", warning["lineHeight"]
    lines = (warning["height"] - 26) / 15
    assert lines >= 1 and abs(lines - round(lines)) < 0.05, warning["height"]


@pytest.mark.parametrize("page", FILE_PAGES)
def test_the_field_starts_lower_by_the_box_and_still_ends_32_px_above_the_foot(measured, page):
    sound, faulty = measured[page]["sound"], measured[page]["faulty"]
    box = faulty["warning"]["height"] + 32
    assert abs(faulty["groundTop"] - sound["groundTop"] - box) <= 2, (sound["groundTop"], faulty["groundTop"], box)
    if page == "konfiguration":
        assert abs(faulty["toFoot"] - 32) <= 2 and abs(sound["toFoot"] - 32) <= 2, (sound["toFoot"], faulty["toFoot"])
        assert abs(faulty["groundBottom"] - sound["groundBottom"]) <= 2


@pytest.mark.parametrize("page", ("konfiguration", "tools_datei", "zugangsdaten", "agent:broken"))
def test_silence_a_sound_file_shows_no_box(measured, page):
    assert measured[page]["sound"]["warnings"] == 0, measured[page]["sound"]


def test_silence_the_credentials_page_is_the_page_of_a_file_and_the_field_is_where_it_was(measured):
    sound = measured["zugangsdaten"]["sound"]
    assert sound["value"].startswith("TEST_KEY"), sound
    assert abs(sound["toFoot"] - 32) <= 2, sound["toFoot"]
    # The same field is a block under the same head: its ground starts where the page's content does.
    assert abs(sound["groundTop"] - measured["konfiguration"]["sound"]["groundTop"]) <= 1, (
        sound["groundTop"], measured["konfiguration"]["sound"]["groundTop"],
    )


def test_silence_the_box_of_an_agent_file_stays_under_the_field_with_its_own_look(measured):
    warning = measured["agent:broken"]["faulty"]["warning"]
    assert not measured["agent:broken"]["faulty"]["first"] and not warning["before"], warning
    assert warning["background"] not in TRANSPARENT and warning["edgeWidth"] == "0px", warning
    assert warning["dot"] is None and warning["ink"] == warning["redInk"], warning
    assert warning["padding"] == "8px 12px 8px 12px" and warning["size"] == 12.5, warning
    assert warning["text"].startswith("This agent is unavailable:"), warning["text"]


def test_a_long_word_in_the_reason_breaks_inside_the_box(measured):
    long = measured["long"]
    assert long["scrollWidth"] <= long["clientWidth"] + 1, long
    assert long["spanRight"] <= long["boxRight"], long
