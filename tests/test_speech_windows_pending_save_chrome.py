"""A value typed a moment before closing the window, or a moment before
"Start", is written — in the clean-up server's window and in the speech
server's, in a real browser.

The windows wrote each field a beat after its last change, and the timer was
cleared when the window went away and was not waited for by "Start": a value
typed and then closed within the beat was lost, and a start right after the
change ran on the old value while the locked window showed the new one. The
real windows are built as they ship, with only the service's answers
replaced (`lib/api.js` by a stand-in that keeps the stored settings and a
list of the calls), and driven in headless Chrome.

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
  import Bereinigungsserver from %(bereinigung)r
  import Sprachserver from %(sprach)r
  import { scene } from './scene.svelte.js'
</script>

<div style="width: 1000px; margin: 0 auto;">
  {#if scene.show === 'bereinigung'}<Bereinigungsserver />{/if}
  {#if scene.show === 'sprach'}<Sprachserver />{/if}
</div>
"""

SCENE_JS = "export const scene = $state({ show: null })\n"

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import %(global)r

window.scene = scene
mount(Shell, { target: document.getElementById('root') })
"""

# The service's answers, kept in the page: the stored settings and the list
# of calls with their order. Anything not listed answers with an empty set.
API_STUB = """const stub = (window.__stub = { settings: { diktat: {}, embedding: {} }, calls: [] })
const copy = (value) => JSON.parse(JSON.stringify(value))
const putz = { putzkontext: 2048, putzschichten: 99, putzfaeden: 0, putztemperatur: 0, putztop_k: 0,
  putztop_p: 1, putzmin_p: 0, putzstrafe: 1 }
const program = { programm: '/bin/llama-server', version: 'b1', updatable: false, restorable: false }
const works = {
  sprache: 'auto', anweisung: 'x', bereinigung: 'aus', putzmodell: 'clean.gguf', bereinigung_anweisung: 'y',
  vorlesen: true, keep_model_in_memory: true, conversation_pause_seconds: 3, stimme: '', stimmprobe: '',
  stimmsprache: '', stimmtemperatur: 0.9, stimmtop_k: 50, stimmtop_p: 1, stimmmin_p: 0, stimmstrafe: 1.05,
  stimmschichten: 99, stimmfaeden: 0, gespraechsanweisung: 'z', automatik: false, microphone_key: 'Meta+Alt',
  ...putz,
}
const running = { cleanup: false, speech: false }
const cleanup = () => ({
  ...program, ordner: '/m', modelle: [{ name: 'clean.gguf', groesse_gb: 1 }], laeuft: running.cleanup,
  modell: null, port: 8085, kerne: 8, unknown_architecture: null, diktat_vorgaben: copy(works),
})
const speech = () => ({
  ...program, ordner: '/m', modelle: [{ name: 'voice.gguf', groesse_gb: 1 }], mmproj: [],
  projektoren: { 'voice.gguf': 'mm.gguf' }, laeuft: running.speech, modell: null, port: 8084,
  kontext: null, schichten: null, threads: null, kerne: 8, unknown_architecture: null,
  vorgaben: { kontext: 4096, schichten: 99, threads: 0 }, diktat_vorgaben: copy(works), stimmproben: [],
})
const methods = {
  bereinigungAuskunft: async () => cleanup(),
  spracheAuskunft: async () => speech(),
  bereinigungProtokoll: async () => [],
  spracheProtokoll: async () => [],
  einstellungAufgeloest: async (key) => ({ wert: copy(stub.settings[key] || {}), herkunft: {} }),
  einstellungMischen: async (scope, key, values) => {
    stub.calls.push({ name: 'patch', key, values: copy(values), at: performance.now() })
    // A write takes a moment, like the real one.
    await new Promise((done) => setTimeout(done, 40))
    const row = stub.settings[key] || (stub.settings[key] = {})
    for (const [name, value] of Object.entries(values)) {
      if (value === null) delete row[name]
      else row[name] = value
    }
    return { wert: copy(row) }
  },
  bereinigungStarten: async (model, port) => {
    stub.calls.push({ name: 'start', server: 'cleanup', model, port, stored: copy(stub.settings.diktat), at: performance.now() })
    running.cleanup = true
    return { ...cleanup(), laeuft: true, port }
  },
  spracheStarten: async (model, values) => {
    stub.calls.push({ name: 'start', server: 'speech', model, values: copy(values), stored: copy(stub.settings.diktat), at: performance.now() })
    running.speech = true
    return { ...speech(), laeuft: true }
  },
}
export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* antwortStrom() {}
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
export const api = new Proxy({}, {
  get(_, name) {
    if (name in methods) return methods[name]
    return async () => ({})
  },
})
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const stub = window.__stub
const portField = () => document.querySelector('input[id$="-port"]')
const type = (field, text) => {
  field.focus()
  field.value = text
  field.dispatchEvent(new Event('input', { bubbles: true }))
  field.dispatchEvent(new Event('change', { bubbles: true }))
}
const open = async (which) => {
  scene.show = which
  for (let k = 0; k < 60 && !(portField() && portField().value); k += 1) await wait(50)
  await wait(250)
}
const close = async () => {
  scene.show = null
  await wait(300)
}
const patches = () => stub.calls.filter((c) => c.name === 'patch').map((c) => c.values)

// 1. The clean-up window: a port typed, the window gone within 100 ms.
await open('bereinigung')
report.cleanup_before = portField().value
type(portField(), '8190')
await wait(40)
await close()
report.cleanup_closed = { patches: patches(), stored: { ...stub.settings.diktat } }
await open('bereinigung')
report.cleanup_reopened = portField().value
await close()

// 2. The clean-up window: a port typed and "Start" pressed at once.
stub.calls.length = 0
await open('bereinigung')
type(portField(), '8200')
await wait(20)
const start = document.querySelector('.startknopf')
start.click()
await wait(600)
report.cleanup_start = stub.calls.map((c) => ({ ...c, at: undefined }))
await close()

// 3. The speech window: a port typed, the window gone within 100 ms.
stub.calls.length = 0
await open('sprach')
report.speech_before = portField().value
type(portField(), '8191')
await wait(40)
await close()
report.speech_closed = { patches: patches(), stored: { ...stub.settings.diktat } }
await open('sprach')
report.speech_reopened = portField().value
await close()

// 4. The speech window: typed and "Start" pressed at once.
stub.calls.length = 0
await open('sprach')
type(portField(), '8201')
await wait(20)
document.querySelector('.startknopf').click()
await wait(600)
report.speech_start = stub.calls.map((c) => ({ ...c, at: undefined }))
await close()

// 5. Silence: nothing typed, nothing written.
stub.calls.length = 0
await open('sprach')
await wait(800)
await close()
report.nothing_typed = stub.calls.filter((c) => c.name === 'patch').length

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>windows</title>
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
    folder = FRONTEND / "node_modules" / f".harness-windows-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {
                "bereinigung": "../../src/teile/Bereinigungsserver.svelte",
                "sprach": "../../src/teile/Sprachserver.svelte",
            },
            encoding="utf-8",
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "api_stub.js").write_text(API_STUB, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css"}, encoding="utf-8"
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [str(FRONTEND / "node_modules" / ".bin" / "vite"), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": "const { scene } = window;\n" + CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1100,1200", f"--remote-debugging-port={port}",
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


def test_the_cleanup_port_typed_before_the_window_closes_is_written(report):
    assert report["cleanup_before"] == "8085"
    assert report["cleanup_closed"]["patches"] == [{"cleanup_port": 8190}], report["cleanup_closed"]
    assert report["cleanup_closed"]["stored"]["cleanup_port"] == 8190


def test_the_reopened_cleanup_window_shows_it(report):
    assert report["cleanup_reopened"] == "8190"


def test_the_start_of_the_cleanup_server_waits_for_the_write(report):
    calls = report["cleanup_start"]
    names = [call["name"] for call in calls]
    assert names == ["patch", "start"], calls
    assert calls[0]["values"] == {"cleanup_port": 8200}
    assert calls[1]["stored"]["cleanup_port"] == 8200
    assert calls[1]["port"] == 8200


def test_the_speech_port_typed_before_the_window_closes_is_written(report):
    assert report["speech_before"] == "8084"
    assert {"speech_port": 8191} in report["speech_closed"]["patches"], report["speech_closed"]
    assert report["speech_closed"]["stored"]["speech_port"] == 8191
    assert report["speech_reopened"] == "8191"


def test_the_start_of_the_speech_server_waits_for_the_write(report):
    calls = report["speech_start"]
    names = [call["name"] for call in calls]
    assert "patch" in names and names[-1] == "start", calls
    start = calls[-1]
    assert start["stored"]["speech_port"] == 8201
    assert start["values"]["port"] == 8201


def test_nothing_typed_nothing_written(report):
    """The silence check: opening the window and leaving it again writes no
    value — the works answers are not stored as choices."""
    assert report["nothing_typed"] == 0
