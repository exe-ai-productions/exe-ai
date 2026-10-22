"""The line of numbers under an answer, in a real browser: the cache share never
stands alone, and a stopped answer shows the same line live and after a reload.

`Nachricht.svelte` and `chatlauf.svelte.js` are built as shipped; only the
service is made up: the stream of the answer (a round that writes, its `stats`,
a second round that is stopped by the press), the call that stops it and the
stored row the window asks for afterwards (given 700 ms after the press, the
way the service stores a stopped answer a moment after the stop lands). The
page is measured every 50 ms:

* an answer whose stats carry only the cache share shows no number; with the
  time to the first token beside it, both stand; with the speed too, all three;
* the stopped answer never shows a speed — not in the moment after the press
  (the speed of the earlier round it still holds) and not after the stored row
  has come — and shows "12.3 s TTFT · 98 % Cache" and "abgebrochen" once the
  service has stored the answer, the line a reload gives;
* an answer stopped before anything was stored (no row ever comes) keeps only
  its word "abgebrochen" and shows no number.

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
  import Nachricht from '../../src/teile/Nachricht.svelte'
  import { zustand, laufVon } from '../../src/lib/zustand.svelte.js'
  import { scene } from './scene.svelte.js'
</script>

<div style="width: 640px; margin: 0 auto;">
  {#if scene.single}
    <Nachricht nachricht={scene.single} laeuft={false} istLetzte={true} neuErzeugen={() => {}} neuSenden={() => {}} />
  {/if}
  {#each zustand.nachrichten as nachricht (nachricht.id)}
    {#if nachricht.role === 'assistant'}
      <Nachricht
        {nachricht}
        istLetzte={true}
        laeuft={nachricht.zustand === 'laeuft' || Boolean(laufVon(zustand.aktiverChat))}
        neuErzeugen={() => {}}
        neuSenden={() => {}}
      />
    {/if}
  {/each}
</div>
"""

SCENE_JS = """export const scene = $state({ single: null })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import { chatRun } from '../../src/lib/chatlauf.svelte.js'
import { texte } from '../../src/lib/texte.svelte.js'
import german from '../../../app/locales/de.json'
import '../../src/stil/global.css'

texte.katalog = german
window.scene = scene
window.zustand = zustand
window.chatRun = chatRun
mount(Shell, { target: document.getElementById('root') })
"""

# The service, made up: the stream of the answer waits for the press after its
# second round starts, and the stored row is handed out 700 ms after the press.
API_STUB = """export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const service = (window.__service = { stored: null, pressedAt: 0, withRow: true, rows: [] })
export async function* antwortStrom(koerper, signal) {
  yield { typ: 'start', generation_id: 'g1', message_id: 'a1', zeitpunkt_ms: Date.now() }
  yield { typ: 'content', text: 'First round. ', zeitpunkt_ms: Date.now() }
  // The first round has measured itself: a speed that is no figure of the stopped run.
  yield {
    typ: 'stats',
    daten: { tokens_pro_sekunde: 1987.2, tempo_quelle: 'server', erstes_token_nach_sekunden: 12.3, prompt_cache_percent: 98 },
  }
  yield { typ: 'content', text: 'Second round, being written. ', zeitpunkt_ms: Date.now() }
  await new Promise((_, broke) => {
    signal.addEventListener('abort', () => broke(Object.assign(new Error('aborted'), { name: 'AbortError' })))
  })
}
export const api = new Proxy({}, {
  get(_, name) {
    if (name === 'abbrechen') {
      return async () => { service.pressedAt = performance.now(); return {} }
    }
    if (name === 'nachrichten') {
      return async () => {
        const stored = service.withRow && service.pressedAt && performance.now() - service.pressedAt > 700
        return {
          nachrichten: stored
            ? [{
                id: 'a1', role: 'assistant', content: 'First round. Second round, being written. ',
                zustand: 'abgebrochen',
                stats: { abgebrochen: true, erstes_token_nach_sekunden: 12.3, prompt_cache_percent: 98,
                         tokens_pro_sekunde: null, tempo_quelle: null },
              }]
            : [],
          laufend: null,
        }
      }
    }
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
const { scene, zustand, chatRun } = window
const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : '')
const line = () => ({
  words: Array.from(document.querySelectorAll('.messung')).map(text),
  numbers: Array.from(document.querySelectorAll('.zahl')).map(text),
})
const whole = () => text(document.body)

// 1. The cache share alone, with the wait beside it, with all three.
const one = async (stats) => {
  scene.single = null
  await wait(100)
  scene.single = { id: 's', rolle: 'assistant', role: 'assistant', content: 'An answer.', abschnitte: [{ art: 'content', text: 'An answer.' }], werkzeuge: [], stats }
  await wait(500)
  return line()
}
report.cacheAlone = await one({ prompt_cache_percent: 98 })
report.cacheAndWait = await one({ prompt_cache_percent: 98, erstes_token_nach_sekunden: 12.3 })
report.allThree = await one({ prompt_cache_percent: 98, erstes_token_nach_sekunden: 5.3, tokens_pro_sekunde: 60.4, tempo_quelle: 'server' })
scene.single = null

// 2. A run stopped by the press, measured every 50 ms.
zustand.modellId = 'm'
zustand.aktiverChat = 'c1'
zustand.nachrichtenChatId = 'c1'
const frames = []
const record = async (ms) => {
  const end = performance.now() + ms
  while (performance.now() < end) {
    const l = line()
    frames.push({ at: performance.now(), body: whole(), ...l })
    await wait(50)
  }
}
const sending = chatRun.senden('A question')
await wait(900)
const pressedAt = performance.now()
await chatRun.abbrechenVonHand()
// Measured from the moment the run has let go: while the stopped round is
// still being wound up, the window shows what any running answer shows.
await sending
frames.length = 0
await record(1800)
report.afterPress = frames.map((f) => ({ ms: Math.round(f.at - pressedAt), words: f.words, numbers: f.numbers, stopped: f.body.includes('abgebrochen') }))
report.final = line()
report.finalBody = whole()

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>line</title>
<style>body { margin: 0; background: #fff; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  window.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16)
  window.cancelAnimationFrame = (id) => clearTimeout(id)
</script>
<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">
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
    folder = FRONTEND / "node_modules" / f".harness-answerline-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
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
                program, "--headless=new", "--disable-gpu", "--no-first-run",
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


def test_the_cache_share_alone_shows_no_number(report):
    assert report["cacheAlone"]["numbers"] == []


def test_the_cache_share_beside_the_wait_shows_both(report):
    assert report["cacheAndWait"]["numbers"] == ["12.3 s", "98 %"]


def test_all_three_readings_stand_as_before(report):
    assert report["allThree"]["numbers"] == ["60", "5.3 s", "98 %"]


def test_a_stopped_answer_never_shows_a_speed_and_the_line_follows_the_stored_row(report):
    frames = report["afterPress"]
    assert frames, "no frame was measured after the press"
    for frame in frames:
        assert "TPS" not in " ".join(frame["words"]), frame
    first, last = frames[0], frames[-1]
    # Right after the press nothing is stored yet: no number stands.
    assert first["numbers"] == []
    # Once the service has stored the answer, the line a reload gives stands.
    assert last["numbers"] == ["12.3 s", "98 %"]
    assert last["stopped"] is True


def test_the_line_changes_once_from_empty_to_the_stored_one(report):
    numbers = [tuple(f["numbers"]) for f in report["afterPress"]]
    changes = sum(1 for a, b in zip(numbers, numbers[1:], strict=False) if a != b)
    assert changes == 1
