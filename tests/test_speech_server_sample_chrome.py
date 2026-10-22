"""The speech server's voice sample block, measured in a real browser.

`Sprachserver.svelte` is built as shipped and drawn in headless Chrome with
the service's answers replaced (`lib/api.js` by a stand-in that keeps the
stored settings and the folder's samples, and lists every call). The
microphone is the fake device Chrome offers, so the recording is real. The
block "Voice sample" stands under the second row, as wide as the page, with
two rows of 56: the choice with its folder button, and the buttons of the
recording (record, play, stop) with the chosen file's name and length, and the
bin at the far right. A recording is kept and chosen at once, deleting asks
first and empties the choice, and the record button is locked while the
dictation holds the microphone. The parameters stand folded to the
temperature and open to all five, and the three choice fields show a dash
where nothing is chosen. Skipped where there is no Chrome or no node, like
the other browser tests.
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
  import Sprachserver from %(sprach)r
  import { scene } from './scene.svelte.js'
</script>

<div id="frame" style="width: 1000px; margin: 0 auto;">
  {#if scene.show === 'sprach'}<Sprachserver />{/if}
</div>
"""

SCENE_JS = "export const scene = $state({ show: null })\n"

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand, frageBeantworten } from '../../src/lib/zustand.svelte.js'
import * as rec from '../../src/lib/aufnahme.svelte.js'
import katalog from '../../../app/locales/de.json'
import %(global)r

texte.katalog = katalog
window.scene = scene
window.zustand = zustand
window.frageBeantworten = frageBeantworten
window.rec = rec
mount(Shell, { target: document.getElementById('root') })
"""

# The service's answers: the settings, the samples lying in the folder with
# their lengths, and the list of calls.
API_STUB = r"""const stub = (window.__stub = {
  settings: { diktat: {} },
  samples: ['own.wav'],
  lengths: { 'own.wav': 7 },
  calls: [],
})
const copy = (value) => JSON.parse(JSON.stringify(value))
const works = {
  sprache: 'auto', anweisung: 'x', bereinigung: 'aus', putzmodell: 'clean.gguf', bereinigung_anweisung: 'y',
  vorlesen: true, keep_model_in_memory: true, conversation_pause_seconds: 3, stimme: '', stimmprobe: '',
  stimmsprache: '', stimmtemperatur: 0.9, stimmtop_k: 50, stimmtop_p: 1, stimmmin_p: 0, stimmstrafe: 1.05,
  stimmschichten: 99, stimmfaeden: 0, gespraechsanweisung: 'z', automatik: false, microphone_key: 'Meta+Alt',
}
const state = () => ({
  programm: '/bin/llama-server', version: 'b1', updatable: false, restorable: false,
  ordner: '/m', modelle: [{ name: 'voice.gguf', groesse_gb: 1 }], mmproj: [],
  projektoren: { 'voice.gguf': 'mm.gguf' }, laeuft: false, modell: null, port: 8084,
  kontext: null, schichten: null, threads: null, kerne: 8, unknown_architecture: null,
  vorgaben: { kontext: 4096, schichten: 99, threads: 0 }, diktat_vorgaben: copy(works),
  stimmproben: [...stub.samples], stimmproben_dauer: copy(stub.lengths),
})
// A short silence as a WAV, what the service would hand back.
const wavBytes = () => {
  const buffer = new ArrayBuffer(44 + 3200)
  const view = new DataView(buffer)
  const text = (at, value) => [...value].forEach((c, k) => view.setUint8(at + k, c.charCodeAt(0)))
  text(0, 'RIFF'); view.setUint32(4, 36 + 3200, true); text(8, 'WAVE'); text(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true)
  view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, 3200, true)
  return buffer
}
const methods = {
  spracheAuskunft: async () => state(),
  spracheProtokoll: async () => [],
  einstellungAufgeloest: async (key) => ({ wert: copy(stub.settings[key] || {}), herkunft: {} }),
  einstellungMischen: async (scope, key, values) => {
    stub.calls.push({ name: 'patch', key, values: copy(values) })
    const row = stub.settings[key] || (stub.settings[key] = {})
    Object.assign(row, values)
    return { wert: copy(row) }
  },
  voiceSampleSave: async (wav) => {
    let number = 1
    while (stub.samples.includes('stimmprobe-' + number + '.wav')) number += 1
    const name = 'stimmprobe-' + number + '.wav'
    stub.samples.push(name)
    stub.lengths[name] = 12
    stub.settings.diktat.stimmprobe = name
    stub.calls.push({ name: 'save', bytes: wav.size, type: wav.type, saved: name })
    return { name, seconds: 12 }
  },
  voiceSampleBlob: async (name) => {
    stub.calls.push({ name: 'blob', sample: name })
    // The service takes a moment: a stop pressed meanwhile must win.
    if (stub.slow) await new Promise((done) => setTimeout(done, 200))
    return new Blob([wavBytes()], { type: 'audio/wav' })
  },
  voiceSampleDelete: async (name) => {
    stub.calls.push({ name: 'delete', sample: name })
    stub.samples = stub.samples.filter((n) => n !== name)
    delete stub.lengths[name]
    if (stub.settings.diktat.stimmprobe === name) stub.settings.diktat.stimmprobe = ''
    return state()
  },
  spracheOrdnerOeffnen: async () => {
    stub.calls.push({ name: 'folder' })
    return true
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
const box = (node) => {
  const r = node.getBoundingClientRect()
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }
}
const block = () => {
  const head = Array.from(document.querySelectorAll('.tafelkopf .name')).find((n) => n.textContent.trim() === 'Stimmprobe')
  return head && head.closest('section.abschnitt')
}
const names = () => ({
  record: document.getElementById('sp-probe-aufnehmen'),
  play: document.getElementById('sp-probe-abspielen'),
  stop: document.getElementById('sp-probe-stoppen'),
  bin: document.getElementById('sp-probe-loeschen'),
  line: document.querySelector('.probename'),
})
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()

scene.show = 'sprach'
for (let k = 0; k < 100 && !(block() && document.querySelector('.probename')); k += 1) await wait(50)
await wait(400)

// 1. The block and its rows.
const sample = block()
const rows = Array.from(sample.querySelectorAll('.karte > .zeile'))
const above = document.getElementById('sp-vorlesen').closest('section.abschnitt')
const voice = document.getElementById('sp-stimmemodell').closest('section.abschnitt')
const row = voice.closest('.reihe')
const parameters = document.querySelector('.parameterblock')
report.layout = {
  block: box(sample), frame: box(document.getElementById('frame')), above: box(above), parameters: box(parameters),
  columns: Array.from(row.children).map((c) => box(c)),
  rows: rows.map((r) => box(r)),
  picker: box(sample.querySelector('.probewahl')), field: box(sample.querySelector('.probewahl button[role=combobox]')),
  buttons: Array.from(sample.querySelectorAll('.zeichenknopf')).map((b) => ({ ...box(b), id: b.id, sign: box(b.querySelector('svg')) })),
  title: sample.querySelector('.tafelkopf .name').textContent.trim(),
  titleSize: getComputedStyle(sample.querySelector('.tafelkopf .name')).fontSize,
  titleWeight: getComputedStyle(sample.querySelector('.tafelkopf .name')).fontWeight,
  foldSize: getComputedStyle(document.querySelector('.klappzeile span')).fontSize,
  foldWeight: getComputedStyle(document.querySelector('.klappzeile span')).fontWeight,
  label: text(sample.querySelector('.probezeile .name')),
  conversationHasNoSampleRow: !above.querySelector('#sp-stimmprobe'),
  folderTitle: sample.querySelector('.probezeile .zeichenknopf').title,
}

// 2. The dash where nothing is chosen, and the line of the sample.
const selected = (id) => text(document.getElementById(id))
report.dash = { voice: selected('sp-stimmemodell'), sample: selected('sp-stimmprobe'), language: selected('sp-stimmsprache'), line: text(names().line) }
report.initial = {
  record: names().record.disabled, play: names().play.disabled, stop: names().stop.disabled, bin: names().bin.disabled,
}

// 3. The parameters: folded to the temperature, open to five.
const fold = document.querySelector('.klappzeile')
report.params = { head: box(fold), closed: parameters.querySelectorAll('.regel').length, expandedBefore: fold.getAttribute('aria-expanded') }
fold.click()
await wait(300)
report.params.open = parameters.querySelectorAll('.regel').length
report.params.expandedAfter = fold.getAttribute('aria-expanded')
fold.click()
await wait(300)
report.params.closedAgain = parameters.querySelectorAll('.regel').length

// 4. The microphone held by the dictation locks the record button.
await window.rec.starten()
await wait(300)
report.locked = { disabled: names().record.disabled, title: names().record.title }
window.rec.stoppen()
await wait(300)
report.unlocked = { disabled: names().record.disabled, title: names().record.title }

// 5. A recording: made, stopped, kept, chosen, shown.
names().record.click()
await wait(1700)
report.recording = { line: text(names().line), stopEnabled: !names().stop.disabled, recordDisabled: names().record.disabled, playDisabled: names().play.disabled }
names().stop.click()
await wait(800)
report.saved = {
  calls: stub.calls.filter((c) => c.name === 'save'),
  stored: stub.settings.diktat.stimmprobe,
  picker: selected('sp-stimmprobe'), line: text(names().line),
  play: names().play.disabled, bin: names().bin.disabled, stop: names().stop.disabled,
}

// 6. Playing: the service hands the sample out; stop ends it. Every start of
// a sound is counted.
const starts = []
const RealAudio = window.Audio
window.Audio = function (source) {
  const sound = new RealAudio(source)
  const start = sound.play.bind(sound)
  sound.play = () => { starts.push(source); return start() }
  return sound
}
names().play.click()
await wait(300)
report.playing = { blob: stub.calls.filter((c) => c.name === 'blob'), stopEnabled: !names().stop.disabled, starts: starts.length }
names().stop.click()
await wait(300)
report.stopped = { stopEnabled: !names().stop.disabled, playEnabled: !names().play.disabled }

// 7. The bin asks first.
names().bin.click()
await wait(300)
report.asked = { text: window.zustand.frage && window.zustand.frage.text, deletes: stub.calls.filter((c) => c.name === 'delete').length }
window.frageBeantworten(false)
await wait(300)
report.declined = { deletes: stub.calls.filter((c) => c.name === 'delete').length, line: text(names().line) }
names().bin.click()
await wait(300)
window.frageBeantworten(true)
await wait(600)
report.deleted = {
  calls: stub.calls.filter((c) => c.name === 'delete'), stored: stub.settings.diktat.stimmprobe,
  picker: selected('sp-stimmprobe'), line: text(names().line), samples: [...stub.samples],
  bin: names().bin.disabled, play: names().play.disabled,
}

// 8. A recording ended by someone else (the dictation took the microphone)
// leaves no running line behind; a stop pressed while the sample is still
// being fetched ends the play before it starts.
names().record.click()
await wait(600)
window.rec.stoppen()
await wait(400)
report.takenAway = { line: text(names().line), stopDisabled: names().stop.disabled, recordDisabled: names().record.disabled, saves: stub.calls.filter((c) => c.name === 'save').length }
document.getElementById('sp-stimmprobe').click()
await wait(200)
const own = Array.from(document.querySelectorAll('[role=listbox] [role=option]')).find((o) => text(o) === 'own.wav')
own.click()
await wait(400)
stub.slow = true
names().play.click()
await wait(40)
names().stop.click()
await wait(500)
report.quickStop = { stopDisabled: names().stop.disabled, playDisabled: names().play.disabled, starts: starts.length }

// 9. The folder button still shows the folder.
sample.querySelector('.probezeile .zeichenknopf').click()
await wait(200)
report.folder = stub.calls.filter((c) => c.name === 'folder').length

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
    folder = FRONTEND / "node_modules" / f".harness-speech-sample-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"sprach": "../../src/teile/Sprachserver.svelte"}, encoding="utf-8"
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
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
                "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                "--window-size=1100,1500", f"--remote-debugging-port={port}",
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


def _close(a: float, b: float, by: float = 1.0) -> bool:
    return abs(a - b) <= by


# --- The block ---


def test_the_block_stands_under_the_second_row_as_wide_as_the_page(report):
    layout = report["layout"]
    assert layout["title"] == "Stimmprobe", layout["title"]
    # The title of the block and the title of the folding row are the house's
    # one section title: the same size, semi bold.
    assert layout["titleSize"] == layout["foldSize"], (layout["titleSize"], layout["foldSize"])
    assert layout["titleWeight"] == "600" and layout["foldWeight"] == "600", (layout["titleWeight"], layout["foldWeight"])
    assert layout["conversationHasNoSampleRow"] is True
    assert layout["block"]["top"] >= layout["above"]["bottom"] - 1, layout
    assert layout["parameters"]["top"] >= layout["block"]["bottom"] - 1, layout
    assert _close(layout["block"]["width"], layout["parameters"]["width"]), layout
    assert _close(layout["block"]["width"], layout["frame"]["width"], 2), layout


def test_the_columns_of_the_second_row_stay_equally_tall(report):
    left, right = report["layout"]["columns"]
    assert _close(left["height"], right["height"]), report["layout"]["columns"]


def test_the_block_has_two_rows_of_56(report):
    rows = report["layout"]["rows"]
    assert len(rows) == 2, rows
    for row in rows:
        assert _close(row["height"], 56), rows
    assert report["layout"]["label"] == "Datei"


def test_the_picker_is_200_by_32_and_the_buttons_are_34_by_34_with_a_sign_of_15(report):
    layout = report["layout"]
    assert _close(layout["picker"]["width"], 200), layout["picker"]
    assert _close(layout["field"]["height"], 32), layout["field"]
    ids = [b["id"] for b in layout["buttons"]]
    assert ids == ["", "sp-probe-aufnehmen", "sp-probe-abspielen", "sp-probe-stoppen", "sp-probe-loeschen"], ids
    for button in layout["buttons"]:
        assert _close(button["width"], 34) and _close(button["height"], 34), button
        assert _close(button["sign"]["width"], 15, 0.6), button
        assert _close(button["sign"]["cx"] if "cx" in button["sign"] else (button["sign"]["left"] + button["sign"]["right"]) / 2,
                      (button["left"] + button["right"]) / 2, 0.6), button


def test_the_three_recording_buttons_follow_each_other_and_the_bin_stands_at_the_far_right(report):
    layout = report["layout"]
    record, play, stop, bin_ = layout["buttons"][1:]
    assert record["left"] < play["left"] < stop["left"] < bin_["left"]
    assert _close(play["left"] - record["right"], 10, 1.5) and _close(stop["left"] - play["right"], 10, 1.5)
    row = layout["rows"][1]
    assert _close(row["right"] - bin_["right"], 16, 1.5), (row, bin_)
    assert record["top"] >= layout["rows"][0]["bottom"] - 1


def test_a_recording_ended_by_the_dictation_leaves_no_running_line(report):
    taken = report["takenAway"]
    assert taken["line"] == "-" or ":" not in taken["line"], taken
    assert taken["stopDisabled"] is True and taken["recordDisabled"] is False, taken
    assert taken["saves"] == 1, taken


def test_a_stop_pressed_while_the_sample_is_fetched_ends_the_play_before_it_starts(report):
    quick = report["quickStop"]
    assert quick["stopDisabled"] is True and quick["playDisabled"] is False, quick
    # The one start is the play of the earlier case; the stopped one never started.
    assert quick["starts"] == 1, quick


def test_the_folder_button_names_the_folder_and_still_opens_it(report):
    assert report["layout"]["folderTitle"] == "Ordner öffnen"
    assert report["folder"] == 1


# --- The dash, the line, the parameters ---


def test_the_three_fields_show_a_dash_where_nothing_is_chosen(report):
    assert report["dash"]["voice"] == "-", report["dash"]
    assert report["dash"]["sample"] == "-", report["dash"]
    assert report["dash"]["language"] == "-", report["dash"]
    assert report["dash"]["line"] == "-"


def test_without_a_chosen_sample_only_recording_can_be_pressed(report):
    assert report["initial"] == {"record": False, "play": True, "stop": True, "bin": True}


def test_the_parameters_are_a_folding_row_of_34_that_shows_only_the_temperature_folded(report):
    params = report["params"]
    assert _close(params["head"]["height"], 34), params["head"]
    assert params["expandedBefore"] == "false" and params["expandedAfter"] == "true"
    assert params["closed"] == 1 and params["open"] == 5 and params["closedAgain"] == 1, params


# --- The recording ---


def test_the_record_button_is_locked_while_the_dictation_holds_the_microphone(report):
    assert report["locked"]["disabled"] is True, report["locked"]
    assert report["locked"]["title"] == "Das Diktat benutzt gerade das Mikrofon.", report["locked"]
    assert report["unlocked"]["disabled"] is False
    assert report["unlocked"]["title"] == "Aufnahme starten"


def test_while_recording_the_line_runs_and_only_stop_can_be_pressed(report):
    recording = report["recording"]
    assert recording["line"] != "-" and ":" in recording["line"], recording
    assert recording["stopEnabled"] is True
    assert recording["recordDisabled"] is True and recording["playDisabled"] is True


def test_a_stopped_recording_is_kept_chosen_and_shown_with_its_length(report):
    saved = report["saved"]
    assert [c["saved"] for c in saved["calls"]] == ["stimmprobe-1.wav"], saved
    assert saved["calls"][0]["type"] == "audio/wav" and saved["calls"][0]["bytes"] > 44, saved
    assert saved["stored"] == "stimmprobe-1.wav"
    assert saved["picker"] == "stimmprobe-1.wav", saved
    assert saved["line"] == "stimmprobe-1.wav · 0:12", saved
    assert saved["play"] is False and saved["bin"] is False and saved["stop"] is True, saved


def test_play_asks_the_service_for_the_chosen_sample_and_stop_ends_it(report):
    assert report["playing"]["blob"] == [{"name": "blob", "sample": "stimmprobe-1.wav"}], report["playing"]
    assert report["playing"]["stopEnabled"] is True
    assert report["playing"]["starts"] == 1
    assert report["stopped"] == {"stopEnabled": False, "playEnabled": True}


def test_the_bin_asks_first_and_deletes_only_after_a_yes(report):
    assert report["asked"] == {"text": "Diese Aufnahme löschen?", "deletes": 0}, report["asked"]
    assert report["declined"]["deletes"] == 0
    assert report["declined"]["line"] == "stimmprobe-1.wav · 0:12"


def test_after_the_delete_the_file_is_gone_and_the_choice_is_a_dash(report):
    deleted = report["deleted"]
    assert deleted["calls"] == [{"name": "delete", "sample": "stimmprobe-1.wav"}], deleted
    assert deleted["samples"] == ["own.wav"]
    assert deleted["stored"] == ""
    assert deleted["picker"] == "-" and deleted["line"] == "-", deleted
    assert deleted["bin"] is True and deleted["play"] is True
