"""The phone page attaches to an answer that is still being written, measured
in a real browser.

`phone/ChatView.svelte` is built as shipped, with the real chat state and the
real shared run, and drawn in headless Chrome on a phone-sized page with touch
events. The service is made up in the page: it names the chats, one of them
with a run that is still going, and it holds the event stream of that run
open so the test can let text arrive in it; like the real one, the stream
plays the answer again from its first event. The page reports:

* opening a chat whose answer is still being written asks for the stream of
  that run exactly once, and text that arrives in the stream afterwards
  shows in the answer, with the stop button standing;
* opening a chat without a running answer asks for no stream;
* a signal owed to a chat that is not on screen asks for nothing and stays
  where it is until that chat is opened.

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
  import ChatView from %(chat)r
</script>

<div id="phone" style="width: 390px; height: 780px; display: flex; flex-direction: column; position: relative; overflow: hidden;">
  <ChatView />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { zustand, chatOeffnen } from %(zustand)r

const enc = new TextEncoder()
const calls = []
const streams = {}
const chats = {
  c0: { nachrichten: [
    { id: 'q0', role: 'user', content: 'Idle question' },
    { id: 'a0', role: 'assistant', content: 'Idle answer', zustand: 'fertig' },
  ], laufend: null, frage: null },
  c1: { nachrichten: [
    { id: 'q1', role: 'user', content: 'First question' },
    { id: 'a1', role: 'assistant', content: 'Half an answer. ', zustand: 'laeuft' },
  ], laufend: { generation_id: 'g1', message_id: 'a1' }, frage: null },
  c2: { nachrichten: [
    { id: 'q2', role: 'user', content: 'Second question' },
    { id: 'a2', role: 'assistant', content: 'Half of another. ', zustand: 'laeuft' },
  ], laufend: { generation_id: 'g2', message_id: 'a2' }, frage: null },
}
const json = (body) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
window.fetch = async (address) => {
  const full = String(address)
  const path = full.replace(/^.*?\\/api\\/v1/, '')
  calls.push(path)
  const stream = path.match(/^\\/chat\\/stream\\/([^?]+)/)
  if (stream) {
    const body = new ReadableStream({ start(controller) { streams[stream[1]] = controller } })
    return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
  }
  const messages = path.match(/^\\/chats\\/([^/]+)\\/messages/)
  if (messages) return json(chats[messages[1]] || { nachrichten: [], laufend: null, frage: null })
  if (path.startsWith('/chats')) return json([])
  return json({})
}
window.__calls = calls
window.__send = (generation, event) => streams[generation] && streams[generation].enqueue(enc.encode('data: ' + JSON.stringify(event) + '\\n\\n'))
window.__streams = streams
window.zustand = zustand
window.chatOeffnen = chatOeffnen
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
const until = async (check, limit = 4000) => {
  for (let waited = 0; waited < limit; waited += 50) {
    if (check()) return true
    await wait(50)
  }
  return false
}
const streamCalls = () => window.__calls.filter((path) => path.startsWith('/chat/stream/'))
const history = () => (document.querySelector('.verlauf')?.textContent || '')
const stopButton = () => Boolean(document.querySelector('.act.stops'))
await wait(400)

// a chat without a running answer asks for no stream
await window.chatOeffnen('c0')
await until(() => history().includes('Idle answer'))
await wait(700)
report.idle = {
  streams: streamCalls(),
  shows: history().includes('Idle answer'),
  owed: Object.keys(window.zustand.wiederanhaengen),
  stop: stopButton(),
}

// a signal owed to a chat that is not on screen asks for nothing and stays
window.zustand.wiederanhaengen.c2 = { chatId: 'c2', generationId: 'g2', messageId: 'a2' }
await wait(700)
report.other = {
  streams: streamCalls(),
  owed: Object.keys(window.zustand.wiederanhaengen),
  stop: stopButton(),
}

// opened, that chat is attached to once and the entry is spent
await window.chatOeffnen('c2')
await until(() => streamCalls().length > 0)
await wait(400)
window.__send('g2', { typ: 'start', generation_id: 'g2', message_id: 'a2' })
window.__send('g2', { typ: 'content', text: 'Half of another. ' })
window.__send('g2', { typ: 'content', text: 'Growth of the second chat.' })
await until(() => history().includes('Growth of the second chat.'))
report.opened = {
  streams: streamCalls(),
  owed: Object.keys(window.zustand.wiederanhaengen),
  grows: history().includes('Growth of the second chat.'),
  keeps: history().includes('Half of another.'),
  stop: stopButton(),
}

// a chat opened with a running answer grows from the stream, the stop button stands
await window.chatOeffnen('c1')
await until(() => streamCalls().some((path) => path.includes('/g1')))
await wait(400)
window.__send('g1', { typ: 'start', generation_id: 'g1', message_id: 'a1' })
window.__send('g1', { typ: 'content', text: 'Half an answer. ' })
window.__send('g1', { typ: 'content', text: 'First growth.' })
await until(() => history().includes('First growth.'))
const afterFirst = history()
window.__send('g1', { typ: 'content', text: ' Second growth.' })
await until(() => history().includes('Second growth.'))
report.running = {
  streams: streamCalls().filter((path) => path.includes('/g1')),
  firstGrowth: afterFirst.includes('First growth.'),
  secondGrowth: history().includes('Second growth.'),
  keeps: history().includes('Half an answer.'),
  stop: stopButton(),
  owed: Object.keys(window.zustand.wiederanhaengen),
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 390px; height: 780px; position: relative; }</style>
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


def _run_case(cases: str) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-phone-reattach-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"chat": "../../src/phone/ChatView.svelte"}, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
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
        (folder / "measure.html").write_text(PAGE % {"cases": cases}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--touch-events=enabled",
                "--window-size=390,780",
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
    return _run_case(CASES)


def test_a_chat_opened_with_a_running_answer_asks_for_its_stream_once(measured):
    running = measured["running"]
    assert len(running["streams"]) == 1, running["streams"]
    assert running["streams"][0].startswith("/chat/stream/g1"), running["streams"]
    assert running["owed"] == [], running["owed"]


def test_text_that_arrives_in_the_stream_shows_in_the_answer_and_the_stop_button_stands(measured):
    running = measured["running"]
    assert running["firstGrowth"] and running["secondGrowth"], running
    assert running["keeps"], "the stored start of the answer went missing"
    assert running["stop"], "no stop button under a running answer"


def test_silence_a_chat_without_a_running_answer_asks_for_no_stream(measured):
    idle = measured["idle"]
    assert idle["shows"], idle
    assert idle["streams"] == [], idle["streams"]
    assert idle["owed"] == [], idle["owed"]
    assert not idle["stop"], "a stop button under an answer that is over"


def test_silence_a_signal_for_another_chat_waits_until_that_chat_is_opened(measured):
    other, opened = measured["other"], measured["opened"]
    assert other["streams"] == [], other["streams"]
    assert other["owed"] == ["c2"], other["owed"]
    assert not other["stop"]
    assert len(opened["streams"]) == 1 and opened["streams"][0].startswith("/chat/stream/g2"), opened["streams"]
    assert opened["owed"] == [], opened["owed"]
    assert opened["grows"] and opened["keeps"], opened
