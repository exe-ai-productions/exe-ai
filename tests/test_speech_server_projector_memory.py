"""The speech server's "Wired Memory" row counts the projector of the chosen
model, and the service hands the projector sizes over.

`GET /api/v1/sprachserver` carries `projector_size_gb` like the model
server's answer does. In a real browser the real page of the speech server
(built as it ships, the service's answers replaced by a stand-in) shows
exactly the projector's size more than for the same model without one.
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
from fastapi.testclient import TestClient

from app import appfenster, prozessstopp

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"



def browser(test):
    """The tests that need the real page in Chrome; the two answers of the
    service below run everywhere."""
    test = pytest.mark.platforms(
        "darwin", reason="the browser run of the interface is checked on macOS only"
    )(test)
    return pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    )(test)


SHELL = """<script>
  import ModelleLokal from '../src/teile/ModelleLokal.svelte'
</script>

<div style="height: 1000px; display: flex; flex-direction: column;">
  <ModelleLokal offen={true} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { texte } from '../src/lib/texte.svelte.js'
import { zustand } from '../src/lib/zustand.svelte.js'
import katalog from '../../app/locales/de.json'
import '../src/stil/global.css'

texte.katalog = katalog
window.zustand = zustand
mount(Shell, { target: document.getElementById('root') })
"""

# Every call answers with what `window.answers` holds under its name, else an empty object.
API_STUB = """export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* antwortStrom() {}
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
export const api = new Proxy({}, {
  get: (_, name) => async () => {
    ;(window.calls ||= []).push(name)
    const answer = (window.answers || {})[name]
    return JSON.parse(JSON.stringify(answer === undefined ? {} : answer))
  },
})
"""

CASES = r"""
const report = { errors: [] }
window.addEventListener('error', (event) => report.errors.push(String(event.message)))
window.addEventListener('unhandledrejection', (event) => report.errors.push(String(event.reason && event.reason.message || event.reason)))
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const until = async (test, what, limit = 20000) => {
  const end = Date.now() + limit
  while (Date.now() < end) {
    try { if (test()) return true } catch (_) {}
    await wait(150)
  }
  throw new Error('timed out waiting for ' + what)
}

const file = (name) => ({ name, groesse_gb: 4.2 })
const machine = { speicher_gb: 32, kerne: 8, vorgaben: { kontext: 4096, schichten: null, port: 8080, vorladen: false }, zuordnung: {}, mtp: [], modelle: [file('chat.gguf')], projector_size_gb: {} }
const speech = (extra) => ({ ...machine, laeuft: false, port: null, modell: 'ear.gguf', modelle: [file('ear.gguf')], mmproj: [], projektoren: {}, programm: true, ...extra })
window.answers = {
  runnerAuskunft: { ...machine, laeuft: false, port: null, programm: true },
  einbettungAuskunft: { ...machine, laeuft: false, port: null, modelle: [], programm: true },
  agentenmodellAuskunft: { ...machine, laeuft: false, port: null, programm: true },
  spracheAuskunft: speech({}),
  bereinigungAuskunft: { ...machine, laeuft: false, port: null, modelle: [], programm: true },
  turboStand: { zustand: 'aus', port: 8097, programm_da: true, picture_running: false },
  speicherBlick: { wired_gb: 10, wired_limit_gb: 20, gesamt_gb: 32 },
  einstellungAufgeloest: { wert: null },
  modelle: [], modelleAlle: [], serverUebersicht: [], oauthStatus: [],
  bildmodelle: { modelle: [], families: {}, programm_da: true, standardmodell: '' },
  bildProgrammStand: {},
  bildProgrammVarianten: { varianten: [] },
  bildFamilien: [],
  bildAufbereitung: { verbesserer: 'agent', anweisungen: { sdxl: '' } },
  imageDevices: [], imageModelFiles: [], imageFamilies: {},
  runnerProtokoll: [], einbettungProtokoll: [], spracheProtokoll: [], bereinigungProtokoll: [],
  agentenmodellProtokoll: [], bildProtokoll: [],
}

const show = async (name) => {
  window.zustand.lokalWunsch = name
  const title = { server: 'Modell-Server', sprache: 'Sprach-Server' }[name]
  await until(() => document.querySelector('header.kopf .titel')?.textContent.trim() === title, name + ' page')
  await wait(900)
}

// The row of the card of the speech model: its figures and the width of its fill.
const row = () => {
  const card = [...document.querySelectorAll('.abschnitt')].find((c) => c.querySelector('.kopf .name')?.textContent.trim() === 'Speicher')
  const wired = card?.querySelector('.zeile.wired')
  if (!wired) return null
  return { figures: wired.querySelector('.schaetz').textContent.trim(), fill: parseFloat(wired.querySelector('.balken i').style.width) }
}
const voice = () => [...document.querySelectorAll('.abschnitt')].filter((c) => c.querySelector('.zeile.wired')).length

// The model with its projector (0.9 GB), then the same model without one.
window.answers.spracheAuskunft = speech({ mmproj: ['ear-mmproj.gguf'], projektoren: { 'ear.gguf': 'ear-mmproj.gguf' }, projector_size_gb: { 'ear-mmproj.gguf': 0.9 } })
await show('sprache')
report.with = row()
report.cards = voice()

window.answers.spracheAuskunft = speech({ mmproj: ['ear-mmproj.gguf'], projektoren: {}, projector_size_gb: { 'ear-mmproj.gguf': 0.9 } })
await show('server')
await show('sprache')
report.without = row()

// A projector of another model, and sizes the answer does not carry: nothing is added.
window.answers.spracheAuskunft = speech({ mmproj: ['ear-mmproj.gguf'], projektoren: { 'ear.gguf': 'ear-mmproj.gguf' }, projector_size_gb: {} })
await show('server')
await show('sprache')
report.unknownSize = row()

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>server head</title>
<style>body { margin: 0; background: #1c1c1a; }</style>
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


async def _read_result(port: int, limit: float = 240.0) -> str:
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
            await asyncio.sleep(0.5)
    return ""


@pytest.fixture(scope="module", params=[1400])
def report(request) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / f".harness-serverhead-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
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
                f"--window-size={request.param},1000", f"--remote-debugging-port={port}",
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
        result["width"] = request.param
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@browser
def test_the_page_ran_without_a_script_error(report):
    assert report["errors"] == []


@browser
def test_the_row_counts_the_projector_of_the_chosen_model(report):
    # 4.2 GB file + the cache of 4096 tokens (0.1376 GB) = 4.3 GB; with the projector 5.2 GB.
    assert report["without"]["figures"] == "4,3 GB von 20,0 GB"
    assert report["with"]["figures"] == "5,2 GB von 20,0 GB"


@browser
def test_the_fill_grows_by_exactly_the_size_of_the_projector(report):
    grown = report["with"]["fill"] - report["without"]["fill"]
    assert abs(grown - 0.9 / 20 * 100) < 0.01, grown


@browser
def test_silence_a_projector_without_a_size_adds_nothing(report):
    assert report["unknownSize"] == report["without"]


@browser
def test_silence_the_card_of_the_voice_still_has_no_row(report):
    assert report["cards"] == 1


def test_the_answer_of_the_service_carries_the_projector_sizes(client: TestClient):
    folder = Path(client.get("/api/v1/sprachserver").json()["ordner"])
    (folder / "vision").mkdir(parents=True, exist_ok=True)
    (folder / "listener.gguf").write_bytes(b"x" * 10)
    with (folder / "vision" / "listener-mmproj-F16.gguf").open("wb") as projector:
        projector.truncate(900_000_000)
    answer = client.get("/api/v1/sprachserver").json()
    assert answer["projector_size_gb"] == {"listener-mmproj-F16.gguf": 0.9}
    # The pairing and the name list stay as they were.
    assert answer["projektoren"]["listener.gguf"] == "listener-mmproj-F16.gguf"
    assert answer["mmproj"] == ["listener-mmproj-F16.gguf"]


def test_silence_without_projectors_the_sizes_are_empty(client: TestClient):
    assert client.get("/api/v1/sprachserver").json()["projector_size_gb"] == {}
