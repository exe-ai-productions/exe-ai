"""The shared parts of the server pages, measured in a real browser: the head
signs of "Memory" and "Network", the angle of the folding head, the estimate
line with the decimal sign of the language, and the folder buttons — 34 px and
a row of 56 inside a card of a server page, 30 px where a folder row stands
outside a card.

The real `Serverregler.svelte`, `Serverabschnitt.svelte` and
`Speicherortzeile.svelte` are built as they ship, with only the service's
answers replaced (`lib/api.js` by a stand-in) and the real German texts put in.
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
  import Serverabschnitt from '../src/teile/Serverabschnitt.svelte'
  import Speicherortzeile from '../src/teile/Speicherortzeile.svelte'
</script>

<div style="width: 900px; display: flex; flex-direction: column; gap: 24px; padding: 16px;">
  <div id="sheet">
    <Serverregler kennung="rs" teil="alles" kontext={16384}
                  schaetzung={{ gesamt: 7.46 }} maschineGb={60.8} />
  </div>
  <div id="small">
    <Serverregler kennung="kl" teil="speicher" kontext={8192}
                  schaetzung={{ gesamt: 0.5 }} maschineGb={60.8} />
  </div>
  <div id="incard">
    <Serverabschnitt titel="Folder">
      <div class="zeile">A row above the folder row</div>
      <Speicherortzeile name="models" />
    </Serverabschnitt>
  </div>
  <div id="outside">
    <Speicherortzeile name="models" />
  </div>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { texte } from '../src/lib/texte.svelte.js'
import katalog from '../../app/locales/de.json'
import '../src/stil/global.css'

texte.katalog = katalog
texte.sprache = 'de'
window.answers = { speicherorteLesen: [{ name: 'models', pfad: '/data/models' }] }
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
export const api = new Proxy({}, {
  get: (_, name) => async () => {
    const answer = (window.answers || {})[name]
    return JSON.parse(JSON.stringify(answer === undefined ? {} : answer))
  },
})
"""

CASES = r"""
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const rect = (node) => {
  if (!node) return null
  const box = node.getBoundingClientRect()
  return { x: box.x, y: box.y, width: box.width, height: box.height }
}
for (let k = 0; k < 100 && !(document.querySelectorAll('.schaetz').length >= 2 && document.querySelectorAll('.ordnerknopf').length >= 6); k += 1) await wait(100)
await wait(500)

const sections = [...document.querySelectorAll('#sheet .abschnitt')].map((section) => {
  const sign = section.querySelector('.kopf .zeichen svg')
  return {
    title: section.querySelector('.kopf .name')?.textContent.trim() ?? null,
    sign: sign ? {
      view: sign.getAttribute('viewBox'),
      rects: sign.querySelectorAll('rect').length,
      circles: sign.querySelectorAll('circle').length,
      paths: [...sign.querySelectorAll('path')].map((path) => path.getAttribute('d')),
    } : null,
    angle: rect(section.querySelector('.winkel')),
  }
})
const folderRow = (scope) => {
  const row = document.querySelector(scope + ' .zeile:has(.knopfpaar)')
  return {
    row: rect(row),
    buttons: [...document.querySelectorAll(scope + ' .ordnerknopf')].map(rect),
    path: document.querySelector(scope + ' .pfad')?.textContent.trim() ?? null,
  }
}
const report = {
  sections,
  estimate: document.querySelector('#sheet .schaetz')?.textContent.trim() ?? null,
  smallEstimate: document.querySelector('#small .schaetz')?.textContent.trim() ?? null,
  incard: folderRow('#incard'),
  outside: folderRow('#outside'),
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html><meta charset=utf-8><title>server card measures</title>
<style>body { margin: 0; background: #1c1c1a; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  window.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16)
  window.cancelAnimationFrame = (id) => clearTimeout(id)
</script>
<link rel="stylesheet" href="out/style.css">
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
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js', cssFileName: 'style' },
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
    folder = FRONTEND / f".harness-servercard-{uuid4().hex}"
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
                "--window-size=1000,1800", f"--remote-debugging-port={port}",
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


def _section(report: dict, title: str) -> dict:
    found = [section for section in report["sections"] if section["title"] == title]
    assert len(found) == 1, (title, [section["title"] for section in report["sections"]])
    return found[0]


def test_the_sheet_shows_its_sections(report):
    # Without them every check below would compare nothing with nothing.
    assert [section["title"] for section in report["sections"]] == [
        "Module", "Speicher", "Netzwerk", "Erweitert",
    ]


def test_the_memory_head_wears_the_chip_with_the_bolt(report):
    sign = _section(report, "Speicher")["sign"]
    assert sign and sign["view"] == "0 0 64 64"
    assert sign["rects"] == 1 and sign["circles"] == 0
    assert "M35 21 L27 33 H37 L29 43" in sign["paths"]


def test_the_network_head_wears_the_chip_with_the_network(report):
    sign = _section(report, "Netzwerk")["sign"]
    assert sign and sign["view"] == "0 0 64 64"
    assert sign["rects"] == 1 and sign["circles"] == 3
    assert "M30 27.5 L25 36.5 M34 27.5 L39 36.5 M26.5 40 H37.5" in sign["paths"]


def test_the_angle_of_the_folding_head_is_14_px(report):
    angle = _section(report, "Erweitert")["angle"]
    assert angle and abs(angle["width"] - 14) <= 0.5 and abs(angle["height"] - 14) <= 0.5, angle
    # Only a folding head has one.
    assert _section(report, "Speicher")["angle"] is None


def test_the_wired_memory_row_writes_both_numbers_with_the_decimal_sign_of_the_language(report):
    assert report["estimate"] == "7,5 GB von 60,8 GB"
    # Under 1 GB two digits, as everywhere else a size is written.
    assert report["smallEstimate"] == "0,50 GB von 60,8 GB"


def test_the_folder_buttons_in_a_card_are_34_px_and_their_row_is_56_high(report):
    card = report["incard"]
    assert card["path"] == "/data/models", card
    assert len(card["buttons"]) == 2
    for button in card["buttons"]:
        assert abs(button["width"] - 34) <= 0.5 and abs(button["height"] - 34) <= 0.5, button
    assert abs(card["row"]["height"] - 56) <= 0.5, card["row"]


def test_silence_a_folder_row_outside_a_card_keeps_its_30_px_buttons(report):
    outside = report["outside"]
    assert outside["path"] == "/data/models", outside
    assert len(outside["buttons"]) == 2
    for button in outside["buttons"]:
        assert abs(button["width"] - 30) <= 0.5 and abs(button["height"] - 30) <= 0.5, button
