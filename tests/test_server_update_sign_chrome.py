"""The version rows of the server pages and the model card of the picture
server, in a real browser.

``App.svelte`` is built as shipped and drawn in headless Chrome with the
global stylesheet; the service is not asked, the page answers every request
itself and lists the calls it got.

* The version row of llama.cpp (chat and agent server) and of sd.cpp (picture
  server) reads "Version" on the left and the build number as a mark at the
  end, with the sign "Update" before the mark. No word button stands there.
* The first press on the sign only asks: nothing is fetched. A newer build
  turns the sign yellow; the second press fetches it, once. No newer build:
  "Up to date" with the tick. A list that could not be read: the red message.
* Where nothing is checked (a program the settings name) there is no sign; the
  button that fetches a missing program stays.
* The picture server's model card holds the picker with the default model and
  the door to the catalogue (on the picture tab); the row "Standardmodell"
  and the word button "Nach Updates suchen" are gone; the mark beside the
  head shows the sentence.

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

ENTRY_JS = """import { mount } from 'svelte'
import App from '../../src/App.svelte'
import '../../src/stil/global.css'
import german from '@@GERMAN@@'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand, seiteZeigen } from '../../src/lib/zustand.svelte.js'

texte.katalog = german
texte.sprache = 'de'
const files = ['a.safetensors', 'b.safetensors']
const scenario = {
  updatable: true, hasProgram: true, check: 'aktuell', files, defaultModel: 'a.safetensors',
  stateFor: { fertig: true, fehler: false, anteil: 1 },
}
const calls = []
window.__scenario = scenario
window.__calls = calls
const server = (port) => ({
  programm: scenario.hasProgram ? '/bin/llama-server' : null,
  version: scenario.hasProgram ? 'b11429' : null,
  updatable: scenario.updatable, restorable: false,
  ordner: '/m', modelle: [{ name: 'a.gguf', groesse_gb: 2 }], mmproj: [], projector_size_gb: {}, mtp: [],
  speicher_gb: 32, kerne: 8, belegt_gb: null, laeuft: false, modell: null, kontext: null, schichten: null, port,
  drafter: null, vision: null, fein: null, flash_aktiv: null, mtp_aktiv: null, unknown_architecture: null,
  zuordnung: {}, vorgaben: { kontext: 16384, schichten: 99, port: null, vorladen: true }, vorgabe: 'a.gguf',
})
const picture = () => ({
  programm_da: true, restorable: false, bau: 'master-4ff2c8a', modelle: scenario.files,
  standardmodell: scenario.defaultModel, families: {}, ab_werk: {}, anweisungen: {},
})
const checkAnswer = () => (
  scenario.check === 'neuer' ? { verfuegbar: true, aktuell: false }
    : scenario.check === 'unlesbar' ? { verfuegbar: false, aktuell: false, unreadable: true }
      : { verfuegbar: false, aktuell: true }
)
window.fetch = async (address, options = {}) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const method = options.method || 'GET'
  const sent = options.body ? String(options.body) : null
  if (path !== '/runner' && path !== '/agentenmodell' && path !== '/bild/turbo' && !path.endsWith('/log')) {
    calls.push({ method, path, sent })
  }
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  if (path === '/runner') return json(server(8080))
  if (path === '/agentenmodell') return json(server(8083))
  if (path === '/runner/programm' && method === 'GET') return json(scenario.stateFor)
  if (path === '/runner/programm' && method === 'POST') return json({ fertig: false, fehler: false, anteil: 0.4 })
  if (path === '/runner/programm/aktualisierung') return json(checkAnswer())
  if (path === '/runner/programm/varianten') return json({})
  if (path === '/bild/modelle') return json(picture())
  if (path === '/bild/programm' && method === 'POST') return json({ fertig: false, fehler: false, anteil: 0.4 })
  if (path === '/bild/programm') return json({ fertig: true, fehler: false, anteil: 1 })
  if (path === '/bild/programm/aktualisierung') return json(checkAnswer())
  if (path === '/bild/programm/varianten') return json({})
  if (path === '/bild/model-files') return json([])
  if (path === '/bild/turbo') return json({ zustand: 'aus', programm_da: true })
  if (path === '/system/speicher') return json({ wired_limit_gb: 20, gesamt_gb: 32 })
  if (path === '/models' || path === '/speicherorte' || path === '/chats' || path.endsWith('/log')) return json([])
  if (path.startsWith('/settings/') && method === 'PUT') {
    scenario.defaultModel = JSON.parse(sent || '{}').wert ?? scenario.defaultModel
    return json({ wert: scenario.defaultModel })
  }
  return json({})
}
window.__zustand = zustand
window.__open = (name) => {
  zustand.lokalWunsch = name
  seiteZeigen('lokal')
}
mount(App, { target: document.getElementById('wurzel') })
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
const report = (window.__report = {})
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const scenario = window.__scenario
const calls = window.__calls
const until = async (test, ms = 8000) => { for (let k = 0; k < ms / 100 && !test(); k += 1) await wait(100) }
const cardOf = (head) => [...document.querySelectorAll('section.abschnitt')].find((s) => {
  const h = s.querySelector(':scope > .kopf')
  return h && text(h).startsWith(head)
})
const open = async (name, head) => {
  window.__open(name)
  await until(() => cardOf(head))
  await wait(900)
}
const versionRow = (card) => [...card.querySelectorAll('.karte > .zeile')].find((r) => r.querySelector(':scope > .name')?.textContent.trim() === 'Version')
const rowFacts = (card) => {
  const row = versionRow(card)
  if (!row) return null
  const sign = row.querySelector('.updatezeichen')
  const mark = row.querySelector('.versionsmarke')
  const kids = [...row.children]
  return {
    name: text(row.querySelector(':scope > .name')),
    mark: mark ? text(mark) : null,
    hasSign: Boolean(sign),
    signTitle: sign?.getAttribute('title') ?? null,
    signLabel: sign?.getAttribute('aria-label') ?? null,
    signText: sign ? text(sign) : null,
    signBeforeMark: sign && mark ? kids.indexOf(sign) < kids.indexOf(mark) : null,
    markLast: mark ? kids.indexOf(mark) === kids.length - 1 : null,
    yellow: sign?.classList.contains('gefunden') ?? null,
    disabled: sign?.disabled ?? null,
    upToDate: Boolean(row.querySelector('.uptodate')),
    wordButtons: [...row.querySelectorAll('button')].filter((b) => text(b) !== '').map((b) => text(b)),
    wraps: getComputedStyle(row).flexWrap,
    rowHeight: Math.round(row.getBoundingClientRect().height),
  }
}
const press = async (card) => { versionRow(card).querySelector('.updatezeichen').click(); await wait(900) }
const callsOf = (path, method) => calls.filter((c) => c.path === path && (!method || c.method === method))

// --- llama.cpp on the model server -----------------------------------------
await open('server', 'Modelle')
let llama = cardOf('llama.cpp')
report.llama = { initial: rowFacts(llama) }
scenario.check = 'aktuell'
calls.length = 0
await press(llama)
report.llama.upToDate = { ...rowFacts(llama), checks: callsOf('/runner/programm/aktualisierung').length, posts: callsOf('/runner/programm', 'POST').length }
scenario.check = 'unlesbar'
await press(llama)
report.llama.unreadable = { ...rowFacts(llama), message: document.body.innerText.includes('Updates ließen') }
scenario.check = 'neuer'
calls.length = 0
await press(llama)
report.llama.found = { ...rowFacts(llama), checks: callsOf('/runner/programm/aktualisierung').length, posts: callsOf('/runner/programm', 'POST').length }
await press(llama)
report.llama.second = {
  ...rowFacts(llama),
  posts: callsOf('/runner/programm', 'POST').map((c) => c.sent),
  checks: callsOf('/runner/programm/aktualisierung').length,
}

// --- the same row on the agent server --------------------------------------
await open('agent', 'Modell')
report.agent = rowFacts(cardOf('llama.cpp'))

// --- a program the settings name: nothing is checked -----------------------
scenario.updatable = false
await open('server', 'Modelle')
await wait(3500)
report.named = rowFacts(cardOf('llama.cpp'))
scenario.updatable = true

// --- no program: the button that fetches it stays --------------------------
scenario.hasProgram = false
await open('agent', 'Modell')
await wait(3500)
const missing = cardOf('llama.cpp')
report.missing = {
  hasSign: Boolean(missing.querySelector('.updatezeichen')),
  buttons: [...missing.querySelectorAll('.karte > .zeile button')].map((b) => text(b)).filter(Boolean),
  mark: missing.querySelector('.versionsmarke') ? text(missing.querySelector('.versionsmarke')) : null,
}
scenario.hasProgram = true

// --- sd.cpp on the picture server -------------------------------------------
scenario.check = 'aktuell'
await open('bild', 'Bildmodell')
await until(() => cardOf('sd.cpp') && versionRow(cardOf('sd.cpp')))
let sd = cardOf('sd.cpp')
report.sd = { initial: rowFacts(sd) }
calls.length = 0
await press(sd)
report.sd.upToDate = { ...rowFacts(sd), posts: callsOf('/bild/programm', 'POST').length }
scenario.check = 'neuer'
await press(sd)
report.sd.found = { ...rowFacts(sd), posts: callsOf('/bild/programm', 'POST').length }
await press(sd)
report.sd.second = { ...rowFacts(sd), posts: callsOf('/bild/programm', 'POST').map((c) => c.sent) }

// --- the model card of the picture server -------------------------------------
await open('agent', 'Modell')
await open('bild', 'Bildmodell')
const model = cardOf('Bildmodell')
const head = model.querySelector(':scope > .kopf')
const pickerRow = model.querySelector('.karte > .zeile.auswahlzeile')
const door = pickerRow?.querySelector('.katalogtuer')
const infoMark = head.querySelector('.mark')
report.model = {
  pickerRow: Boolean(pickerRow),
  picker: pickerRow ? text(pickerRow.querySelector('button[role="combobox"]')) : null,
  door: door ? { title: door.getAttribute('title'), label: door.getAttribute('aria-label') } : null,
  arrow: Boolean(pickerRow?.querySelector('.weiter')),
  rows: [...model.querySelectorAll('.karte > .zeile')].map((r) => text(r)),
  wordButtons: [...document.querySelectorAll('button')].map((b) => text(b)).filter((x) => x === 'Nach Updates suchen'),
  hasInfo: Boolean(infoMark),
  headText: text(head),
  headBefore: Math.round(head.getBoundingClientRect().height),
}
infoMark?.click()
await wait(300)
report.model.sentence = head.querySelector('.bubble') ? text(head.querySelector('.bubble')) : null
report.model.headOpen = Math.round(head.getBoundingClientRect().height)
infoMark?.click()
await wait(200)
// A different default model goes out as before.
calls.length = 0
pickerRow.querySelector('button[role="combobox"]').click()
await wait(400)
;[...document.querySelectorAll('[role="option"]')].find((o) => text(o) === 'b.safetensors')?.click()
await wait(900)
report.model.written = calls.filter((c) => c.method === 'PUT').map((c) => ({ path: c.path, sent: c.sent }))
// The door opens the catalogue on the picture tab.
door.click()
report.model.door.kind = window.__zustand.katalogArtWunsch
await wait(700)
report.model.door.opened = window.__zustand.katalogOffen === true
// An empty folder: the picker stands locked with the sentence.
window.__zustand.katalogOffen = false
scenario.files = []
scenario.defaultModel = ''
await open('server', 'Modelle')
await open('bild', 'Bildmodell')
const empty = cardOf('Bildmodell').querySelector('.karte > .zeile.auswahlzeile button[role="combobox"]')
report.empty = { disabled: empty?.disabled ?? null, text: empty ? text(empty) : null }
document.title = 'done'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { position: relative; width: 1920px; height: 1080px; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      @@CASES@@
    } catch (failure) {
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure), partial: window.__report })
    }
  })
</script>
</body></html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 240.0) -> dict:
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
        raw = ""
        while time.monotonic() < end and not raw:
            number += 1
            await connection.send(json.dumps({
                "id": number, "method": "Runtime.evaluate",
                "params": {"expression": "document.getElementById('ergebnis')?.textContent || ''", "returnByValue": True},
            }))
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    break
            raw = response.get("result", {}).get("result", {}).get("value", "")
            if not raw:
                await asyncio.sleep(0.5)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, (report["failure"], report.get("partial"))
        return report


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-update-sign-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "entry.js").write_text(
            ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json")), encoding="utf-8"
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", CASES), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1920,1080", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return asyncio.run(_drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


PROGRAM_ROWS = [("llama", "b11429"), ("sd", "master-4ff2c8a")]


@pytest.mark.parametrize(("page", "build"), PROGRAM_ROWS)
def test_the_version_row_reads_version_with_the_build_as_a_mark_and_the_sign_before_it(report, page, build):
    row = report[page]["initial"]
    assert row["name"] == "Version"
    assert row["mark"] == build
    assert row["hasSign"] and row["signBeforeMark"] and row["markLast"]
    assert row["signTitle"] == row["signLabel"] == "Aktualisieren"
    assert row["signText"] == ""
    assert row["wordButtons"] == []
    assert row["wraps"] == "nowrap"


def test_the_agent_server_carries_the_same_row(report):
    assert report["agent"] == report["llama"]["initial"]


@pytest.mark.parametrize("page", ["llama", "sd"])
def test_the_first_press_only_asks_and_the_second_press_fetches_once(report, page):
    data = report[page]
    assert data["upToDate"]["upToDate"] is True and data["upToDate"]["yellow"] is False
    assert data["upToDate"]["posts"] == 0
    assert data["found"]["yellow"] is True and data["found"]["posts"] == 0
    assert len(data["second"]["posts"]) == 1
    assert '"aktualisieren":true' in data["second"]["posts"][0]
    assert data["second"]["disabled"] is True


def test_the_llama_check_asked_once_per_press_and_never_again_while_it_fetched(report):
    assert report["llama"]["upToDate"]["checks"] == 1
    assert report["llama"]["found"]["checks"] == 1
    assert report["llama"]["second"]["checks"] == 1


def test_a_list_that_could_not_be_read_shows_the_red_message_and_keeps_the_sign_quiet(report):
    data = report["llama"]["unreadable"]
    assert data["message"] is True
    assert data["yellow"] is False and data["upToDate"] is False


def test_silence_a_program_the_settings_name_has_no_sign_but_keeps_its_mark(report):
    data = report["named"]
    assert data["hasSign"] is False
    assert data["mark"] == "b11429" and data["markLast"] is True


def test_silence_without_a_program_the_fetch_button_stays_and_the_mark_is_a_dash(report):
    assert report["missing"] == {"hasSign": False, "buttons": ["Download"], "mark": "-"}


def test_the_model_card_holds_the_picker_the_arrow_and_the_door_to_the_catalogue(report):
    model = report["model"]
    assert model["pickerRow"] is True
    assert model["picker"] == "a.safetensors"
    assert model["arrow"] is True
    assert model["door"]["title"] == model["door"]["label"] == "Zum Katalog"
    assert model["door"]["kind"] == "bild" and model["door"]["opened"] is True


def test_the_model_card_has_no_default_model_row_and_no_update_word_button(report):
    model = report["model"]
    assert model["wordButtons"] == []
    assert not any("Standardmodell" in row for row in model["rows"])


def test_the_mark_beside_the_head_shows_the_sentence_and_the_head_grows_with_it(report):
    model = report["model"]
    assert model["hasInfo"] is True and model["headText"] == "Bildmodell"
    assert model["sentence"].startswith("Wird von Chats ohne eigenes Bildmodell")
    assert model["headOpen"] > model["headBefore"]


def test_another_pick_goes_out_as_before(report):
    assert report["model"]["written"] == [
        {"path": "/settings/global/bild_standardmodell", "sent": '{"wert":"b.safetensors"}'}
    ]


def test_silence_an_empty_folder_locks_the_picker_and_says_what_to_do(report):
    assert report["empty"]["disabled"] is True
    assert report["empty"]["text"].startswith("Bitte ein Bildmodell im Ordner ablegen")
