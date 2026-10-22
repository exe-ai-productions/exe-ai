"""The head of a report in the reader, measured in a real browser.

`Bildschau.svelte` is built as shipped and drawn in headless Chrome at
1920 x 1080 with a report made up in the page (the service is not asked).
With a task of three paragraphs over about twenty lines the head shows: the
agent's tile on the top edge of the head, the task beginning beside it on the
tile's height, the dot of the ending beside the first line, the task at most
two lines tall with a fold under it (`aria-expanded` false); a press opens the
whole task with an empty line between its paragraphs, a second press folds it
back to two lines; closing the reader and opening the same report starts
folded again. A task of one line shows no fold, and the head keeps its agent,
its time and its text.

The build of the harness links the built stylesheet, so every size probe
reads the real tokens.

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
  import Bildschau from %(reader)r
</script>

<Bildschau />
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { texte } from %(texts)r
import { showReport, closeReader } from %(reader)r

texte.sprache = 'en'
texte.katalog = english
window.fetch = async () =>
  new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
window.__show = showReport
window.__close = closeReader
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
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const round = (value) => Math.round(value * 10) / 10
const paragraph = (word) => (word + ' ').repeat(60).trim()
const LONG = [paragraph('alpha'), paragraph('bravo'), paragraph('charlie')].join('\n\n')
const make = (task) => ({
  name: 'research-j1', agent: 'research', colour: '#5fa8d3', task, time: '12:00', state: 'fertig',
  chain: '', reason: '', timedOut: false, text: 'The text of the report.', plain: false, facts: () => null,
})
const head = () => document.querySelector('.head')
const taskNode = () => document.querySelector('.head .task')
const foldNode = () => document.querySelector('.head .fold')
const rect = (node) => {
  const r = node.getBoundingClientRect()
  return { x: round(r.x), y: round(r.y), width: round(r.width), height: round(r.height), right: round(r.right), bottom: round(r.bottom) }
}
const measure = () => {
  const task = taskNode()
  const style = getComputedStyle(task)
  const fold = foldNode()
  const dot = document.querySelector('.head .dotbox > *')
  return {
    head: rect(head()), tile: rect(head().querySelector('.tile')), task: rect(task),
    lineHeight: round(parseFloat(style.lineHeight)), whiteSpace: style.whiteSpace,
    breaks: task.innerText.includes('\n\n'),
    fold: fold ? { ...rect(fold), expanded: fold.getAttribute('aria-expanded'), label: fold.getAttribute('aria-label') === task.textContent } : null,
    dot: dot ? rect(dot) : null,
    agent: document.querySelector('.head .agent')?.textContent.trim(),
    time: document.querySelector('.head .time')?.textContent.trim(),
    body: document.querySelector('.berichttext')?.textContent.trim(),
  }
}
const open = async (task) => {
  window.__show(make(task))
  for (let k = 0; k < 60 && !head(); k += 1) await wait(100)
  await wait(400)
}
const report = {}
await open(LONG)
report.folded = measure()
foldNode().click()
await wait(300)
report.unfolded = measure()
foldNode().click()
await wait(300)
report.folded_again = measure()
foldNode().click()
await wait(300)
window.__close()
await wait(300)
await open(LONG)
report.reopened = measure()
window.__close()
await wait(300)
await open('One short line')
report.short = measure()
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
%(links)s
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
    folder = FRONTEND / "node_modules" / f".harness-report-head-fold-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"reader": "../../src/teile/Bildschau.svelte"},
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "reader": "../../src/lib/bildschau.svelte.js",
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
        (folder / "measure.html").write_text(
            PAGE % {"cases": CASES, "links": links}, encoding="utf-8"
        )
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


def test_the_tile_stands_on_the_top_edge_and_the_task_begins_beside_it_on_its_height(measured):
    folded = measured["folded"]
    assert abs(folded["tile"]["y"] - folded["head"]["y"]) <= 1, folded
    assert folded["task"]["x"] >= folded["tile"]["right"], folded
    assert abs(folded["task"]["y"] - folded["tile"]["y"]) <= 1, folded


def test_the_dot_stands_beside_the_first_line_of_the_task(measured):
    folded = measured["folded"]
    first_line_middle = folded["task"]["y"] + folded["lineHeight"] / 2
    assert abs(folded["dot"]["y"] + folded["dot"]["height"] / 2 - first_line_middle) <= 2, folded
    assert folded["dot"]["right"] <= folded["head"]["right"] + 0.5, folded


def test_a_long_task_is_two_lines_tall_with_a_closed_fold_under_it(measured):
    folded = measured["folded"]
    assert folded["task"]["height"] <= 2 * folded["lineHeight"] + 1, folded
    fold = folded["fold"]
    assert fold and fold["expanded"] == "false" and fold["label"], folded
    assert fold["y"] >= folded["task"]["bottom"] - 1, folded


def test_the_fold_opens_the_whole_task_with_an_empty_line_between_its_paragraphs(measured):
    unfolded = measured["unfolded"]
    assert unfolded["whiteSpace"] == "pre-wrap" and unfolded["breaks"], unfolded
    assert unfolded["fold"]["expanded"] == "true", unfolded
    assert unfolded["task"]["height"] > 10 * unfolded["lineHeight"], unfolded
    assert abs(unfolded["tile"]["y"] - unfolded["head"]["y"]) <= 1, unfolded
    assert abs(unfolded["task"]["y"] - unfolded["tile"]["y"]) <= 1, unfolded


def test_a_second_press_folds_it_back_to_two_lines(measured):
    again = measured["folded_again"]
    assert again["task"]["height"] <= 2 * again["lineHeight"] + 1, again
    assert again["fold"]["expanded"] == "false", again


def test_a_report_opened_again_starts_folded(measured):
    reopened = measured["reopened"]
    assert reopened["task"]["height"] <= 2 * reopened["lineHeight"] + 1, reopened
    assert reopened["fold"]["expanded"] == "false", reopened


def test_silence_a_task_of_one_line_has_no_fold_and_the_head_keeps_its_parts(measured):
    short = measured["short"]
    assert short["fold"] is None, short
    assert short["task"]["height"] <= short["lineHeight"] + 1, short
    assert short["agent"] == "research" and short["time"] == "12:00", short
    assert short["body"] == "The text of the report.", short
    assert abs(short["tile"]["y"] - short["head"]["y"]) <= 1, short
