"""The head of the settings pages: a box of button glass with the sign, and a
title in the normal cut, as drawn.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome, with the
files made up in the page (the service is not asked), on four of the pages that
take their head from it: Appearance, Agents, Tools and Configuration. The page
reports for each head: the box of 40 x 40 px with radius 9, the ground of the
button glass and its edge of 1 px inside, the sign of 22 px in the middle of it;
the title 14 px to the right of the box, 22 px, weight 400, no letter spacing, a
line of 1.3 and the colour of the text. And what stays: the figure of the tools
stands 12 px behind its title, "New agent" stands at the far end of the head, and
the warning box of a faulty file stands under the head.

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
  '/dateien/konfiguration': { inhalt: 'key: value', kaputt: 'Invalid YAML: line 3' },
  '/tools/config': { content: '{}', kaputt: null, platzhalter: [] },
  '/system-prompt': { text: 'A short instruction.' },
  '/agents': [], '/agent-files': [], '/skills': [], '/cronjobs': [], '/jobs': [], '/tools': [], '/werkzeuge': [],
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
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const probe = (token, property = 'color') => {
  const node = document.createElement('i')
  node.style[property] = `var(${token})`
  document.body.appendChild(node)
  const value = getComputedStyle(node)[property]
  node.remove()
  return value
}
const PAGES = ['darstellung', 'agent', 'werkzeuge', 'konfiguration']
// The titles already seen: the head of a page is the one that is none of them.
const seen = new Set()
for (const page of PAGES) {
  window.__zustand.promptStart = 'system'
  await wait(600)
  const rest = document.querySelector('.set-kopf h3')
  if (rest) seen.add(rest.textContent.trim())
  window.__zustand.promptStart = page
  let head = null
  for (let k = 0; k < 80; k += 1) {
    await wait(100)
    head = document.querySelector('.set-kopf')
    if (head && head.querySelector('h3') && !seen.has(head.querySelector('h3').textContent.trim())) break
    if (k === 79) throw new Error('the head of ' + page + ' did not show')
  }
  await wait(500)
  const mark = head.querySelector('.s2-zeichen')
  const title = head.querySelector('h3')
  const svg = mark.querySelector('svg')
  const box = mark.getBoundingClientRect()
  const look = getComputedStyle(mark)
  const type = getComputedStyle(title)
  const pill = head.querySelector('.zahlpille')
  const add = head.querySelector('.neu')
  seen.add(title.textContent.trim())
  report[page] = {
    title: title.textContent.trim(),
    box: { width: box.width, height: box.height, radius: look.borderTopLeftRadius, ground: look.backgroundColor,
           glass: probe('--glass-button', 'backgroundColor'), shadow: look.boxShadow, edge: probe('--glass-button-edge') },
    sign: svg ? { width: svg.getBoundingClientRect().width, height: svg.getBoundingClientRect().height,
                  centreX: svg.getBoundingClientRect().left + svg.getBoundingClientRect().width / 2 - (box.left + box.width / 2),
                  centreY: svg.getBoundingClientRect().top + svg.getBoundingClientRect().height / 2 - (box.top + box.height / 2) } : null,
    gap: title.getBoundingClientRect().left - box.right,
    type: { size: px(type.fontSize), weight: type.fontWeight, spacing: type.letterSpacing, lineHeight: px(type.lineHeight),
            ink: type.color, text: probe('--text') },
    pill: pill ? pill.getBoundingClientRect().left - title.getBoundingClientRect().right : null,
    add: add ? { left: add.getBoundingClientRect().left, titleRight: title.getBoundingClientRect().right,
                 right: add.getBoundingClientRect().right, headRight: head.getBoundingClientRect().right } : null,
    warning: (() => {
      const w = document.querySelector('.breite .warnung')
      return w ? w.getBoundingClientRect().top - head.getBoundingClientRect().bottom : null
    })(),
  }
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
    folder = FRONTEND / "node_modules" / f".harness-page-head-{uuid4().hex}"
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


PAGES = ("darstellung", "agent", "werkzeuge", "konfiguration")


def test_the_four_pages_show_four_different_titles(measured):
    titles = [measured[page]["title"] for page in PAGES]
    assert all(titles) and len(set(titles)) == 4, titles


@pytest.mark.parametrize("page", PAGES)
def test_the_sign_stands_in_a_box_of_button_glass_40_px(measured, page):
    box = measured[page]["box"]
    assert box["width"] == 40 and box["height"] == 40 and box["radius"] == "9px", box
    assert box["ground"] == box["glass"], box
    # The fine edge is drawn inside, 1 px, in the colour of the glass's edge.
    assert box["shadow"].startswith(box["edge"]) and "0px 0px 0px 1px inset" in box["shadow"], box


@pytest.mark.parametrize("page", PAGES)
def test_the_sign_is_22_px_and_in_the_middle_of_the_box(measured, page):
    sign = measured[page]["sign"]
    assert sign["width"] == 22 and sign["height"] == 22, sign
    assert abs(sign["centreX"]) <= 0.5 and abs(sign["centreY"]) <= 0.5, sign


@pytest.mark.parametrize("page", PAGES)
def test_the_title_stands_14_px_from_the_box_in_22_px_normal_cut(measured, page):
    case = measured[page]
    assert abs(case["gap"] - 14) <= 0.5, case["gap"]
    kind = case["type"]
    assert kind["size"] == 22 and kind["weight"] == "400" and kind["spacing"] == "normal", kind
    assert abs(kind["lineHeight"] - 28.6) <= 0.2 and kind["ink"] == kind["text"], kind


def test_silence_the_figure_of_the_tools_stands_12_px_behind_the_title(measured):
    assert abs(measured["werkzeuge"]["pill"] - 12) <= 0.5, measured["werkzeuge"]["pill"]
    assert all(measured[page]["pill"] is None for page in ("darstellung", "agent", "konfiguration"))


def test_silence_new_agent_stands_at_the_far_end_of_the_head(measured):
    add = measured["agent"]["add"]
    assert add["left"] > add["titleRight"] + 40 and abs(add["right"] - add["headRight"]) <= 1, add
    assert all(measured[page]["add"] is None for page in ("darstellung", "werkzeuge", "konfiguration"))


def test_silence_the_warning_box_of_a_faulty_file_stays_under_the_head(measured):
    gap = measured["konfiguration"]["warning"]
    assert gap is not None and 0 <= gap <= 30, gap
