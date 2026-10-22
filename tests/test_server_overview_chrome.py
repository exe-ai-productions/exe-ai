"""The server overview of the settings, measured in a real browser: the maker's
logo stands in front of every chosen model, and the MCP connections are a table
that lines up with the table of the local servers.

`ServerOverview.svelte` is built as shipped and drawn in headless Chrome with
faked answers of the service: six server reports (three with a chosen model of
a known maker, one of an unknown name, two without a choice) and four MCP
servers in four different states. Skipped where there is no Chrome or no node,
like the other browser tests.
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
  import ServerOverview from %(overview)r
</script>

<div style="width: 1200px; padding: 24px; box-sizing: border-box;">
  <ServerOverview wired={12} total={48} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { refreshServerState } from %(serverstand)r
import %(global)r

const reports = {
  '/runner': { laeuft: true, selected_model: 'Qwen3.8-27B-Q4_K_M.gguf', programm: '/bin/llama', port: 8081 },
  '/agentenmodell': { laeuft: false, selected_model: 'Occamy-1.0.APEX-I-MiniPlus-V2.1.gguf', programm: '/bin/llama', port: 8082 },
  '/einbettungsserver': { laeuft: false, selected_model: 'zzz-unknown-model.gguf', programm: '/bin/llama', port: 8083 },
  '/sprachserver': { laeuft: false, selected_model: null, port: 8084 },
  '/bereinigungsserver': { laeuft: false, selected_model: null, port: 8085 },
  '/bild/turbo': { zustand: 'aus', selected_model: null, port: 8191 },
}
// Six servers on file: connected (two), starting, off, not connected (wants a sign-in and has none), and one
// whose keys are missing, with names long enough to want a line of their own. Shipped servers that have no
// entry here must not get a row.
const servers = [
  { name: 'websuche', enabled: true, laeuft: true, type: 'stdio', alle_werkzeuge: [{ name: 'search' }], allowed_tools: [] },
  { name: 'notion', enabled: false, laeuft: false, type: 'http', url: 'https://mcp.notion.com/mcp', alle_werkzeuge: [], allowed_tools: [] },
  { name: 'atlas', enabled: true, laeuft: false, type: 'http', url: 'http://127.0.0.1:1/mcp', auth: 'oauth', alle_werkzeuge: [], allowed_tools: [] },
  { name: 'github', enabled: true, laeuft: true, type: 'http', url: 'https://api.githubcopilot.com/mcp/', alle_werkzeuge: [{ name: 'issues' }], allowed_tools: [] },
  { name: 'starter', enabled: true, laeuft: false, type: 'stdio', alle_werkzeuge: [], allowed_tools: [] },
  { name: 'keyless', enabled: true, laeuft: false, type: 'stdio', schluessel_gesetzt: false, alle_werkzeuge: [], allowed_tools: [],
    missing_keys: ['GITHUB_PERSONAL_ACCESS_TOKEN', 'NOTION_INTEGRATION_API_KEY', 'ANOTHER_VERY_LONG_ENVIRONMENT_VARIABLE_NAME'] },
]
const answers = { ...reports, '/tools/servers': servers, '/tools/oauth/status': [] }
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
mount(Shell, { target: document.getElementById('wurzel') })
refreshServerState()
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
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const rect = (node) => {
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right }
}
const tables = () => document.querySelectorAll('.card')
for (let k = 0; k < 60 && !(tables().length === 2 && tables()[1].querySelectorAll('.link').length === 6); k += 1) await wait(100)
await wait(500)
const [local, mcp] = Array.from(tables())
const report = {}
report.localRows = Array.from(local.querySelectorAll('.line')).map((row) => {
  const model = row.querySelector('.model')
  return {
    text: model.querySelector('.text').textContent.trim(),
    svg: Boolean(model.querySelector('svg')),
    svgWidth: model.querySelector('svg')?.getBoundingClientRect().width ?? null,
    svgHeight: model.querySelector('svg')?.getBoundingClientRect().height ?? null,
    letter: model.querySelector('.letter')?.textContent.trim() ?? null,
    markWidth: model.querySelector('.mark')?.getBoundingClientRect().width ?? null,
  }
})
const stateX = (table) => Array.from(table.querySelectorAll('.state')).map((n) => Math.round(n.getBoundingClientRect().x))
const headState = (table) => Math.round(table.querySelectorAll('.head > span')[1].getBoundingClientRect().x)
report.localStateX = stateX(local)
report.mcpStateX = stateX(mcp)
report.localHeadX = headState(local)
report.mcpHeadX = headState(mcp)
report.mcpHeads = Array.from(mcp.querySelectorAll('.head > span')).map((n) => n.textContent.trim())
report.localHeads = Array.from(local.querySelectorAll('.head > span')).map((n) => n.textContent.trim())
report.mcpRows = Array.from(mcp.querySelectorAll('.link')).map((row) => {
  const logo = row.querySelector('.mcplogo')
  const state = row.querySelector('.state')
  return {
    title: row.querySelector('.text').textContent.trim(),
    state: state.textContent.trim(),
    stateClass: state.className.replace(/svelte-\S+/g, '').trim(),
    color: getComputedStyle(state).color,
    logoWidth: logo.getBoundingClientRect().width,
    logoHeight: logo.getBoundingClientRect().height,
    hasDrawing: Boolean(logo.querySelector('svg, img')),
    chevron: Boolean(row.querySelector('.chevron svg, .chevron span')),
    tag: row.tagName,
  }
})
report.tableLeft = [rect(local).x, rect(mcp).x]
report.tableWidth = [rect(local).width, rect(mcp).width]
report.rowHeights = [
  ...Array.from(local.querySelectorAll('.line')).map((n) => Math.round(n.getBoundingClientRect().height)),
  ...Array.from(mcp.querySelectorAll('.link')).map((n) => Math.round(n.getBoundingClientRect().height)),
]
report.pageWidth = [document.documentElement.scrollWidth, innerWidth]
const typeOf = (node) => {
  const c = getComputedStyle(node)
  return { weight: c.fontWeight, size: c.fontSize, color: c.color }
}
const colourOf = (variable) => {
  const probe = document.createElement('span')
  probe.style.color = `var(${variable})`
  local.appendChild(probe)
  const value = getComputedStyle(probe).color
  probe.remove()
  return value
}
report.colours = { text: colourOf('--text'), quiet: colourOf('--text-leise') }
report.type = {
  local: {
    head: typeOf(local.querySelector('.head > span')),
    names: Array.from(local.querySelectorAll('.line .name .text')).map(typeOf),
    ports: Array.from(local.querySelectorAll('.line .cell')).map(typeOf),
    models: Array.from(local.querySelectorAll('.line .model .text')).map(typeOf),
    states: Array.from(local.querySelectorAll('.line .state')).map(typeOf),
  },
  mcp: {
    head: typeOf(mcp.querySelector('.head > span')),
    names: Array.from(mcp.querySelectorAll('.link .name .text')).map(typeOf),
    states: Array.from(mcp.querySelectorAll('.link .state')).map(typeOf),
  },
}
report.headHeights = [rect(local.querySelector('.head')).height, rect(mcp.querySelector('.head')).height]
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/%(style)s">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; position: relative; }</style>
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


async def _read_report(port: int, limit: float = 120.0) -> dict:
    """The page's report, read over the debug port."""
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
        raw = ""
        while time.monotonic() < end and not raw:
            number += 1
            expression = "document.getElementById('ergebnis')?.textContent || ''"
            await connection.send(
                json.dumps(
                    {
                        "id": number,
                        "method": "Runtime.evaluate",
                        "params": {"expression": expression, "returnByValue": True},
                    }
                )
            )
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    raw = response.get("result", {}).get("result", {}).get("value") or ""
                    break
            if not raw:
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-server-overview-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"overview": "../../src/teile/ServerOverview.svelte"}, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {"global": "../../src/stil/global.css", "serverstand": "../../src/lib/serverstand.svelte.js"},
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
        # The build writes the sheet of global.css beside the script, under the package's name.
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
                "--window-size=1280,900",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return asyncio.run(_read_report(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_every_chosen_model_has_its_makers_logo_or_a_letter_and_none_has_a_dash(report):
    rows = report["localRows"]
    assert len(rows) == 6
    qwen, accio, unknown, none_a, none_b, none_c = rows
    assert qwen["svg"] and accio["svg"], "a model of a known maker wears its logo"
    assert (accio["svgWidth"], accio["svgHeight"]) == (18, 18)
    assert qwen["letter"] is None and accio["letter"] is None
    # A name the house does not know keeps its first letter where the logo would stand.
    assert not unknown["svg"] and unknown["letter"] == "Z"
    # No choice: a dash, no mark.
    for row in (none_a, none_b, none_c):
        assert row["text"] == "-" and not row["svg"] and row["letter"] is None and row["markWidth"] is None
    # The mark takes the same room in every row, so the names line up.
    assert qwen["markWidth"] == accio["markWidth"] == unknown["markWidth"] == 18


def test_the_mcp_connections_are_a_table_with_the_columns_of_the_local_servers(report):
    assert len(report["mcpRows"]) == 6
    assert report["mcpHeads"][:2] == report["localHeads"][:2]
    # The Status column stands over the same x in both tables, in the head and in every row.
    assert report["mcpHeadX"] == report["localHeadX"]
    assert set(report["mcpStateX"]) == set(report["localStateX"]) == {report["localHeadX"]}
    assert report["tableLeft"][0] == report["tableLeft"][1] and report["tableWidth"][0] == report["tableWidth"][1]
    assert report["pageWidth"][0] <= report["pageWidth"][1]


def test_every_mcp_row_has_a_24_pixel_logo_a_state_word_in_its_colour_and_a_way_in(report):
    rows = {row["title"]: row for row in report["mcpRows"]}
    assert len(rows) == 6
    for row in rows.values():
        assert row["tag"] == "BUTTON" and row["chevron"]
        assert row["logoWidth"] == row["logoHeight"] == 24 and row["hasDrawing"]
        assert row["state"]
    # A connected server is green; the others are not, and their words differ from it.
    connected = [row for row in rows.values() if row["stateClass"].endswith("gruen")]
    # Connected and starting (green), in front of the others, as the MCP page orders its cards.
    assert len(connected) == 3
    classes = [row["stateClass"].endswith("gruen") for row in report["mcpRows"]]
    assert classes == sorted(classes, reverse=True)
    assert len({row["color"] for row in connected}) == 1
    others = [row for row in rows.values() if not row["stateClass"].endswith("gruen")]
    assert all(row["color"] != connected[0]["color"] for row in others), report["mcpRows"]
    assert all(row["state"] != connected[0]["state"] for row in others)
    # A missing key is red and names the variables, on the one line every row has.
    assert rows["atlas"]["stateClass"].endswith("rot") and rows["Notion"]["stateClass"].endswith("still")
    keyless = rows["keyless"]
    assert keyless["stateClass"].endswith("rot") and "GITHUB_PERSONAL_ACCESS_TOKEN" in keyless["state"]


def test_the_rows_of_both_tables_are_equally_high(report):
    assert set(report["rowHeights"][:6]) == set(report["rowHeights"][6:]) == {56}


def test_the_tables_carry_the_type_of_the_drawing(report):
    """Heads half-bold 11 px in the quiet text colour, names half-bold 13 px,
    port and model plain 13 px, both in the text colour; the words of the
    state keep their medium weight. Both tables alike."""
    quiet, text = report["colours"]["quiet"], report["colours"]["text"]
    assert quiet != text, "the two colours are told apart"
    for table, rows in (("local", 6), ("mcp", 6)):
        found = report["type"][table]
        assert found["head"] == {"weight": "600", "size": "11px", "color": quiet}, table
        # Every row, not the first alone.
        assert found["names"] == [{"weight": "600", "size": "13px", "color": text}] * rows, table
        assert [s["weight"] for s in found["states"]] == ["500"] * rows, table
        assert {s["size"] for s in found["states"]} == {"13px"}, table
    local = report["type"]["local"]
    assert local["ports"] == [{"weight": "400", "size": "13px", "color": text}] * 6
    assert local["models"] == [{"weight": "400", "size": "13px", "color": text}] * 6


def test_the_type_changes_nothing_of_the_height_of_the_rows(report):
    assert report["headHeights"] == [34, 34]
