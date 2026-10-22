"""Chats answer side by side, in a real browser: a send in one chat never waits
for an answer that is running in another.

`eingabe.svelte.js`, `chatlauf.svelte.js` and `zustand.svelte.js` are built as
shipped; only the service is made up: every answer stream sends its first
words at once and then waits on a gate the page opens, so any number of answers
can be held open at the same time. The page is driven the way the hand does it:
words into the bar, Enter, "New chat", words, Enter.

* chat A answers with its stream open; the page goes to the empty start page and
  a send there creates chat B and starts it — both stand in `zustand.laeuft`,
  no notice says an answer is already being generated, and what the rest of each
  answer writes lands in its own chat;
* six chats are started one after another from the start page, all six run at
  once, each with its own words;
* nothing is loosened inside one chat: a message typed while its chat answers
  still lines up (no second stream), and "New answer" in a running chat still
  reports that an answer is already being generated.

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

ENTRY_JS = """import { zustand, neuerChat, nachrichtenSetzen } from '../../src/lib/zustand.svelte.js'
import { chatRun } from '../../src/lib/chatlauf.svelte.js'
import { chatEingabe } from '../../src/lib/eingabe.svelte.js'
import { meldungen } from '../../src/lib/meldewesen.svelte.js'
import { warteschlange } from '../../src/lib/warteschlange.svelte.js'
import { texte, t } from '../../src/lib/texte.svelte.js'
import german from '../../../app/locales/de.json'

texte.katalog = german
Object.assign(window, {
  zustand, neuerChat, nachrichtenSetzen, chatRun, chatEingabe, meldungen, warteschlange, t,
})
"""

# The service, made up: every answer stream says its first words, then waits on
# the gate of its chat until the page opens it (or the run is stopped).
API_STUB = """export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
const service = (window.__service = { calls: [], gates: {}, chats: [], count: 0 })
export async function* antwortStrom(koerper, signal) {
  service.calls.push({ chat: koerper.chat_id, content: koerper.content ?? null })
  const chat = koerper.chat_id
  const gate = new Promise((open) => { service.gates[chat] = open })
  yield { typ: 'start', generation_id: 'g-' + chat, message_id: 'a-' + chat, zeitpunkt_ms: Date.now() }
  yield { typ: 'content', text: 'first-' + chat + ' ', zeitpunkt_ms: Date.now() }
  await Promise.race([
    gate,
    new Promise((_, broke) => {
      signal.addEventListener('abort', () => broke(Object.assign(new Error('aborted'), { name: 'AbortError' })))
    }),
  ])
  yield { typ: 'content', text: 'rest-' + chat, zeitpunkt_ms: Date.now() }
  await new Promise((later) => setTimeout(later, 100))
  yield { typ: 'done' }
}
export const api = new Proxy({}, {
  get(_, name) {
    if (name === 'chatAnlegen') {
      return async (daten) => {
        const chat = { id: 'chat-' + ++service.count, title: daten.title, endpoint_id: daten.endpoint_id }
        service.chats.push(chat)
        return chat
      }
    }
    if (name === 'chats') return async () => service.chats.slice()
    if (name === 'projects' || name === 'archivedChats') return async () => []
    if (name === 'nachrichten') return async () => ({ nachrichten: [], laufend: null })
    return async () => ({})
  },
})
"""

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { fileURLToPath } from 'node:url'

const stub = fileURLToPath(new URL('./api_stub.js', import.meta.url))

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  logLevel: 'error',
  resolve: { alias: [{ find: /^(?:\\.|.*\\/lib)\\/api\\.js$/, replacement: stub }] },
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
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const { zustand, neuerChat, nachrichtenSetzen, chatEingabe, chatRun, meldungen, warteschlange, t } = window
const service = window.__service

// Every notice that ever stood, and the longest text each running answer wrote.
const notices = new Set()
const written = {}
setInterval(() => {
  for (const meldung of meldungen.liste) notices.add(meldung.text)
  for (const [chat, row] of Object.entries(zustand.laufenderPlatzhalter)) {
    if (row) written[chat] = row.content
  }
}, 10)
const until = async (test, limit = 4000) => {
  const end = performance.now() + limit
  while (performance.now() < end) {
    if (test()) return true
    await wait(20)
  }
  return false
}
const running = () => Object.keys(zustand.laeuft).sort()
const busyText = t('eingabe.laeuft_schon')

// From the empty start page: type the words, press Enter, and wait until that
// chat's run stands.
const startFromTheStartPage = async (words) => {
  neuerChat()
  const before = running().length
  chatEingabe.text = words
  await chatEingabe.absenden()
  await until(() => running().length === before + 1, 1500)
  return zustand.aktiverChat
}
const openGate = (chat) => service.gates[chat]?.()
const allDone = () => until(() => running().length === 0, 6000)

zustand.modellId = 'm'
nachrichtenSetzen(null, [])

// 1. Chat A answers with its stream open; the start page; a send there.
const chatA = await startFromTheStartPage('Say alpha')
report.afterA = { chat: chatA, running: running() }
const chatB = await startFromTheStartPage('Say bravo')
report.afterB = { chat: chatB, running: running(), busyNotice: notices.has(busyText) }
report.callsWhileBothRun = service.calls.slice()
openGate(chatA)
openGate(chatB)
report.bothDone = await allDone()
await wait(150)
report.written = { ...written }
report.expectedA = chatA
report.expectedB = chatB

// 2. Six chats, one after another from the start page, all running at once.
const words = ['one', 'two', 'three', 'four', 'five', 'six']
const six = []
for (const word of words) six.push(await startFromTheStartPage('Reply only with the word ' + word))
report.six = { chats: six, running: running(), distinct: new Set(six).size, busyNotice: notices.has(busyText) }
report.sixCalls = service.calls.slice(2).map((call) => ({ chat: call.chat, content: call.content }))
for (const chat of six) openGate(chat)
report.sixDone = await allDone()
await wait(150)
report.sixWritten = six.map((chat) => written[chat])

// 3. Inside one chat nothing is loosened.
const chatP = await startFromTheStartPage('Say papa')
const callsBefore = service.calls.length
notices.delete(busyText)
chatEingabe.text = 'typed while it answers'
await chatEingabe.absenden()
await wait(200)
report.queued = {
  queue: warteschlange.liste.filter((entry) => entry.chatId === chatP).length,
  newCalls: service.calls.length - callsBefore,
  busyNotice: notices.has(busyText),
}
await chatRun.neuErzeugen('a-' + chatP)
await wait(200)
report.again = { busyNotice: notices.has(busyText), newCalls: service.calls.length - callsBefore }
openGate(chatP)
await wait(300)

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>chats</title>
<style>body { margin: 0; background: #fff; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  window.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16)
  window.cancelAnimationFrame = (id) => clearTimeout(id)
</script>
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
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _read_result(port: int, limit: float = 180.0) -> str:
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
    async with websockets.connect(address, max_size=16 * 1024 * 1024) as connection:
        number = 0
        while time.monotonic() < end:
            number += 1
            await connection.send(json.dumps({
                "id": number,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.getElementById('ergebnis')?.textContent || ''",
                           "returnByValue": True},
            }))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    break
            value = response.get("result", {}).get("result", {}).get("value", "")
            if value:
                return value
            await asyncio.sleep(0.25)
    return ""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-sidebyside-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "api_stub.js").write_text(API_STUB, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run", "--mute-audio",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=900,1400", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_read_result(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
        assert raw, "the page reported nothing"
        result = json.loads(raw)
        assert "failure" not in result, result["failure"]
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_send_on_the_start_page_starts_a_new_chat_while_another_answers(report):
    assert report["afterA"]["running"] == [report["afterA"]["chat"]]
    chat_a, chat_b = report["afterA"]["chat"], report["afterB"]["chat"]
    assert chat_a != chat_b
    assert report["afterB"]["running"] == sorted([chat_a, chat_b])
    assert [call["content"] for call in report["callsWhileBothRun"]] == ["Say alpha", "Say bravo"]


def test_the_second_send_gets_no_notice_that_an_answer_is_running(report):
    assert report["afterB"]["busyNotice"] is False


def test_the_rest_of_each_answer_lands_in_its_own_chat(report):
    assert report["bothDone"] is True
    chat_a, chat_b = report["expectedA"], report["expectedB"]
    assert report["written"][chat_a] == f"first-{chat_a} rest-{chat_a}"
    assert report["written"][chat_b] == f"first-{chat_b} rest-{chat_b}"


def test_six_chats_started_one_after_another_all_run_at_once(report):
    six = report["six"]
    assert six["distinct"] == 6
    assert six["running"] == sorted(six["chats"])
    assert six["busyNotice"] is False
    contents = [call["content"] for call in report["sixCalls"]]
    assert contents == [f"Reply only with the word {word}" for word in
                        ("one", "two", "three", "four", "five", "six")]
    assert [call["chat"] for call in report["sixCalls"]] == six["chats"]


def test_each_of_the_six_answers_ends_in_its_own_chat(report):
    assert report["sixDone"] is True
    for chat, text in zip(report["six"]["chats"], report["sixWritten"], strict=True):
        assert text == f"first-{chat} rest-{chat}"


def test_a_message_typed_in_a_running_chat_still_lines_up(report):
    assert report["queued"] == {"queue": 1, "newCalls": 0, "busyNotice": False}


def test_a_new_answer_in_a_running_chat_still_reports_that_one_is_running(report):
    assert report["again"] == {"busyNotice": True, "newCalls": 0}
