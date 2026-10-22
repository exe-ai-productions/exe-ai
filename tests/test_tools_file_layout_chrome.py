"""The layout of the tools file page, as drawn: the field of 420, the blocks 32 apart, the
servers under "Live" as rows with their own tools.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome, with the
files made up in the page (the service is not asked): a tools file with two keys, and
the answer of the tool list with two servers, their tools and tools of the program
itself. The page reports for the tools file the height of the field, the gaps
between the field, the heading "Keys", the key list, the heading "Active right now"
and its field, and where the room that is left stands; for each server the row
(dot, name, its own tools as pills with a mark) and for the tools of the program
that none of them stands there. And what stays: with the tools file switched off
the sentence stands, and the credentials page still reaches down to its foot.

The build of the harness links the built stylesheet, so every colour probe reads
the real tokens.

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

<div id="frame" style="width: 1100px; height: 1200px; position: relative;">
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
  '/tools/config': {
    content: '{}', kaputt: null,
    platzhalter: [{ name: 'BRAVE_API_KEY', gesetzt: true }, { name: 'OTHER_KEY', gesetzt: false }],
  },
  '/tools': {
    aktiv: true,
    server: ['websearch', 'files', 'archive'],
    werkzeuge: [
      { name: 'get_current_time', anzeige: null, beschreibung: '', server: 'clock', needs_confirmation: false, builtin: true },
      { name: 'run_command', anzeige: null, beschreibung: '', server: 'websearch', needs_confirmation: true, builtin: true },
      { name: 'mcp__websearch__web_search', anzeige: 'web_search', beschreibung: '', server: 'websearch', needs_confirmation: false, builtin: false },
      { name: 'mcp__websearch__read_webpage', anzeige: 'read_webpage', beschreibung: '', server: 'websearch', needs_confirmation: false, builtin: false },
      { name: 'mcp__files__list', anzeige: 'list', beschreibung: '', server: 'files', needs_confirmation: false, builtin: false },
      { name: 'mcp__archive__long', anzeige: 'a_very_long_tool_name_'.repeat(8), beschreibung: '', server: 'archive', needs_confirmation: false, builtin: false },
    ],
  },
  '/dateien/zugangsdaten': { inhalt: 'KEY=value', kaputt: null },
  '/dateien/konfiguration': { inhalt: 'port: 8090', kaputt: null },
  '/agents': [], '/agent-files': [], '/skills': [], '/cronjobs': [], '/jobs': [], '/werkzeuge': [],
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
const probe = (token, property = 'color', holder = document.body) => {
  const node = document.createElement('i')
  node.style[property] = `var(${token})`
  holder.appendChild(node)
  const value = getComputedStyle(node)[property]
  node.remove()
  return value
}
const rect = (node) => {
  if (!node) return null
  const box = node.getBoundingClientRect()
  return { top: px(box.top), bottom: px(box.bottom), left: px(box.left), right: px(box.right), height: px(box.height) }
}
const show = async (page, ready) => {
  window.__zustand.promptStart = page === 'tools_datei' ? 'zugangsdaten' : 'tools_datei'
  await wait(600)
  window.__zustand.promptStart = page
  for (let k = 0; k < 80; k += 1) {
    await wait(100)
    if (ready()) break
    if (k === 79) throw new Error('the page did not show: ' + page)
  }
  await wait(500)
}
await show('tools_datei', () => document.querySelectorAll('.lese .server').length === 3 && document.querySelector('.keys'))
const field = document.querySelector('.editorboden .feld')
const keysTitle = document.querySelector('.keys-title')
const keyCard = document.querySelector('.keys-card')
const liveTitle = document.querySelector('.lesetitel')
const liveCard = document.querySelector('.live-card')
const foot = document.querySelector('.fuss')
report.stack = {
  field: rect(field), board: rect(document.querySelector('.editorboden')), keysTitle: rect(keysTitle), keyCard: rect(keyCard),
  liveTitle: rect(liveTitle), liveCard: rect(liveCard), foot: rect(foot),
}
if (liveCard) {
  const liveLook = getComputedStyle(liveCard)
  report.liveCard = {
    ground: liveLook.backgroundColor, glass: probe('--glass-card', 'backgroundColor'),
    edgeWidth: liveLook.borderTopWidth, edgeColour: liveLook.borderTopColor, edge: probe('--feldstrich', 'borderTopColor'),
    radius: liveLook.borderTopLeftRadius, padding: [liveLook.paddingTop, liveLook.paddingRight, liveLook.paddingBottom, liveLook.paddingLeft].join(' '),
  }
  const cardBox = liveCard.getBoundingClientRect()
  report.rows = Array.from(liveCard.querySelectorAll('.live-row')).map((row) => {
    const rowBox = row.getBoundingClientRect()
    const server = row.querySelector('.server')
    const dot = server.querySelector('svg.lp')
    const nameNode = Array.from(server.childNodes).find((n) => n.nodeType === 3 && n.textContent.trim())
    const nameRange = document.createRange()
    nameRange.selectNodeContents(nameNode)
    const nameBox = nameRange.getBoundingClientRect()
    const serverLook = getComputedStyle(server)
    return {
      height: px(rowBox.height), top: px(rowBox.top),
      border: getComputedStyle(row).borderTopWidth, borderColour: getComputedStyle(row).borderTopColor,
      server: {
        text: server.textContent.trim(), family: serverLook.fontFamily, size: px(serverLook.fontSize), ink: serverLook.color,
        dotBox: px(dot.getBoundingClientRect().width), dotFromCard: px(dot.getBoundingClientRect().left - cardBox.left),
        dotToName: px(nameBox.left - dot.getBoundingClientRect().right),
      },
      pills: Array.from(row.querySelectorAll('.werkzeugpille')).map((pill) => {
        const box = pill.getBoundingClientRect()
        const look = getComputedStyle(pill)
        const mark = pill.querySelector('.pillenzeichen')
        const markBox = mark ? mark.getBoundingClientRect() : null
        const name = pill.querySelector('.pillenname')
        const textRange = document.createRange()
        textRange.selectNodeContents(name)
        const textBox = textRange.getBoundingClientRect()
        return {
          text: pill.textContent.replace(/\s+/g, ' ').trim(), height: px(box.height), width: px(box.width),
          rim: look.borderTopWidth, rimColour: look.borderTopColor, radius: look.borderTopLeftRadius,
          ground: look.backgroundColor, family: look.fontFamily, size: px(look.fontSize), weight: look.fontWeight, ink: look.color,
          hasMark: Boolean(pill.querySelector('.pillenzeichen svg, .pillenzeichen img')),
          cut: name.scrollWidth > name.clientWidth,
          markSize: markBox ? [px(markBox.width), px(markBox.height)] : null,
          markFromEdge: markBox ? px(markBox.left - box.left) : null,
          markToText: markBox ? px(textBox.left - markBox.right) : null,
          textToEdge: px(box.right - Math.min(textBox.right, name.getBoundingClientRect().right)),
          fromCardEdge: px(cardBox.right - box.right),
        }
      }),
    }
  })
} else {
  report.liveCard = null
  report.rows = []
}
report.tokens = {
  fixed: probe('--schrift-fest', 'fontFamily'), quiet: probe('--text-leise'), ink: probe('--text'),
  line: probe('--linie', 'borderTopColor', liveCard || document.body), feldstrich: probe('--feldstrich', 'borderTopColor', liveCard || document.body),
  glass: probe('--glass-button', 'backgroundColor'),
}
report.cardWidth = liveCard ? px(liveCard.getBoundingClientRect().width) : 0
report.everyName = Array.from(document.querySelectorAll('.lese .werkzeugpille')).map((pill) => pill.textContent.replace(/\s+/g, ' ').trim())
window.__answers['/tools'] = { ...window.__answers['/tools'], aktiv: false }
await show('tools_datei', () => document.querySelector('.leseleer') && !document.querySelector('.live-card'))
report.off = {
  sentence: document.querySelector('.leseleer').textContent.trim(),
  cards: document.querySelectorAll('.live-card').length,
  heading: document.querySelector('.lesetitel').textContent.trim(),
}
const fillsFoot = async (page, content) => {
  await show(page, () => document.querySelector('.editorboden textarea')?.value.startsWith(content))
  const board = document.querySelector('.editorboden')
  return { board: rect(board), foot: rect(document.querySelector('.fuss')) }
}
report.credentials = await fillsFoot('zugangsdaten', 'KEY=')
report.configuration = await fillsFoot('konfiguration', 'port:')
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
    folder = FRONTEND / "node_modules" / f".harness-tool-layout-{uuid4().hex}"
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
                "--window-size=1100,1300",
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


def _gap(upper: dict | None, lower: dict | None) -> float:
    assert upper and lower, "a block of the page is missing"
    return round(lower["top"] - upper["bottom"], 1)


def test_the_field_of_the_tools_file_is_420_high_and_takes_no_more(measured):
    stack = measured["stack"]
    assert stack["field"]["height"] == 420, stack["field"]
    assert stack["board"]["height"] == 420, stack["board"]


def test_the_blocks_under_the_field_stand_32_apart_each_heading_34_high(measured):
    stack = measured["stack"]
    assert _gap(stack["field"], stack["keysTitle"]) == 32, stack
    assert _gap(stack["keysTitle"], stack["keyCard"]) == 32, stack
    assert _gap(stack["keyCard"], stack["liveTitle"]) == 32, stack
    assert _gap(stack["liveTitle"], stack["liveCard"]) == 32, stack
    assert stack["keysTitle"]["height"] == 34 and stack["liveTitle"]["height"] == 34, stack


def test_the_room_that_is_left_stands_above_the_foot_where_more_keys_come(measured):
    stack = measured["stack"]
    assert _gap(stack["liveCard"], stack["foot"]) > 40, stack


def test_live_is_a_field_of_card_glass_with_a_rim_like_the_key_list(measured):
    card = measured["liveCard"]
    assert card, "there is no field under Live"
    assert card["ground"] == card["glass"], card
    assert card["edgeWidth"] == "1px" and card["edgeColour"] == card["edge"], card
    assert card["radius"] == "9px" and card["padding"] == "0px 16px 0px 16px", card


def test_live_has_one_row_for_each_server_with_its_dot_and_its_name(measured):
    rows = measured["rows"]
    assert rows, "there is no row under Live"
    assert [row["server"]["text"] for row in rows] == ["websearch", "files", "archive"], rows
    tokens = measured["tokens"]
    for row in rows:
        server = row["server"]
        assert server["dotBox"] == 12 and server["dotFromCard"] == 17, server
        assert server["dotToName"] == 8, server
        assert server["size"] == 12 and server["family"] == tokens["fixed"] and server["ink"] == tokens["quiet"], server
    assert rows[0]["height"] == 52 and rows[1]["height"] == 53 and rows[2]["height"] == 53, rows
    assert rows[1]["border"] == "1px" and rows[1]["borderColour"] == tokens["feldstrich"], rows[1]


def test_each_row_shows_only_the_tools_of_its_server_as_pills_with_their_mark(measured):
    rows = measured["rows"]
    assert [[pill["text"] for pill in row["pills"]] for row in rows[:2]] == [["web_search", "read_webpage"], ["list"]]
    assert all(pill["hasMark"] for row in rows for pill in row["pills"]), rows


def test_no_tool_of_the_program_stands_under_live(measured):
    names = measured["everyName"]
    assert sorted(name for name in names if len(name) < 40) == ["list", "read_webpage", "web_search"], names
    assert len(names) == 4, names


def test_a_pill_is_28_high_with_its_rim_its_mark_of_14_and_the_tool_face(measured):
    tokens = measured["tokens"]
    for row in measured["rows"][:2]:
        for pill in row["pills"]:
            assert pill["height"] == 28, pill
            assert pill["rim"] == "1px" and pill["rimColour"] == tokens["line"] and pill["radius"] == "9px", pill
            assert pill["ground"] == tokens["glass"], pill
            assert pill["markSize"] == [14, 14] and pill["markFromEdge"] == 11 and pill["markToText"] == 7, pill
            assert abs(pill["textToEdge"] - 12) <= 0.5, pill
            assert pill["family"] == tokens["fixed"] and pill["size"] == 12 and pill["weight"] == "500", pill
            assert pill["ink"] == tokens["ink"], pill
        assert row["pills"][-1]["fromCardEdge"] == 17, row["pills"][-1]


def test_a_name_longer_than_the_row_is_cut_with_dots_and_the_pill_stays_in_the_field(measured):
    pill = measured["rows"][2]["pills"][0]
    assert pill["height"] == 28 and pill["fromCardEdge"] >= 17, pill
    assert pill["cut"] and pill["width"] < measured["cardWidth"] - 32, pill


def test_silence_with_the_tools_file_switched_off_the_sentence_stands_without_a_field(measured):
    off = measured["off"]
    assert off["sentence"] == "Tools are disabled (features.mcp)", off
    assert off["cards"] == 0 and off["heading"] == "Active right now", off


def test_silence_the_credentials_and_the_configuration_still_reach_down_to_the_foot(measured):
    for page in ("credentials", "configuration"):
        found = measured[page]
        assert found["board"]["height"] > 500, found
        assert _gap(found["board"], found["foot"]) == 18, found
