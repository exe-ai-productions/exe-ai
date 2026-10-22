"""The head of the pages Local models, Servers (overview and model server),
Cloud providers and Catalogue, in a real browser: the sign stands in a box of
40 × 40 with a radius of 9, the glass of a button and its fine line of one
pixel; the sign in it is 22 and in the middle; the title stands 14 px right of
the box, 22 px, in the normal weight, without letter spacing; Local models
wears the grid sign and its count of quick-pick models stands as a quiet pill in
the row of the title, 12 px from it.

The real pages are built as they ship with the global stylesheet, with only the
service's answers replaced (`lib/api.js` by a stand-in) and the real German
texts put in. Skipped where there is no Chrome or no node, like the other
browser tests.
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
  import ModelleLokal from '../../src/teile/ModelleLokal.svelte'
  import ModelleCloud from '../../src/teile/ModelleCloud.svelte'
  import Katalog from '../../src/teile/Katalog.svelte'
  import Hauszeichen from '../../src/teile/Hauszeichen.svelte'
  import { scene } from './scene.svelte.js'
</script>

<div style="height: 1000px; display: flex; flex-direction: column; position: relative;">
  {#if scene.show === 'lokal'}<ModelleLokal offen={true} />{/if}
  {#if scene.show === 'cloud'}<ModelleCloud offen={true} />{/if}
  {#if scene.show === 'katalog'}<Katalog offen={true} />{/if}
  {#if scene.show === 'signs'}
    <span id="grid-sign"><Hauszeichen zeichen="raster" groesse={22} /></span>
    <span id="server-sign"><Hauszeichen zeichen="server" groesse={22} /></span>
  {/if}
</div>
"""

SCENE_JS = "export const scene = $state({ show: null })\n"

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import katalog from '../../../app/locales/de.json'
import { modellwahl } from '../../src/lib/modelle.svelte.js'
import '../../src/stil/global.css'

texte.katalog = katalog
texte.sprache = 'de'
window.zustand = zustand
window.modellwahl = modellwahl
window.scene = scene
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
    const answer = (window.answers || {})[name]
    return JSON.parse(JSON.stringify(answer === undefined ? {} : answer))
  },
})
"""

CASES = r"""
const report = { errors: [], pages: {} }
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
  runnerAuskunft: { ...machine, laeuft: false, port: null, modell: null, programm: true },
  einbettungAuskunft: { ...machine, laeuft: false, port: null, programm: true },
  agentenmodellAuskunft: { ...machine, laeuft: false, port: null, programm: true },
  spracheAuskunft: { ...machine, laeuft: false, port: null, modelle: [], programm: true },
  bereinigungAuskunft: { ...machine, laeuft: false, port: null, modelle: [], programm: true },
  turboStand: { zustand: 'aus', port: 8097, programm_da: true, picture_running: false },
  speicherBlick: { wired_gb: 10, wired_limit_gb: 20, gesamt_gb: 32 },
  einstellungAufgeloest: { wert: null },
  modelle: [], modelleAlle: [], serverUebersicht: [], oauthStatus: [],
  bildmodelle: { modelle: [], families: {}, programm_da: true, standardmodell: '' },
  bildProgrammStand: {}, bildProgrammVarianten: { varianten: [] }, bildFamilien: [],
  bildAufbereitung: { verbesserer: 'agent', anweisungen: { sdxl: '' } },
  imageDevices: [], imageModelFiles: [], imageFamilies: {},
  runnerProtokoll: [], einbettungProtokoll: [], spracheProtokoll: [], bereinigungProtokoll: [],
  agentenmodellProtokoll: [], bildProtokoll: [],
}

const probe = document.createElement('span')
document.body.appendChild(probe)
const colourOf = (property, value) => {
  probe.style[property] = value
  const read = getComputedStyle(probe)[property === 'background' ? 'backgroundColor' : property]
  probe.style[property] = ''
  return read
}
report.want = {
  glass: colourOf('background', 'var(--glass-button)'),
  edge: colourOf('color', 'var(--glass-button-edge)'),
  text: colourOf('color', 'var(--text)'),
}
const rect = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
const head = (box, title) => {
  const style = getComputedStyle(box)
  const titleStyle = getComputedStyle(title)
  const sign = box.querySelector('svg')
  const boxRect = rect(box)
  const signRect = rect(sign)
  return {
    box: boxRect,
    ground: style.backgroundColor,
    shadow: style.boxShadow,
    radius: style.borderTopLeftRadius,
    sign: signRect,
    signCentre: signRect && [signRect.x + signRect.width / 2 - (boxRect.x + boxRect.width / 2), signRect.y + signRect.height / 2 - (boxRect.y + boxRect.height / 2)],
    signMarkup: sign ? sign.innerHTML : null,
    title: title.textContent.trim(),
    titleRect: rect(title),
    gap: rect(title).x - boxRect.right,
    size: titleStyle.fontSize,
    weight: titleStyle.fontWeight,
    spacing: titleStyle.letterSpacing,
    lineHeight: titleStyle.lineHeight,
    colour: titleStyle.color,
  }
}
const show = async (page, wish) => {
  window.scene.show = null
  await wait(200)
  if (wish) window.zustand.lokalWunsch = wish
  window.scene.show = page
  await until(() => document.querySelector('header.kopf .titel, header.kopf .title'), page + ' head')
  await wait(900)
}
const find = () => {
  const kopf = document.querySelector('header.kopf')
  return [kopf.querySelector('.kasten, .sign-box'), kopf.querySelector('.titel, .title')]
}

for (const [key, page, wish] of [['lokal', 'lokal', 'lokal'], ['overview', 'lokal', 'overview'], ['server', 'lokal', 'server'], ['cloud', 'cloud', null], ['katalog', 'katalog', null]]) {
  await show(page, wish)
  const [box, title] = find()
  report.pages[key] = head(box, title)
  report.pills = report.pills || {}
  report.pills[key] = document.querySelectorAll('header.kopf .zahlpille').length
  if (key === 'lokal') {
    // Two local models, one of them switched off: the quick-pick count is drawn beside the title.
    window.modellwahl.aus = ['two']
    window.zustand.modelle = [
      { id: 'one', name: 'One', group: 'local', anbieter: 'local' },
      { id: 'two', name: 'Two', group: 'local', anbieter: 'local' },
    ]
    // Without the pill the case goes on and the test of the pill says so.
    await until(() => document.querySelector('header.kopf .zahlpille .pille'), 'the count pill', 4000).catch(() => null)
    await wait(300)
    const pill = document.querySelector('header.kopf .zahlpille .pille')
    if (!pill) report.pill = null
    else {
    const row = document.querySelector('header.kopf .markenzeile')
    const pillStyle = getComputedStyle(pill)
    const pillRect = rect(pill)
    const titleRect = rect(document.querySelector('header.kopf .titel'))
    const rowRect = rect(row)
    report.pill = {
      text: pill.textContent.trim(),
      farbe: pill.dataset.farbe,
      gap: pillRect.x - titleRect.right,
      centre: (pillRect.y + pillRect.height / 2) - (titleRect.y + titleRect.height / 2),
      inRow: pillRect.y >= rowRect.y - 0.5 && pillRect.bottom <= rowRect.bottom + 0.5,
      ground: pillStyle.backgroundColor,
      colour: pillStyle.color,
      size: pillStyle.fontSize,
      weight: pillStyle.fontWeight,
      padding: pillStyle.padding,
      radius: pillStyle.borderTopLeftRadius,
      dot: getComputedStyle(pill, '::before').display,
      lineBelow: Boolean(document.querySelector('header.kopf .zaehler')),
    }
    }
    report.want.quiet = colourOf('color', 'var(--text-leise)')
  }
}
// The two signs the house draws, to compare the heads with.
window.scene.show = null
await wait(200)
window.scene.show = 'signs'
await until(() => document.querySelector('#grid-sign svg'), 'the reference signs')
report.gridSign = document.querySelector('#grid-sign svg').innerHTML
report.serverSign = document.querySelector('#server-sign svg').innerHTML
report.errors = window.__errors
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>page head</title>
<style>body { margin: 0; background: #1c1c1a; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  window.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16)
  window.cancelAnimationFrame = (id) => clearTimeout(id)
</script>
<script>
  window.__errors = []
  window.addEventListener('error', (event) => window.__errors.push(String(event.message)))
  window.addEventListener('unhandledrejection', (event) => window.__errors.push(String(event.reason)))
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


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-pagehead-{uuid4().hex}"
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
                "--window-size=1400,1000", f"--remote-debugging-port={port}",
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


PAGES = {
    "lokal": "Lokale Modelle",
    "overview": "Server",
    "server": "Modell-Server",
    "cloud": "Cloud-Anbieter",
    "katalog": "Katalog",
}


def test_the_harness_has_the_house_colours(report):
    assert report["want"]["glass"] != report["want"]["edge"]
    assert report["want"]["text"] not in ("rgb(0, 0, 0)", "")
    assert report["errors"] == []


@pytest.mark.parametrize("page", list(PAGES))
def test_the_box_is_40_by_40_with_radius_9_on_the_glass_of_a_button_with_its_line(report, page):
    head = report["pages"][page]
    assert head["title"] == PAGES[page], head["title"]
    assert abs(head["box"]["width"] - 40) <= 0.5 and abs(head["box"]["height"] - 40) <= 0.5, head["box"]
    assert head["radius"] == "9px"
    assert head["ground"] == report["want"]["glass"], head
    assert head["ground"] not in ("rgba(0, 0, 0, 0)", "transparent"), "the box has no glass"
    assert report["want"]["edge"] in head["shadow"] and "inset" in head["shadow"] and "1px" in head["shadow"], head["shadow"]


@pytest.mark.parametrize("page", list(PAGES))
def test_the_sign_is_22_and_in_the_middle_of_the_box(report, page):
    head = report["pages"][page]
    assert abs(head["sign"]["width"] - 22) <= 0.5 and abs(head["sign"]["height"] - 22) <= 0.5, head["sign"]
    assert abs(head["signCentre"][0]) <= 0.5 and abs(head["signCentre"][1]) <= 0.5, head["signCentre"]


@pytest.mark.parametrize("page", list(PAGES))
def test_the_title_stands_14_px_from_the_box_22_px_normal_without_letter_spacing(report, page):
    head = report["pages"][page]
    assert abs(head["gap"] - 14) <= 0.5, head["gap"]
    assert head["size"] == "22px" and head["weight"] == "400", head
    assert head["spacing"] in ("normal", "0px"), head["spacing"]
    assert abs(float(head["lineHeight"].removesuffix("px")) / 22 - 1.3) <= 0.01, head["lineHeight"]
    assert head["colour"] == report["want"]["text"]


def test_local_models_wears_the_grid_sign_and_the_server_pages_keep_their_own(report):
    assert report["gridSign"] and report["serverSign"] and report["gridSign"] != report["serverSign"]
    assert report["pages"]["lokal"]["signMarkup"] == report["gridSign"]
    assert report["pages"]["overview"]["signMarkup"] != report["gridSign"]
    assert report["pages"]["server"]["signMarkup"] != report["gridSign"]


def test_the_quick_pick_count_is_a_quiet_pill_in_the_row_of_the_title_12_px_from_it(report):
    pill = report["pill"]
    assert pill is not None, "the count pill is not drawn"
    assert pill["text"] == "1 in der Schnellwahl", pill["text"]
    assert pill["farbe"] == "count" and pill["dot"] == "none", pill
    assert pill["inRow"] and abs(pill["centre"]) <= 1, pill
    assert abs(pill["gap"] - 12) <= 0.5, pill["gap"]
    assert pill["ground"] == report["want"]["glass"] and pill["colour"] == report["want"]["quiet"], pill
    assert (pill["size"], pill["weight"], pill["padding"], pill["radius"]) == ("12px", "500", "5px 11px", "9px"), pill
    assert pill["lineBelow"] is False


def test_no_count_pill_while_there_is_no_local_model_yet(report):
    # Measured before the first model exists on the page.
    assert report["pills"]["lokal"] == 0


@pytest.mark.parametrize("page", ["overview", "server", "cloud", "katalog"])
def test_the_other_pages_carry_no_count_pill(report, page):
    # Measured after the models are filled in, so only the page decides.
    assert report["pills"][page] == 0, page
