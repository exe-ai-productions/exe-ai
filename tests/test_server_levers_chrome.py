"""The levers of the llama.cpp servers in the real sheet (Serverregler), in a
real browser: an empty GPU-layer field says "Auto" and stands for no count,
and the switch "Dynamisches Kontextfenster" next to the slot count.

The real component is built as it ships, with only the service's answers
replaced (`lib/api.js` by a stand-in) and the real German texts put in.
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
  import Serverregler from '../src/teile/Serverregler.svelte'
  import { scene } from './scene.svelte.js'
</script>

<!-- The two halves the model and agent windows draw, wired the way those
     windows wire them: the storage half only reads the slot count and the
     levers (for the context one request gets), the advanced half writes. -->
<div style="width: 1000px; margin: 0 auto;">
  <Serverregler
    kennung="rs" teil="speicher"
    bind:schichten={scene.schichten} maxSchichten={99}
    bind:kontext={scene.kontext} kontextstufen={[4096, 8192, 16384, 32768]}
    bind:moeSchichten={scene.moe}
    parallel={scene.parallel} fein={scene.fein}
  />
  <Serverregler
    kennung="rs" teil="fein"
    bind:parallel={scene.parallel}
    bind:fein={scene.fein}
  />
</div>
"""

SCENE_JS = """export const scene = $state({
  schichten: null,
  moe: null,
  parallel: null,
  kontext: 16384,
  fein: { kv_cache: 'f16', moe_auf_cpu: false, festnageln: false, kv_unified: true },
})
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { texte } from '../src/lib/texte.svelte.js'
import katalog from '../../app/locales/de.json'
import '../src/stil/global.css'

texte.katalog = katalog
window.scene = scene
mount(Shell, { target: document.getElementById('root') })
"""

API_STUB = """export const setSessionKey = () => {}
export const sitzungNeuLaden = () => {}
export const spracheMerken = () => {}
export const rememberStatusText = () => {}
export const bootMessage = (failure) => String(failure)
export const allPages = async () => []
export async function* antwortStrom() {}
export async function* zusehenStrom() {}
export class ApiFehler extends Error {}
export const api = new Proxy({}, { get: () => async () => ({}) })
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const scene = window.scene
const row = (id) => document.querySelector(`label[for="${id}"]`).closest('.zeile')
const layerRow = () => row('rs-schichten')
const field = () => layerRow().querySelector('input[type=number]')
const slider = () => document.getElementById('rs-schichten')
const word = () => layerRow().querySelector('.nullwort')?.textContent ?? null
const type = (el, text) => {
  el.focus()
  el.value = text
  el.dispatchEvent(new Event('input', { bubbles: true }))
  el.dispatchEvent(new Event('change', { bubbles: true }))
  el.blur()
}
const move = (el, value) => {
  el.value = String(value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}
const kvRow = () => [...document.querySelectorAll('.zeile')].find((r) => r.textContent.includes('Dynamisches Kontextfenster'))
const kvSwitch = () => kvRow().querySelector('button[role=switch]')
const perRequest = () => document.querySelector('.jeanfrage')?.textContent ?? null

await wait(400)

// 1. Nothing named: the field says Auto, the count is null, the track rests at its end.
report.start = { word: word(), count: scene.schichten, track: slider().value, label: layerRow().textContent.includes('GPU') }

// 2. A number typed: the count, the track follows, the word is gone.
type(field(), '40'); await wait(150)
report.typed = { word: word(), count: scene.schichten, track: slider().value }

// 3. The field emptied: back to Auto.
type(field(), ''); await wait(150)
report.emptied = { word: word(), count: scene.schichten, track: slider().value }

// 4. The track moved: a number; moved to the end it is the number, not Auto.
move(slider(), 50); await wait(150)
report.moved = { word: word(), count: scene.schichten }
move(slider(), 99); await wait(150)
report.at_end = { word: word(), count: scene.schichten }

// 5. Zero is a count.
type(field(), '0'); await wait(150)
report.zero = { word: word(), count: scene.schichten }
type(field(), ''); await wait(150)

// 6. The switch: slot count on Auto, it stands on and cannot be moved.
report.switch_auto = { checked: kvSwitch().getAttribute('aria-checked'), disabled: kvSwitch().disabled, shown: perRequest() }

// 7. A slot count: the switch can be moved; off, the request's context is named.
scene.parallel = 2; await wait(150)
report.switch_slots = { checked: kvSwitch().getAttribute('aria-checked'), disabled: kvSwitch().disabled, shown: perRequest() }
kvSwitch().click(); await wait(150)
report.switch_off = { checked: kvSwitch().getAttribute('aria-checked'), stored: scene.fein.kv_unified, shown: perRequest() }
kvSwitch().click(); await wait(150)
report.switch_on_again = { checked: kvSwitch().getAttribute('aria-checked'), stored: scene.fein.kv_unified, shown: perRequest() }

// 8. Switched off, then the slot count back to Auto: the switch stands on, nothing is named.
kvSwitch().click(); await wait(150)
scene.parallel = null; await wait(150)
report.off_then_auto = { checked: kvSwitch().getAttribute('aria-checked'), disabled: kvSwitch().disabled, shown: perRequest(), stored: scene.fein.kv_unified }

// 9. The MoE experts: an empty field is Auto and the track rests at 0; the track
// dragged from there names a number in the field; a field typed moves the track.
const moeRow = () => row('rs-moe')
const moeField = () => moeRow().querySelector('input[type=number]')
const moeTrack = () => document.getElementById('rs-moe')
const moeWord = () => moeRow().querySelector('.nullwort')?.textContent ?? null
const moeState = () => ({ word: moeWord(), count: scene.moe, track: moeTrack().value, field: moeField().value })
report.moe_start = moeState()
move(moeTrack(), 5); await wait(150)
report.moe_dragged = moeState()
move(moeTrack(), 12); await wait(150)
report.moe_dragged_on = moeState()
type(moeField(), ''); await wait(150)
report.moe_emptied = moeState()
type(moeField(), '7'); await wait(150)
report.moe_typed = moeState()
move(moeTrack(), 0); await wait(150)
report.moe_dragged_to_zero = moeState()
type(moeField(), '3'); await wait(150)
type(moeField(), '0'); await wait(150)
report.moe_typed_zero = moeState()

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>levers</title>
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
    folder = FRONTEND / f".harness-levers-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "api_stub.js").write_text(API_STUB, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [str(FRONTEND / "node_modules" / ".bin" / "vite"), "build", "--config", "vite.config.js"],
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
                "--window-size=1100,1400", f"--remote-debugging-port={port}",
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


def test_an_empty_layer_field_says_auto_and_stands_for_no_count(report):
    assert report["start"] == {"word": "Auto", "count": None, "track": "99", "label": True}


def test_a_number_typed_is_the_count_and_the_track_follows(report):
    assert report["typed"] == {"word": None, "count": 40, "track": "40"}


def test_the_emptied_field_goes_back_to_auto(report):
    assert report["emptied"] == {"word": "Auto", "count": None, "track": "99"}


def test_the_track_moved_names_a_number_even_at_its_end(report):
    assert report["moved"] == {"word": None, "count": 50}
    assert report["at_end"] == {"word": None, "count": 99}


def test_zero_is_a_count_and_not_auto(report):
    assert report["zero"] == {"word": None, "count": 0}


def test_with_the_slots_on_auto_the_switch_stands_on_and_cannot_be_moved(report):
    assert report["switch_auto"] == {"checked": "true", "disabled": True, "shown": None}


def test_with_a_slot_count_the_switch_can_be_moved_and_on_it_names_nothing(report):
    assert report["switch_slots"] == {"checked": "true", "disabled": False, "shown": None}
    assert report["switch_on_again"] == {"checked": "true", "stored": True, "shown": None}


def test_off_the_window_names_the_context_one_request_gets(report):
    assert report["switch_off"] == {"checked": "false", "stored": False, "shown": "2 \u00d7 8k"}


def test_a_stored_off_does_not_show_while_the_slot_count_is_auto(report):
    assert report["off_then_auto"] == {
        "checked": "true", "disabled": True, "shown": None, "stored": False,
    }


def test_the_moe_field_empty_says_auto_and_the_track_rests_at_zero(report):
    assert report["moe_start"] == {"word": "Auto", "count": None, "track": "0", "field": ""}


def test_the_moe_track_dragged_from_an_empty_field_names_the_number(report):
    assert report["moe_dragged"] == {"word": None, "count": 5, "track": "5", "field": "5"}
    assert report["moe_dragged_on"] == {"word": None, "count": 12, "track": "12", "field": "12"}


def test_the_moe_field_emptied_is_auto_and_the_track_goes_to_zero(report):
    assert report["moe_emptied"] == {"word": "Auto", "count": None, "track": "0", "field": ""}


def test_a_moe_number_typed_moves_the_track(report):
    assert report["moe_typed"] == {"word": None, "count": 7, "track": "7", "field": "7"}


def test_the_moe_track_dragged_to_zero_empties_the_field(report):
    assert report["moe_dragged_to_zero"] == {"word": "Auto", "count": None, "track": "0", "field": ""}


def test_a_moe_zero_typed_is_the_same_as_empty(report):
    assert report["moe_typed_zero"] == {"word": "Auto", "count": None, "track": "0", "field": ""}
