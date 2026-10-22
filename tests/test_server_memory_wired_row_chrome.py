"""The row "Wired Memory" in the card "Speicher" of the server pages, in a real
browser: it shows the plan of the server's own model — its file and the
context that is set — as a bar and "x GB von y GB", measured against the
limit the system applies to wired memory (not against the whole machine),
before the server runs.

The real pages (`ModelleLokal.svelte` and the server pages under it) are
built as they ship, with only the service's answers replaced (`lib/api.js`
by a stand-in) and the real German texts put in. Skipped where there is no
Chrome or no node, like the other browser tests.
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
const machine = { speicher_gb: 32, kerne: 8, vorgaben: { kontext: 16384, schichten: null, port: 8080, vorladen: false }, zuordnung: {}, mtp: [], modelle: [file('chat.gguf')], projector_size_gb: {} }
window.answers = {
  runnerAuskunft: { ...machine, laeuft: true, port: 8080, modell: 'chat.gguf', kontext: 16384, schichten: null, belegt_gb: 5.5, drafter: '', vision: '', programm: true },
  einbettungAuskunft: { ...machine, laeuft: false, port: null, modelle: [], programm: true },
  agentenmodellAuskunft: { ...machine, laeuft: false, port: null, programm: true },
  spracheAuskunft: { ...machine, vorgaben: { ...machine.vorgaben, kontext: 4096 }, laeuft: false, port: null, modell: 'ear.gguf', modelle: [file('ear.gguf')], projektoren: {}, mmproj: [], programm: true },
  bereinigungAuskunft: { ...machine, diktat_vorgaben: { putzkontext: 2048, putzschichten: null, putzfaeden: 0, putztemperatur: 0, putztop_k: 0, putztop_p: 1, putzmin_p: 0, putzstrafe: 1 }, laeuft: true, port: 8285, modell: 'tidy.gguf', modelle: [file('tidy.gguf')], programm: true },
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
    sprache: 'Sprach-Server', bereinigung: 'Bereinigungs-Server', bild: 'Bild-Server', lokal: 'Lokale Modelle' }[name]
  await until(() => document.querySelector('header.kopf .titel')?.textContent.trim() === title, name + ' page')
  await wait(900)
}

const colour = (value) => {
  const probe = document.createElement('span')
  probe.style.color = value
  document.body.appendChild(probe)
  const out = getComputedStyle(probe).color
  probe.remove()
  return out
}
report.colours = { line: colour('var(--linie-stark)'), green: colour('var(--gruen)'), quiet: colour('var(--text-leise)'), text: colour('var(--text)') }

// The cards "Speicher" of the page shown, each with the row it carries, or none.
const cards = () => [...document.querySelectorAll('.abschnitt')]
  .filter((card) => card.querySelector('.kopf .name')?.textContent.trim() === 'Speicher')
  .map((card) => {
    const row = card.querySelector('.zeile.wired')
    if (!row) return { row: false, rows: card.querySelectorAll('.karte > .zeile').length }
    const name = row.querySelector('.wiredname')
    const track = row.querySelector('.balken')
    const fill = track.querySelector('i')
    const figures = row.querySelector('.schaetz')
    const own = (node) => getComputedStyle(node)
    return {
      row: true,
      last: row === card.querySelector('.karte').lastElementChild,
      height: row.getBoundingClientRect().height,
      paddingX: [own(row).paddingLeft, own(row).paddingRight],
      gap: own(row).columnGap,
      name: name.textContent.trim(),
      nameType: [own(name).fontWeight, own(name).fontSize, own(name).color],
      trackBox: [track.getBoundingClientRect().height, own(track).borderTopLeftRadius, own(track).backgroundColor],
      fill: [own(fill).backgroundColor, fill.style.width],
      figures: figures.textContent.trim(),
      figuresType: [own(figures).fontWeight, own(figures).fontSize, own(figures).color],
      oldRow: row.classList.contains('duenn'),
    }
  })

await wait(800)
for (const name of ['server', 'agent', 'bereinigung', 'sprache']) {
  await show(name)
  report.pages[name] = cards()
}

// The head's bar still measures the whole machine's wired memory.
await show('server')
report.head = document.querySelector('header.kopf, .kopf')?.textContent.replace(/\s+/g, ' ').trim()
report.headBar = (document.querySelector('.bar')?.textContent ?? '').replace(/\s+/g, ' ').trim()

// The plan follows the context: the speech model's context set higher.
await show('sprache')
const before = cards()[0].figures
const field = document.querySelector('label[for="sp-kontext"]').closest('.regel').querySelector('.zahlplatz input')
field.focus()
Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(field, '32768')
field.dispatchEvent(new Event('input', { bubbles: true }))
field.dispatchEvent(new Event('change', { bubbles: true }))
field.blur()
await wait(600)
report.context = { before, after: cards()[0].figures }

// The limit the system names is what the plan is measured against; none named: its whole memory.
window.answers.speicherBlick = { wired_gb: 10, gesamt_gb: 32 }
await show('server')
await show('bereinigung')
report.noLimit = cards()[0]

// The system names nothing at all: the page that knows its machine measures against that,
// the page that does not has no limit and shows no row.
window.answers.speicherBlick = {}
await show('server')
report.machine = cards()[0]
await show('bereinigung')
report.machineSilent = cards()[0]

// Silence: no model in the folder, no row.
window.answers.spracheAuskunft = { ...window.answers.spracheAuskunft, modell: null, modelle: [] }
await show('server')
await show('sprache')
report.noModel = cards()

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


def test_the_page_ran_without_a_script_error(report):
    assert report["errors"] == []


def _plan(model_gb: float, context: int) -> str:
    kv = (context * 8 * model_gb) / 1e6
    return f"{model_gb + kv:.1f}".replace(".", ",")


@pytest.mark.parametrize(
    ("page", "context"), [("server", 16384), ("bereinigung", 2048), ("sprache", 4096)]
)
def test_the_card_of_the_servers_own_model_carries_the_wired_memory_row(report, page, context):
    card = report["pages"][page][0]
    assert card["row"] is True
    assert card["name"] == "Wired Memory"
    assert card["figures"] == f"{_plan(4.2, context)} GB von 20,0 GB"
    # The last row of the card, an ordinary row and no longer the thin one.
    assert card["last"] is True and card["oldRow"] is False
    # An ordinary row is 56 high; where the page stretches the card to the one beside it, the rows
    # share the extra height and stand a little taller.
    assert (card["height"] == 56) if page == "sprache" else (card["height"] >= 56)


def test_the_row_is_drawn_as_the_drawing_has_it(report, request):
    colours = report["colours"]
    card = report["pages"]["server"][0]
    assert card["paddingX"] == ["16px", "16px"] and card["gap"] == "14px"
    assert card["nameType"] == ["600", "13px", colours["text"]]
    assert card["trackBox"] == [6, "3px", colours["line"]]
    assert card["fill"][0] == colours["green"]
    assert card["figuresType"] == ["400", "13px", colours["quiet"]]
    # The fill is the plan against the limit: 4,75 of 20 GB.
    assert 0 < float(card["fill"][1].rstrip("%")) < 100
    assert abs(float(card["fill"][1].rstrip("%")) - (4.2 + 16384 * 8 * 4.2 / 1e6) / 20 * 100) < 0.5


def test_the_agent_server_without_a_slot_has_no_row_of_its_own_model(report):
    assert [card["row"] for card in report["pages"]["agent"]] == [False]


def test_the_card_of_the_voice_has_no_row(report):
    sprache = report["pages"]["sprache"]
    assert [card["row"] for card in sprache] == [True, False]


def test_the_plan_grows_with_the_context(report):
    before, after = report["context"]["before"], report["context"]["after"]
    assert before == f"{_plan(4.2, 4096)} GB von 20,0 GB"
    assert after == f"{_plan(4.2, 32768)} GB von 20,0 GB"


def test_without_a_limit_of_its_own_the_plan_is_measured_against_the_whole_memory(report):
    assert report["noLimit"]["figures"].endswith("GB von 32,0 GB")
    # And where the system says nothing at all, against what the page knows of the machine.
    assert report["machine"]["figures"].endswith("GB von 32,0 GB")


def test_silence_a_page_without_any_limit_shows_no_row(report):
    assert report["machineSilent"]["row"] is False


def test_silence_without_a_model_there_is_no_row(report):
    assert [card["row"] for card in report["noModel"]] == [False, False]


def test_silence_the_bar_in_the_head_still_measures_the_whole_mac(report):
    assert "Wired Memory" in report["headBar"] and "10,0 GB von 20,0 GB" in report["headBar"]
