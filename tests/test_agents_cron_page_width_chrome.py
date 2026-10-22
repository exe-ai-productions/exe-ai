"""The pages of the agents and the schedules are laid out by their own width,
measured in a real browser.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome, with
the service made up in the page, in frames of different widths. A page 640 px
wide or narrower puts the chosen entry under the list, as wide as the page,
nothing cut off; a page wider than that keeps the list beside it, at the width
it always had; and in the schedules the sentence of a stopped entry asks for the
singular sentence at one failed run and for the plural one at three. The width of the window
does not matter, only that of the page. Skipped where there is no Chrome or no
node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import re
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

<div id="frame" style="width: 720px; height: 800px; position: relative;">
  <SystemPrompt {offen} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { zustand } from %(zustand)r

const LONG = 'A researcher with a rather long name and a rather long description of what it does all day'
const stamp = (minutes) => new Date(Date.now() + minutes * 60000).toISOString()
const answers = {
  '/agent-files': [{ name: 'a-researcher-with-a-long-name', kaputt: null }],
  '/agents': [{
    name: 'a-researcher-with-a-long-name', description: LONG,
    tools: ['read_file', 'web_search', 'run_command', 'list_dir', 'write_file', 'read_webpage'],
    max_rounds: 20, max_minutes: 30, max_tokens: null, max_command_seconds: 60,
  }],
  '/agents/a-researcher-with-a-long-name': { prompt: Array.from({ length: 40 }, (_, k) => 'Step ' + k + ': look at the next thing.').join('\\n') },
  '/cronjobs': [
    { id: 'one', agent: 'a', task: 'Check the inbox', zeitplan: '*/15 * * * *', aktiv: false, fehlversuche: 1, fehlergrenze: 1,
      letzter_ausgang: 'fehlgeschlagen', naechste_faelligkeit: null, skript: null },
    { id: 'three', agent: 'a', task: 'Check the weather', zeitplan: '0 * * * *', aktiv: false, fehlversuche: 3, fehlergrenze: 3,
      letzter_ausgang: 'fehlgeschlagen', naechste_faelligkeit: null, skript: null },
    { id: 'live', agent: 'a', task: 'Check the news', zeitplan: '0 8 * * *', aktiv: true, fehlversuche: 0, fehlergrenze: 3,
      letzter_ausgang: null, naechste_faelligkeit: stamp(60), skript: null },
  ],
  '/cronjobs/runs/all': [],
  '/tools': { werkzeuge: [] },
  '/tools/servers': [],
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
zustand.promptOffen = true
zustand.promptStart = 'agent'
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
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }
}
const columnsOf = (grid) => getComputedStyle(grid).gridTemplateColumns.split(' ').length
const measure = async (page, width) => {
  document.getElementById('frame').style.width = width + 'px'
  await wait(500)
  const grid = document.querySelector('.zweispaltig')
  const list = grid.querySelector('.liste')
  const detail = grid.querySelector('.einzel, .rechtsteil')
  const cut = Array.from(grid.querySelectorAll('.kopf, .kopf .titel, .kopf strong, .knoepfe')).filter((n) => n.scrollWidth > n.clientWidth + 1).length
  const buttons = Array.from(grid.querySelectorAll('.knoepfe button')).map((b) => box(b))
  return {
    page: box(grid), columns: columnsOf(grid), list: box(list), detail: box(detail),
    cut, buttons, prompt: grid.querySelector('.kasten-text') ? parseFloat(getComputedStyle(grid.querySelector('.kasten-text')).height) : null,
    chosen: Boolean(grid.querySelector('.einzel .knoepfe')),
    listOverflow: getComputedStyle(list).overflowY, detailOverflow: getComputedStyle(detail).overflowY,
  }
}
const WIDTHS = [720, 724, 1400, 1600]
for (const page of ['agent', 'cronjobs']) {
  window.__zustand.promptStart = page
  for (let k = 0; k < 80 && !(document.querySelector('.zweispaltig .zeile')); k += 1) await wait(100)
  await wait(500)
  if (page === 'agent') {
    // The files arrive after the page has chosen its first entry: choose the agent itself.
    Array.from(document.querySelectorAll('.zweispaltig .liste .zeile')).find((r) => r.textContent.includes('a-researcher'))?.click()
    await wait(600)
  }
  report[page] = {}
  for (const width of WIDTHS) report[page][width] = await measure(page, width)
}
// The sentence of a stopped schedule: one failed run, three failed runs.
document.getElementById('frame').style.width = '1400px'
await wait(300)
const sentences = {}
for (const id of ['one', 'three']) {
  const row = Array.from(document.querySelectorAll('.zweispaltig .zeile')).find((r) => r.textContent.includes(id === 'one' ? 'inbox' : 'weather'))
  row.click()
  await wait(700)
  sentences[id] = Array.from(document.querySelectorAll('.popup')).map((p) => p.textContent.replace(/\s+/g, ' ')).join(' | ')
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await wait(300)
}
report.sentences = sentences
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1700px; position: relative; }</style>
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
    folder = FRONTEND / "node_modules" / f".harness-agents-cron-width-{uuid4().hex}"
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
                "--window-size=1700,1200",
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


PAGES = ("agent", "cronjobs")
LIST_WIDTH = {"agent": 280, "cronjobs": 330}


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("width", ("720", "724"))
def test_the_page_is_laid_out_by_its_own_width_at_the_edge_of_640(measured, page, width):
    case = measured[page][width]
    # The page's own width: the frame less 8 px of margin on both sides and the
    # two side paddings of 32 px.
    assert abs(case["page"]["width"] - (int(width) - 80)) <= 1, case["page"]
    assert case["columns"] == (1 if width == "720" else 2), (page, width, case["columns"])


@pytest.mark.parametrize("page", PAGES)
def test_a_narrow_page_puts_the_detail_under_the_list_as_wide_as_the_page(measured, page):
    case = measured[page]["720"]
    assert case["detail"]["top"] >= case["list"]["bottom"] - 1, case
    assert abs(case["detail"]["width"] - case["page"]["width"]) <= 1, case
    assert abs(case["list"]["width"] - case["page"]["width"]) <= 1, case


def test_nothing_of_the_chosen_agent_is_cut_off_on_a_narrow_page(measured):
    case = measured["agent"]["720"]
    assert case["chosen"] and len(case["buttons"]) == 2, case
    assert case["cut"] == 0, case
    for button in case["buttons"]:
        assert button["right"] <= case["detail"]["right"] + 1, case


def test_a_long_instruction_stays_a_box_of_320_px_on_a_narrow_page(measured):
    assert abs(measured["agent"]["720"]["prompt"] - 320) <= 1, measured["agent"]["720"]["prompt"]


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("width", ("1400", "1600"))
def test_silence_a_wide_page_keeps_the_list_beside_the_detail_at_its_old_width(measured, page, width):
    case = measured[page][width]
    assert case["columns"] == 2
    assert abs(case["list"]["width"] - LIST_WIDTH[page]) <= 1, case["list"]
    assert abs(case["detail"]["left"] - case["list"]["right"] - 28) <= 1, case
    # Each column still scrolls for itself.
    assert case["listOverflow"] == "auto" and case["detailOverflow"] == "auto", case


@pytest.mark.parametrize("page", PAGES)
def test_the_detail_takes_what_the_list_leaves_at_the_edge_where_the_window_cut_it(measured, page):
    case = measured[page]["724"]
    assert abs(case["detail"]["width"] - (case["page"]["width"] - LIST_WIDTH[page] - 28)) <= 1, case


def test_the_stopped_schedule_asks_for_the_singular_sentence_at_one_failed_run(measured):
    """The page draws no catalogue here, so the key it asks for is what shows;
    its sentence is the catalogue's (tests/test_cron_singular_lines.py)."""
    one, three = measured["sentences"]["one"], measured["sentences"]["three"]
    assert re.search(r"cronjobs\.angehalten_eins\b", one), one
    assert re.search(r"cronjobs\.angehalten(?![\w])", three) and "angehalten_eins" not in three, three
