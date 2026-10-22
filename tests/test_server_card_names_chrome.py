"""The names on the left of a server card stand semi-bold, in a real browser.

In every card of the server pages the first text of a row is the name of the
setting: "Context", "GPU layers", "CPU threads", "Port", the sampling knobs.
It stands in 13 px, weight 600, in the colour of `--text`; the values beside
it (a number in its field, a path, the size of a build) stay regular. A row
that carries only a message — its name is its one child, like "Loading the
generator variants…" or an error — is no name to read a row by and stays 400.

The real `Serverregler.svelte` (memory and network of the model server),
`Sprachserver.svelte`, `BildGeraete.svelte`, `Parametertafel.svelte`,
`BuildRows.svelte`, `LlamaCppSection.svelte` (twice: its version line stands
beside the mark of its build, and a failed fetch is drawn) and `Ankreuzliste.svelte` (a
catalogue row, whose own rule keeps its weight when the name stands alone) are
built as they ship, with only the service's answers replaced (`lib/api.js` by
a stand-in) and the real German texts put in. The rows that carry only a
message, a slider name or a count name are made up in the page. Skipped where
there is no Chrome or no node, like the other browser tests.
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
  import Serverregler from '../../src/teile/Serverregler.svelte'
  import Sprachserver from '../../src/teile/Sprachserver.svelte'
  import BildGeraete from '../../src/teile/BildGeraete.svelte'
  import Parametertafel from '../../src/teile/Parametertafel.svelte'
  import BuildRows from '../../src/teile/BuildRows.svelte'
  import Serverabschnitt from '../../src/teile/Serverabschnitt.svelte'
  import LlamaCppSection from '../../src/teile/LlamaCppSection.svelte'
  import Ankreuzliste from '../../src/teile/Ankreuzliste.svelte'
</script>

<div style="width: 1000px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px;">
  <div id="model"><Serverregler kennung="rs" teil="alles" kontext={16384} schaetzung={{ gesamt: 7.46 }} maschineGb={60.8} /></div>
  <div id="speech"><Sprachserver /></div>
  <div id="image"><BildGeraete /></div>
  <div id="params"><Parametertafel modell={window.__model} /></div>
  <div id="builds">
    <Serverabschnitt titel="Builds">
      <BuildRows builds={window.__builds} installed="cuda12" />
    </Serverabschnitt>
  </div>
  <div id="llama-a"><LlamaCppSection auskunft={{ programm: null, version: null, updatable: false, restorable: false }} /></div>
  <div id="llama-b"><LlamaCppSection auskunft={{ programm: '/bin/llama-server', version: 'b1', updatable: false, restorable: false }} /></div>
  <div id="ticks">
    <Serverabschnitt titel="Catalogue">
      <Ankreuzliste tickEnd eintraege={[{ id: 'a', name: 'First model' }, { id: 'b', name: 'Second model' }]}
                    istAn={(e) => e.id === 'b'} onschalten={() => {}} onalle={() => {}} />
    </Serverabschnitt>
  </div>
  <div id="message">
    <Serverabschnitt titel="State">
      <div class="zeile"><span class="name">Loading the generator variants…</span></div>
      <div class="zeile"><span class="name v_fehler">A failed fetch</span></div>
      <div class="zeile"><span class="regelname">A slider message</span></div>
      <div class="zeile"><span class="zahlname">A count message</span></div>
      <div class="zeile"><span class="name">A setting</span><span class="v_still" id="value">8084</span></div>
    </Serverabschnitt>
  </div>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { texte } from '../../src/lib/texte.svelte.js'
import katalog from '../../../app/locales/de.json'
import %(global)r

texte.katalog = katalog
texte.sprache = 'de'
window.__model = {
  id: 'm1', name: 'Model',
  parameter: [
    { name: 'temperature', label: 'Temperature', minimum: 0, maximum: 2, schritt: 0.1 },
    { name: 'top_k', label: 'Top-K', minimum: 0, maximum: 200, schritt: 1, ganzzahl: true },
  ],
}
window.__builds = [
  { variante: 'cpu', groesse: 60 * 1024 * 1024 },
  { variante: 'cuda12', groesse: 90 * 1024 * 1024 },
  { variante: 'vulkan', groesse: 70 * 1024 * 1024 },
]
mount(Shell, { target: document.getElementById('root') })
"""

API_STUB = r"""const copy = (value) => JSON.parse(JSON.stringify(value))
const works = {
  sprache: 'auto', anweisung: 'x', bereinigung: 'aus', putzmodell: '', bereinigung_anweisung: 'y',
  vorlesen: true, keep_model_in_memory: true, conversation_pause_seconds: 3, stimme: '', stimmprobe: '',
  stimmsprache: '', stimmtemperatur: 0.9, stimmtop_k: 50, stimmtop_p: 1, stimmmin_p: 0, stimmstrafe: 1.05,
  stimmschichten: 99, stimmfaeden: 0, gespraechsanweisung: 'z', automatik: false, microphone_key: 'Meta+Alt',
}
const state = () => ({
  programm: '/bin/llama-server', version: 'b1', updatable: false, restorable: false,
  ordner: '/m', modelle: [{ name: 'voice.gguf', groesse_gb: 1 }], mmproj: [],
  projektoren: {}, laeuft: false, modell: null, port: 8084,
  kontext: null, schichten: null, threads: null, kerne: 8, unknown_architecture: null,
  vorgaben: { kontext: 4096, schichten: 99, threads: 0 }, diktat_vorgaben: copy(works),
  stimmproben: [], stimmproben_dauer: {},
})
const methods = {
  serverProgrammStand: async () => ({ fehler: 'failed', fertig: false, anteil: 0 }),
  serverProgrammVarianten: async () => ({ varianten: [{ variante: 'cpu', groesse: 60 * 1024 * 1024 }], installiert: null, unavailable: [] }),
  spracheAuskunft: async () => state(),
  spracheProtokoll: async () => [],
  einstellungAufgeloest: async () => ({ wert: copy(works), herkunft: {} }),
  einstellungMischen: async () => ({ wert: copy(works) }),
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
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const ready = () => document.querySelector('#speech .parameterblock') && document.querySelector('#model .zahlname')
  && document.querySelector('#image .name') && document.querySelector('#llama-a .v_fehler')
  && document.querySelector('#llama-b .build') && document.querySelector('#ticks .name')
  && document.querySelector('#params .regelname')
for (let k = 0; k < 200 && !ready(); k += 1) await wait(50)
await wait(300)

const style = (node) => {
  const css = getComputedStyle(node)
  return { size: css.fontSize, weight: css.fontWeight, color: css.color, height: node.getBoundingClientRect().height }
}
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const root = document.documentElement
const probe = document.createElement('span')
probe.style.color = 'var(--text)'
document.body.appendChild(probe)
const inkColour = getComputedStyle(probe).color
probe.remove()

// The name of every row in every card: its text and its look.
const names = (scope) => Array.from(document.querySelectorAll(scope + ' .karte :is(.name, .regelname, .zahlname)'))
  .filter((node) => !node.closest('.kopf'))
  .map((node) => ({ text: text(node), only: node.matches(':only-child') && node.parentElement.classList.contains('zeile'), ...style(node) }))
const find = (list, label) => list.find((entry) => entry.text === label)
const model = names('#model')
const speech = names('#speech')
const image = names('#image')
const params = names('#params')
const message = names('#message')
const builds = names('#builds')
const llamaA = names('#llama-a')
const llamaB = names('#llama-b')
const ticks = names('#ticks')

// The values stand beside the names: the number fields, the pasted value, the
// size of a build and the number of a slider.
const values = Array.from(document.querySelectorAll(
  '#model input, #params .zahl, #message .v_still, #builds .groesse, #speech input',
)).map((node) => ({ cls: node.className.replace(/svelte-\w+/g, '').trim(), weight: getComputedStyle(node).fontWeight }))

// Every row of every card, measured once as it is and once with the names
// forced to regular: a heavier name must not make a row taller.
const heights = () => Array.from(document.querySelectorAll('.karte > .zeile')).map((row) => Math.round(row.getBoundingClientRect().height * 10) / 10)
// A name that does not fit its room ends in an ellipsis: which ones do.
const clipped = () => Array.from(document.querySelectorAll('.karte :is(.name, .regelname, .zahlname)'))
  .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => text(node))
const heightsBold = heights()
const clippedBold = clipped()
const forced = document.createElement('style')
forced.textContent = '.karte :is(.name, .regelname, .zahlname) { font-weight: 400 !important; }'
document.head.appendChild(forced)
await wait(100)
const heightsRegular = heights()
const clippedRegular = clipped()
forced.remove()

const redProbe = document.createElement('span')
redProbe.style.color = 'var(--rot)'
document.body.appendChild(redProbe)
const redColour = getComputedStyle(redProbe).color
redProbe.remove()

report = {
  ink: inkColour,
  red: redColour,
  model, speech, image, params, message, builds, llamaA, llamaB, ticks,
  values,
  heightsBold, heightsRegular, clippedBold, clippedRegular,
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>card names</title>
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
    let report
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
    folder = FRONTEND / "node_modules" / f".harness-card-names-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "api_stub.js").write_text(API_STUB, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css"}, encoding="utf-8"
        )
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
                "--window-size=1100,4000", f"--remote-debugging-port={port}",
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


def _named(rows: list[dict], label: str) -> dict:
    found = [row for row in rows if row["text"] == label]
    assert found, (label, [row["text"] for row in rows])
    return found[0]


def _semi_bold(row: dict, ink: str) -> None:
    assert row["size"] == "13px", row
    assert row["weight"] == "600", row
    assert row["color"] == ink, row


def test_the_model_server_names_stand_in_13_semi_bold_in_the_ink_colour(report):
    for label in ("Kontext", "GPU-Layer", "CPU-Threads", "Port"):
        _semi_bold(_named(report["model"], label), report["ink"])


def test_the_speech_server_names_stand_in_13_semi_bold(report):
    assert report["speech"], "the speech page drew no card"
    for row in report["speech"]:
        _semi_bold(row, report["ink"])
    labels = {row["text"] for row in report["speech"]}
    assert {"GPU-Layer", "CPU-Threads"} <= labels, labels


def test_the_image_server_names_stand_in_13_semi_bold(report):
    assert report["image"], "the device card drew no rows"
    for row in report["image"]:
        _semi_bold(row, report["ink"])


def test_the_version_name_stands_semi_bold_beside_the_mark_of_its_build(report):
    # The build number ends the row as a mark, with or without a program, so
    # the name is never alone in its row.
    for scope in ("llamaA", "llamaB"):
        version = [row for row in report[scope] if row["text"] == "Version"]
        assert len(version) == 1, (scope, report[scope])
        assert not version[0]["only"], (scope, version)
        _semi_bold(version[0], report["ink"])


def test_the_names_of_a_catalogue_row_keep_their_own_weight_when_they_stand_alone(report):
    assert [row["text"] for row in report["ticks"]] == ["First model", "Second model"]
    # The unticked one has nothing beside its name: it is the case that counts.
    assert report["ticks"][0]["only"], report["ticks"]
    for row in report["ticks"]:
        _semi_bold(row, report["ink"])


def test_the_error_of_a_failed_fetch_in_a_card_stays_regular(report):
    errors = [row for row in report["llamaA"] if row["only"] and not row["text"].startswith("Version")]
    assert len(errors) == 1, report["llamaA"]
    for row in errors:
        assert row["weight"] == "400", row


def test_a_name_of_the_parameter_board_stands_in_13_semi_bold(report):
    for label in ("Temperature", "Top-K"):
        _semi_bold(_named(report["params"], label), report["ink"])


def test_a_row_with_only_a_message_stays_regular(report):
    rows = [
        _named(report["message"], label)
        for label in ("Loading the generator variants…", "A failed fetch", "A slider message", "A count message")
    ]
    for row in rows:
        assert row["only"], row
        assert row["size"] == "13px" and row["weight"] == "400", row


def test_a_name_beside_its_value_is_semi_bold_where_a_message_row_is_not(report):
    setting = _named(report["message"], "A setting")
    assert not setting["only"]
    assert setting["weight"] == "600", setting


def test_the_names_of_the_builds_stay_semi_bold(report):
    assert [row["text"] for row in report["builds"]] == ["cpu", "cuda12", "vulkan"]
    for row in report["builds"]:
        assert row["weight"] == "600", row


def test_silence_the_values_stay_regular(report):
    assert len(report["values"]) >= 6, report["values"]
    for value in report["values"]:
        assert value["weight"] == "400", value


def test_silence_a_heavier_name_makes_no_row_taller_and_clips_no_name(report):
    assert len(report["heightsBold"]) >= 40, len(report["heightsBold"])
    assert report["heightsBold"] == report["heightsRegular"]
    # What ends in an ellipsis with the heavier weight already did without it.
    assert sorted(report["clippedBold"]) == sorted(report["clippedRegular"]), report["clippedBold"]
