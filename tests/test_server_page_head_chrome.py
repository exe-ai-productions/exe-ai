"""The head of a server page in a real browser: one name, no state pill, the
one start button (86 × 34, flush right, a dot in front of its word), the short
line beside the name, and the port of the server the page shows.

The real page (`ModelleLokal.svelte`) is built as it ships, with only the
service's answers replaced (`lib/api.js` by a stand-in) and the real German
texts put in. Run at two widths. Skipped where there is no Chrome or no node,
like the other browser tests.
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
const report = { errors: [], pages: {} }
window.addEventListener('error', (event) => report.errors.push((window.shown || 'start') + ': ' + String(event.message)))
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
const machine = { speicher_gb: 32, kerne: 8, vorgaben: { kontext: 16384, schichten: null, port: 8080, vorladen: false }, zuordnung: {}, mtp: [], modelle: [file('chat.gguf')], projector_size_gb: 0 }
window.answers = {
  runnerAuskunft: { ...machine, laeuft: true, port: 8080, modell: 'chat.gguf', kontext: 16384, schichten: null, belegt_gb: 5.5, drafter: '', vision: '', programm: true },
  einbettungAuskunft: { ...machine, laeuft: true, port: 8091, modell: 'embed.gguf', belegt_gb: 1, modelle: [file('embed.gguf')], programm: true },
  agentenmodellAuskunft: { ...machine, laeuft: false, port: null, programm: true },
  spracheAuskunft: { ...machine, laeuft: false, port: null, modelle: [], programm: true },
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
  window.shown = name
  window.zustand.lokalWunsch = name
  const title = { server: 'Modell-Server', agent: 'Agenten-Server', einbettung: 'Einbettungs-Server',
    sprache: 'Sprach-Server', bereinigung: 'Bereinigungs-Server', bild: 'Bild-Server', lokal: 'Lokale Modelle', overview: 'Server' }[name]
  await until(() => document.querySelector('header.kopf .titel')?.textContent.trim() === title, name + ' page')
  // The page hands its head up in its first effect; the data it draws comes with the first answers.
  await wait(900)
}

const head = () => {
  const kopf = document.querySelector('header.kopf')
  const kopfBox = kopf.getBoundingClientRect()
  const innerRight = kopfBox.right - parseFloat(getComputedStyle(kopf).paddingRight)
  const names = [...document.querySelectorAll('.titel')].map((e) => e.textContent.trim())
  const title = kopf.querySelector('.titel')
  const buttons = [...document.querySelectorAll('.startknopf')]
  const button = kopf.querySelector('.startknopf')
  const box = button ? button.getBoundingClientRect() : null
  const dot = button ? button.querySelector('svg.lp')?.getAttribute('data-farbe') : null
  const line = kopf.querySelector('.kurzzeile')
  const titleBox = title ? title.getBoundingClientRect() : null
  return {
    names,
    pills: [...document.querySelectorAll('.pille')].map((e) => e.textContent.trim()),
    buttonsOnPage: buttons.length,
    buttonsInHead: kopf.querySelectorAll('.startknopf').length,
    button: button ? {
      width: box.width, height: box.height, rightGap: innerRight - box.right,
      word: button.textContent.trim(), dot, disabled: button.disabled,
      whole: box.left >= 0 && box.right <= window.innerWidth,
    } : null,
    line: line ? line.textContent.trim() : null,
    nameWhole: title ? title.scrollWidth <= title.clientWidth + 1 && titleBox.right <= (box ? box.left : innerRight) + 1 : null,
    facts: (kopf.querySelector('.fakten')?.textContent ?? '').replace(/\s+/g, ' ').trim(),
    wrapped: box && titleBox ? box.top > titleBox.bottom : null,
  }
}

await wait(800)
for (const name of ['server', 'agent', 'einbettung', 'sprache', 'bereinigung', 'bild']) {
  await show(name)
  report.pages[name] = head()
}

// The model server switched off: its line says so, its button says "Start" with the quiet dot.
window.answers.runnerAuskunft = { ...window.answers.runnerAuskunft, laeuft: false, port: null, kontext: null, belegt_gb: null }
await show('server')
await until(() => head().button.word === 'Start', 'the stopped model server')
report.server_stopped = head()

// The picture server up: "Stop", the green dot and its own port.
window.answers.turboStand = { zustand: 'bereit', port: 8097, programm_da: true, picture_running: false }
await show('bild')
await until(() => head().button.word === 'Stopp', 'the running picture server')
report.bild_running = head()

// The button is the page's own: every server running, the button of each page stops that server and no other.
window.answers.runnerAuskunft = { ...window.answers.runnerAuskunft, laeuft: true, port: 8080, kontext: 16384, belegt_gb: 5.5 }
window.answers.agentenmodellAuskunft = { ...machine, laeuft: true, port: 8083, modell: 'agent.gguf', kontext: 8192, modelle: [file('agent.gguf')], programm: true, belegt_gb: 2 }
window.answers.spracheAuskunft = { ...machine, laeuft: true, port: 8284, modell: 'ear.gguf', modelle: [file('ear.gguf')], programm: true }
window.answers.bereinigungAuskunft = { ...machine, laeuft: true, port: 8285, modell: 'tidy.gguf', modelle: [file('tidy.gguf')], programm: true }
report.pressed = {}
for (const [name, call] of [['server', 'runnerStoppen'], ['agent', 'agentenmodellStoppen'], ['einbettung', 'einbettungStoppen'],
                            ['sprache', 'spracheStoppen'], ['bereinigung', 'bereinigungStoppen'], ['bild', 'turboStoppen']]) {
  await show(name)
  await until(() => document.querySelector('header.kopf .startknopf')?.textContent.trim() === 'Stopp' && !document.querySelector('header.kopf .startknopf').disabled, name + ' button')
  window.calls = []
  document.querySelector('header.kopf .startknopf').click()
  await until(() => window.calls.includes(call), call)
  report.pressed[name] = window.calls.filter((entry) => /Starten|Stoppen/.test(entry))
}

// The overview: the same button in every row of its table.
await show('overview')
report.overview = [...document.querySelectorAll('.startknopf')].map((button) => {
  const box = button.getBoundingClientRect()
  return {
    width: box.width, height: box.height, word: button.textContent.trim(),
    dot: button.querySelector('svg.lp')?.getAttribute('data-farbe'),
  }
})

// Local models: no button in the head.
await show('lokal')
report.local = head()

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


@pytest.fixture(scope="module", params=[1400, 1100])
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


NAMES = {
    "server": "Modell-Server",
    "agent": "Agenten-Server",
    "einbettung": "Einbettungs-Server",
    "sprache": "Sprach-Server",
    "bereinigung": "Bereinigungs-Server",
    "bild": "Bild-Server",
}


def test_the_page_ran_without_a_script_error(report):
    assert report["errors"] == []


@pytest.mark.parametrize("page", list(NAMES))
def test_a_server_page_has_one_name_and_no_pill(report, page):
    head = report["pages"][page]
    assert head["names"] == [NAMES[page]]
    assert head["pills"] == []


@pytest.mark.parametrize("page", list(NAMES))
def test_a_server_page_has_one_start_button_flush_right_in_its_head(report, page):
    head = report["pages"][page]
    assert head["buttonsOnPage"] == 1 and head["buttonsInHead"] == 1
    button = head["button"]
    assert abs(button["width"] - 86) <= 0.5 and abs(button["height"] - 34) <= 0.5
    assert abs(button["rightGap"]) <= 1, button
    assert button["whole"] and head["nameWhole"], head
    assert not head["wrapped"], head


def test_the_dot_follows_the_state_of_the_server_shown(report):
    pages = report["pages"]
    assert (pages["server"]["button"]["word"], pages["server"]["button"]["dot"]) == ("Stopp", "gruen")
    assert (pages["einbettung"]["button"]["word"], pages["einbettung"]["button"]["dot"]) == ("Stopp", "gruen")
    for stopped in ("agent", "sprache", "bereinigung", "bild"):
        assert (pages[stopped]["button"]["word"], pages[stopped]["button"]["dot"]) == ("Start", "still"), stopped
    assert (report["server_stopped"]["button"]["word"], report["server_stopped"]["button"]["dot"]) == ("Start", "still")
    assert (report["bild_running"]["button"]["word"], report["bild_running"]["button"]["dot"]) == ("Stopp", "gruen")


def test_the_port_is_the_one_of_the_server_shown(report):
    pages = report["pages"]
    assert "Port: 8080" in pages["server"]["facts"]
    assert "Port: 8091" in pages["einbettung"]["facts"]
    # The model server runs on 8080, the agent server stands: its page says so.
    assert pages["agent"]["facts"].endswith("Port: -")
    assert pages["bild"]["facts"].endswith("Port: -")
    assert "Port: 8097" in report["bild_running"]["facts"]
    assert "Port: -" in report["server_stopped"]["facts"]


def test_the_short_line_stands_beside_the_name_without_the_port(report):
    pages = report["pages"]
    assert pages["server"]["line"] and "Kontext 16k" in pages["server"]["line"]
    assert "Port" not in pages["server"]["line"] and "Läuft" not in pages["server"]["line"]
    assert report["server_stopped"]["line"] == "Kein Modell geladen"
    for quiet in ("einbettung", "sprache", "bereinigung", "bild"):
        assert pages[quiet]["line"] is None, quiet


def test_local_models_shows_no_button_in_its_head(report):
    assert report["local"]["buttonsInHead"] == 0
    assert report["local"]["names"] == ["Lokale Modelle"]


def test_the_overview_carries_the_same_button_in_every_row(report):
    rows = report["overview"]
    assert len(rows) == 6
    for row in rows:
        assert abs(row["width"] - 86) <= 0.5 and abs(row["height"] - 34) <= 0.5, row
        assert row["dot"] in ("gruen", "still"), row


def test_the_button_in_the_head_is_the_deed_of_the_page_shown(report):
    assert report["pressed"] == {
        "server": ["runnerStoppen"],
        "agent": ["agentenmodellStoppen"],
        "einbettung": ["einbettungStoppen"],
        "sprache": ["spracheStoppen"],
        "bereinigung": ["bereinigungStoppen"],
        "bild": ["turboStoppen"],
    }


def test_the_head_carries_the_port_and_no_second_memory_figure(report):
    heads = [*report["pages"].values(), report["server_stopped"], report["bild_running"], report["local"]]
    assert len(heads) == 9
    for head in heads:
        assert re.fullmatch(r"Port: (\d+|-)", head["facts"]), head["facts"]
