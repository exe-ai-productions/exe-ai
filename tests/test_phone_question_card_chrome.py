"""The phone's permission card names the file, not its content, in a real
browser.

`phone/QuestionCard.svelte` is built as shipped and drawn in headless Chrome
on a phone-sized page. A tool asking for permission shows one line of what
the decision rests on: the command with a dollar sign for a shell call, and
for any other call the argument it is about, plainly. A file write lists its
text before its path (`content` first), and the card showed that text as if
it were a command; now it names the file, with slashes like every path. The
page makes up the questions; the shared question store is a stand-in with the
same shape, and nothing is asked of the service. Skipped where there is no
Chrome or no node, like the other browser tests.
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

ENTRY_JS = """import { mount } from 'svelte'
import QuestionCard from '../../src/phone/QuestionCard.svelte'
import '../../src/stil/global.css'
import german from '@@GERMAN@@'
import { texte } from '../../src/lib/texte.svelte.js'

texte.katalog = german
texte.sprache = 'de'
const CASES = {
  write: { name: 'write_file', argumente: { content: 'Eine gute Frage', path: 'notizen\\\\absatz1.txt' } },
  shell: { name: 'run_command', argumente: { command: 'ls -la' } },
  shellAndMore: { name: 'run_command', argumente: { cwd: '/tmp', command: 'ls -la' } },
  none: { name: 'list_tools', argumente: {} },
  none_reason: { name: 'list_tools', argumente: {}, grund: 'The reason stays.' },
  text: { name: 'speak', argumente: { text: 'Hallo zusammen', volume: 3 } },
}
const wurzel = document.getElementById('wurzel')
for (const [key, question] of Object.entries(CASES)) {
  const holder = document.createElement('div')
  holder.id = 'case-' + key
  holder.style.cssText = 'width: 360px; margin: 0 0 16px'
  wurzel.appendChild(holder)
  const questions = {
    standing: { kind: 'tool', question: { chatId: 'c-' + key, aufrufId: key, ...question } },
    modelName: 'Model',
    answerTool() {},
    answerAsk() {},
    later() {},
  }
  mount(QuestionCard, { target: holder, props: { questions } })
}
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
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
await wait(800)
const line = (key) => {
  const node = document.querySelector('#case-' + key + ' .command')
  if (!node) return null
  return { text: node.textContent.replace(/\s+/g, ' ').trim(), dollar: !!node.querySelector('.quiet'), tag: node.tagName }
}
const keys = ['write', 'shell', 'shellAndMore', 'none', 'none_reason', 'text']
for (const key of keys) {
  report[key] = {
    line: line(key),
    details: !!document.querySelector('#case-' + key + ' .details'),
    reason: document.querySelector('#case-' + key + ' .reason')?.textContent.replace(/\s+/g, ' ').trim() || null,
    arguments: document.querySelectorAll('#case-' + key + ' .arguments dt').length,
  }
}
// Unfolding lists every argument, in the order the model wrote them.
document.querySelector('#case-write button.command').click()
await wait(400)
report.unfolded = {
  names: Array.from(document.querySelectorAll('#case-write .arguments dt')).map((n) => n.textContent),
  values: Array.from(document.querySelectorAll('#case-write .arguments dd')).map((n) => n.textContent),
  expanded: document.querySelector('#case-write button.command').getAttribute('aria-expanded'),
  line: line('write'),
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 375px; padding: 12px; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      @@CASES@@
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
    folder = FRONTEND / "node_modules" / f".harness-phone-question-card-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        entry = ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", CASES), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--touch-events=enabled",
                "--window-size=375,812",
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
def report() -> dict:
    return _run_case()


def test_a_file_write_names_the_file_with_slashes_and_no_dollar_sign(report):
    line = report["write"]["line"]
    assert line, report["write"]
    assert line["text"] == "notizen/absatz1.txt", line
    assert not line["dollar"], line
    assert "Eine gute Frage" not in line["text"], line


def test_a_shell_call_shows_its_command_with_a_dollar_sign(report):
    line = report["shell"]["line"]
    assert line and line["dollar"] and line["text"] == "$ ls -la", line
    # A command that is not the first argument still is the line.
    more = report["shellAndMore"]["line"]
    assert more and more["dollar"] and more["text"].startswith("$ ls -la"), more


def test_a_call_without_a_path_or_command_shows_its_first_text_plainly(report):
    line = report["text"]["line"]
    assert line and line["text"] == "Hallo zusammen" and not line["dollar"], line


def test_silence_a_call_without_arguments_shows_no_line_and_keeps_its_reason(report):
    assert report["none"]["line"] is None and not report["none"]["details"], report["none"]
    assert report["none_reason"]["line"] is None and report["none_reason"]["reason"] == "The reason stays.", report["none_reason"]


def test_silence_unfolding_lists_every_argument_in_the_models_order(report):
    unfolded = report["unfolded"]
    assert unfolded["names"] == ["content", "path"], unfolded
    assert unfolded["values"] == ["Eine gute Frage", "notizen\\absatz1.txt"], unfolded
    assert unfolded["expanded"] == "true" and unfolded["line"]["text"] == "notizen/absatz1.txt", unfolded
