"""On the tools page the list and the chosen source end on one line, measured in
a real browser.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome at
1920 x 1080 with the service made up in the page. The two cards are as high as
the longer of the two, never stretched down to the foot of the page beyond
that, and once the longer one is more than the page holds both end at the foot
and the list scrolls inside itself. Three cases: nine sources with a source of
ten tools chosen (the two heights differ by a few pixels), three sources with
one tool each (far shorter than the page), twenty sources (longer than the
page). Skipped where there is no Chrome or no node, like the other browser
tests.
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

<div id="frame" style="width: 1920px; height: 1080px; position: relative; display: flex;">
  <SystemPrompt {offen} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { zustand } from %(zustand)r

const scenario = new URLSearchParams(location.search).get('scenario')
const builtIn = ['shell', 'memory', 'skills', 'image', 'cronjob', 'goal', 'dock', 'clock']
const tool = (name, server, extra = {}) => ({
  name, server, builtin: true, beschreibung: 'Does ' + name, needs_confirmation: false, ...extra,
})
const terminalTools = [
  'run_command', 'read_file', 'write_file', 'edit_file', 'list_dir',
  'create_folder', 'move_file', 'delete_file', 'start_job', 'ask_question',
].map((name) => tool(name, 'shell'))
const server = (name) => ({
  name, laeuft: true, enabled: true, allowed_tools: null,
  alle_werkzeuge: [{ name: name + '_tool', beschreibung: 'Does it' }],
})
const serverTool = (name) => tool(name + '_tool', name, { builtin: false })

let tools
let servers
if (scenario === 'ten') {
  // Nine sources: the eight built-in ones and one server; the terminal holds ten tools.
  tools = [...terminalTools, ...builtIn.slice(1).map((name) => tool(name + '_one', name)), serverTool('searxng')]
  servers = [server('searxng')]
} else if (scenario === 'few') {
  // Three sources, one tool each.
  tools = [tool('get_current_time', 'clock'), tool('goal', 'goal'), tool('deliver_file', 'dock')]
  servers = []
} else if (scenario === 'long') {
  // Three sources, the terminal chosen with sixty tools: the right card is longer than the page.
  tools = [
    ...Array.from({ length: 60 }, (_, i) => tool('terminal_tool_' + i, 'shell')),
    tool('get_current_time', 'clock'), tool('goal', 'goal'),
  ]
  servers = []
} else {
  // Twenty sources: more rows than the page holds.
  const names = Array.from({ length: 12 }, (_, i) => 'server-' + String(i).padStart(2, '0'))
  tools = [...terminalTools, ...builtIn.slice(1).map((name) => tool(name + '_one', name)), ...names.map(serverTool)]
  servers = names.map(server)
}
const answers = { '/tools': { aktiv: true, server: servers.map((s) => s.name), werkzeuge: tools }, '/tools/servers': servers }
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
zustand.promptOffen = true
zustand.promptStart = 'werkzeuge'
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
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js', cssFileName: 'style' },
  },
})
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const box = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }
}
const rows = () => Array.from(document.querySelectorAll('.werkzeugseite .links .qbox'))
const want = { ten: 9, few: 3, many: 20, long: 3 }[new URLSearchParams(location.search).get('scenario')]
for (let k = 0; k < 100 && rows().length < want; k += 1) await wait(100)
await wait(500)

// Choose the first source, the terminal of the built-in ones.
rows()[0].querySelector('.qeintrag').click()
await wait(400)

const page = document.querySelector('.werkzeugseite')
const row = document.querySelector('.werkzeugseite .zwei')
const links = document.querySelector('.werkzeugseite .links')
const right = document.querySelector('.werkzeugseite .rechts')
const lastRow = links.querySelector('.qbox:last-child')
const lastTool = right.lastElementChild
const content = (card, last) => box(last).bottom - box(card).top
const style = (node, name) => getComputedStyle(node)[name]
const report = {
  rows: rows().length, tools: right.querySelectorAll('.eeintrag').length,
  page: box(page), row: box(row), links: box(links), right: box(right),
  contentLinks: box(lastRow).bottom + parseFloat(style(links, 'paddingBottom')) - box(links).top,
  contentRight: box(lastTool).bottom + parseFloat(style(right, 'paddingBottom')) - box(right).top,
  scrollsLinks: links.scrollHeight > links.clientHeight + 1,
  scrollsRight: right.scrollHeight > right.clientHeight + 1,
  overflowLinks: style(links, 'overflowY'), overflowRight: style(right, 'overflowY'),
  head: box(document.querySelector('.set-kopf')),
  headName: links.querySelector('.lname').textContent.trim(),
  linksPadding: style(links, 'padding'), rightPadding: style(right, 'padding'),
  gap: box(right).left - box(links).right, width: box(links).width,
  radiusLinks: style(links, 'borderTopLeftRadius'), radiusRight: style(right, 'borderTopLeftRadius'),
}

// Unfolding a built-in source still works: its tools appear and the cards stay level.
const clock = rows()[rows().length > 8 ? 7 : 0]
const fold = clock.querySelector('.qklapp')
if (fold) {
  fold.click()
  await wait(400)
  report.unfolded = clock.querySelectorAll('.weintrag').length
  report.afterUnfold = { links: box(links), right: box(right) }
}

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1920px; position: relative; }</style>
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


async def _drive(port: int, limit: float = 150.0) -> dict:
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


@pytest.fixture(scope="module")
def harness():
    """The page built once; each case opens it with its own scenario."""
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-tools-equal-bottoms-{uuid4().hex}"
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

        def measure(scenario: str) -> dict:
            port = _free_port()
            browser = subprocess.Popen(
                [
                    program,
                    "--headless=new",
                    "--no-first-run",
                    "--disable-background-networking",
                    "--allow-file-access-from-files",
                    "--window-size=1920,1080",
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={folder / ('profile-' + scenario)}",
                    (folder / "measure.html").as_uri() + f"?scenario={scenario}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                return asyncio.run(_drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)

        yield measure
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def ten(harness) -> dict:
    return harness("ten")


@pytest.fixture(scope="module")
def few(harness) -> dict:
    return harness("few")


@pytest.fixture(scope="module")
def many(harness) -> dict:
    return harness("many")


@pytest.fixture(scope="module")
def long_terminal(harness) -> dict:
    return harness("long")


def _close(a: float, b: float, by: float = 0.5) -> bool:
    return abs(a - b) <= by


# --- Nine sources, a source of ten tools: the two heights differ by a few pixels ---


def test_with_nine_sources_and_a_terminal_of_ten_tools_the_cards_end_on_one_line(ten):
    assert ten["rows"] == 9 and ten["tools"] == 10, ten
    assert _close(ten["links"]["bottom"], ten["right"]["bottom"]), ten
    # The content really differs, so the test would fall over with cards of their own height.
    assert not _close(ten["contentLinks"], ten["contentRight"], 1.0), ten


def test_the_cards_are_as_high_as_the_longer_of_the_two(ten):
    longer = max(ten["contentLinks"], ten["contentRight"])
    assert _close(ten["links"]["height"], longer, 1.0), ten
    assert _close(ten["right"]["height"], longer, 1.0), ten


# --- Three sources: far shorter than the page, nothing is drawn down to the foot ---


def test_with_three_sources_and_one_tool_the_cards_end_on_one_line_well_above_the_foot(few):
    assert few["rows"] == 3, few
    assert _close(few["links"]["bottom"], few["right"]["bottom"]), few
    assert few["page"]["bottom"] - few["links"]["bottom"] >= 100, few
    assert few["scrollsLinks"] is False and few["scrollsRight"] is False, few


# --- Twenty sources: longer than the page, both end at the foot and the list scrolls ---


def test_with_twenty_sources_the_cards_end_on_one_line_at_the_foot_and_the_list_scrolls(many):
    assert many["rows"] == 20, many
    assert _close(many["links"]["bottom"], many["right"]["bottom"]), many
    assert many["links"]["bottom"] <= many["page"]["bottom"] + 0.5, many
    assert _close(many["links"]["bottom"], many["page"]["bottom"], 1.0), many
    assert many["scrollsLinks"] is True, many
    assert many["overflowLinks"] == "auto", many


# --- A chosen source longer than the page: the right card ends at the foot and scrolls ---


def test_with_a_source_of_sixty_tools_both_cards_end_at_the_foot_and_the_right_one_scrolls(long_terminal):
    report = long_terminal
    assert report["rows"] == 3 and report["tools"] == 60, report
    assert report["contentRight"] > report["page"]["height"], report
    assert _close(report["links"]["bottom"], report["right"]["bottom"]), report
    assert _close(report["right"]["bottom"], report["page"]["bottom"], 1.0), report
    assert report["scrollsRight"] is True and report["overflowRight"] == "auto", report


# --- Silence: what stays as it was ---


@pytest.mark.parametrize("case", ["ten", "few", "many", "long_terminal"])
def test_silence_the_list_keeps_its_width_the_gap_its_padding_and_its_head(case, request):
    report = request.getfixturevalue(case)
    assert _close(report["width"], 300), report
    assert _close(report["gap"], 24), report
    assert report["linksPadding"] == "16px 11px", report
    assert report["rightPadding"] == "20px 24px 24px", report
    assert report["radiusLinks"] == "9px" and report["radiusRight"] == "9px", report
    assert report["headName"] == "werkzeuge.sources", report
    assert report["head"] is not None, report


def test_silence_a_built_in_source_still_unfolds_and_the_cards_stay_level(ten):
    assert ten["unfolded"] >= 1, ten
    assert _close(ten["afterUnfold"]["links"]["bottom"], ten["afterUnfold"]["right"]["bottom"]), ten
