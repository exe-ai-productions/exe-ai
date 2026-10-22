"""The names of the picker rows on the server pages stand whole in a narrow window.

``App.svelte`` is built as shipped and drawn in headless Chrome with the
global stylesheet; the service is not asked, the page answers every request
itself. The window is resized through the debug port and each picker row of
the open page is read: its name, its picker, its card.

* Where the name and the picker do not both fit in the line, the picker
  stands under the name, as wide as the row, and stays inside its card; the
  name stands whole.
* Where both fit, the row is as it was: the picker 232 wide beside the name.
* Only a name that does not fit even alone ends in an ellipsis; the speech
  server's picker names carry it whole as their tooltip.
* Silence: rows with a number field, a switch or a button do not wrap, and
  two cards side by side stay equally tall.

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
const files = [{ name: 'a.gguf', groesse_gb: 2 }, { name: 'b.gguf', groesse_gb: 3 }]
const server = (port) => ({
  programm: '/bin/llama-server', version: 'b1', updatable: false, restorable: false,
  ordner: '/m', modelle: files, mmproj: [], projector_size_gb: {}, mtp: [], speicher_gb: 32, kerne: 8,
  belegt_gb: null, laeuft: false, modell: null, kontext: null, schichten: null, port,
  drafter: null, vision: null, fein: null, flash_aktiv: null, mtp_aktiv: null, unknown_architecture: null,
  zuordnung: {}, vorgaben: { kontext: 16384, schichten: 99, port: null, vorladen: true }, vorgabe: 'a.gguf',
})
const speech = {
  ...server(8794), programm: '/bin/whisper-server', modelle: [{ name: 'speech.bin', groesse_gb: 1.5 }],
  projektoren: [], stimmproben: [], stimmproben_dauer: 0,
  diktat_vorgaben: {
    sprache: 'auto', bereinigung: 'aus', anweisung: 'WORKS DICTATION', bereinigung_anweisung: 'WORKS CLEANUP',
    gespraechsanweisung: 'WORKS CONVERSATION', automatik: false, vorlesen: true, keep_model_in_memory: false,
  },
}
const picture = {
  programm_da: true, restorable: false, modelle: ['base.safetensors'], ab_werk: { sdxl: 'WORKS PICTURE' },
  anweisungen: {}, verbesserer: '', bildfamilie: 'sdxl', familien: ['sdxl'],
}
const answers = {
  '/runner': server(8080), '/agentenmodell': server(8083), '/einbettungsserver': { ...server(8081), pooling: '' },
  '/bereinigungsserver': server(8795), '/sprachserver': speech, '/bild/modelle': picture,
  '/system/speicher': { wired_limit_gb: 20, gesamt_gb: 32 }, '/models': [],
  '/speicherorte': [], '/chats': [],
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : path.endsWith('/log') ? [] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
window.__zustand = zustand
window.__texte = texte
window.__german = german
window.__open = (name) => {
  zustand.lokalWunsch = name
  seiteZeigen('lokal')
}
window.__measure = () => {
  const text = (node) => node.textContent.replace(/\\s+/g, ' ').trim()
  const rows = [...document.querySelectorAll('section.abschnitt .karte > .zeile')]
  const choice = rows.filter((row) => row.querySelector(':scope > .wahl') && row.querySelector(':scope > .name'))
  return {
    width: window.innerWidth,
    pickers: choice.map((row) => {
      const name = row.querySelector(':scope > .name')
      const wahl = row.querySelector(':scope > .wahl')
      const card = row.parentElement
      const n = name.getBoundingClientRect(), w = wahl.getBoundingClientRect(), k = card.getBoundingClientRect()
      return {
        text: text(name), title: name.getAttribute('title'),
        clipped: name.scrollWidth > name.clientWidth + 0.5,
        stacked: w.top >= n.bottom - 1,
        pickerWidth: w.width, pickerLeft: w.left, pickerRight: w.right,
        cardLeft: k.left, cardRight: k.right, nameWidth: n.width,
      }
    }),
    // The row of the backend: a text field in the place of a picker.
    backend: (() => {
      const row = rows.find((r) => r.querySelector(':scope > .name')?.textContent.trim().startsWith('Backend'))
      if (!row) return null
      const name = row.querySelector(':scope > .name')
      const field = row.querySelector('input')
      const n = name.getBoundingClientRect(), f = field.getBoundingClientRect(), k = row.parentElement.getBoundingClientRect()
      return {
        clipped: name.scrollWidth > name.clientWidth + 0.5,
        stacked: f.top >= n.bottom - 1,
        fieldWidth: f.width, fieldLeft: f.left, fieldRight: f.right, cardLeft: k.left, cardRight: k.right,
        value: field.value,
      }
    })(),
    wrapping: rows.filter((row) => !row.querySelector(':scope > .wahl') && getComputedStyle(row).flexWrap !== 'nowrap').length,
    // The last card of each of the two columns of every row of the window.
    columns: [...document.querySelectorAll('.reihe')].map((reihe) => (
      [...reihe.querySelectorAll(':scope > .spalte')].map((column) => {
        const cards = column.querySelectorAll('.karte')
        return cards.length ? Math.round(cards[cards.length - 1].getBoundingClientRect().bottom) : null
      })
    )),
  }
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

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { position: fixed; inset: 0; }</style>
</head><body>
<div id="wurzel"></div>
<script src="out/entry.js"></script>
</body></html>
"""

LONG_NAME = "Ein sehr langer Name einer Auswahlzeile, der auch allein nicht in die Zeile einer schmalen Karte passt, ganz sicher nicht"

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Page:
    def __init__(self, connection):
        self.connection = connection
        self.number = 0

    async def call(self, method: str, params: dict | None = None):
        self.number += 1
        await self.connection.send(json.dumps({"id": self.number, "method": method, "params": params or {}}))
        while True:
            response = json.loads(await self.connection.recv())
            if response.get("id") == self.number:
                return response

    async def value(self, expression: str):
        response = await self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        result = response.get("result", {})
        assert "exceptionDetails" not in result, str(result["exceptionDetails"])[:800]
        return result.get("result", {}).get("value")

    async def resize(self, width: int, height: int) -> None:
        await self.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
        })
        await asyncio.sleep(0.35)


async def _sweep(port: int) -> dict:
    websockets = pytest.importorskip("websockets")
    end = time.monotonic() + 240
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
    out: dict = {"sweep": {}, "long": {}, "pages": {}}
    async with websockets.connect(address, max_size=32 * 1024 * 1024) as connection:
        page = _Page(connection)
        for _ in range(100):
            if await page.value("Boolean(document.querySelector('.chatkopf'))"):
                break
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.6)

        async def open_page(name: str, marker: str) -> None:
            await page.value(f"window.__open('{name}')")
            for _ in range(100):
                if await page.value(f"Boolean([...document.querySelectorAll('section.abschnitt .kopf')].some((h) => h.textContent.includes('{marker}')))"):
                    break
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.8)

        await page.resize(1000, 750)
        await open_page("sprache", "Diktat")
        for width, height in [(720, 600), (800, 600), (1000, 750), (1920, 1080)]:
            await page.resize(width, height)
            out["sweep"][f"sprache-{width}"] = await page.value("window.__measure()")
        for width in range(720, 1921, 20):
            await page.resize(width, 800)
            out["sweep"][f"sprache-w{width}"] = await page.value("window.__measure()")
        # A name that does not fit even alone.
        await page.resize(1000, 750)
        await page.value(
            "window.__texte.katalog = { ...window.__german, sprachserver: "
        "{ ...window.__german.sprachserver, feld_sprache: " + json.dumps(LONG_NAME) + " } }"
        )
        await asyncio.sleep(0.5)
        out["long"] = await page.value("window.__measure()")
        await page.value("window.__texte.katalog = window.__german")
        await asyncio.sleep(0.3)

        await page.resize(1000, 750)
        await open_page("bild", "Aufbereitung")
        await page.resize(1000, 750)
        out["sweep"]["bild-1000"] = await page.value("window.__measure()")
        await page.resize(800, 600)
        out["sweep"]["bild-800"] = await page.value("window.__measure()")
        await page.resize(1000, 750)
        for width in range(720, 1921, 20):
            await page.resize(width, 800)
            out["sweep"][f"bild-w{width}"] = await page.value("window.__measure()")
        for name, marker in [("server", "Speicher"), ("agent", "Speicher"), ("einbettung", "Speicher"), ("bereinigung", "Speicher")]:
            await page.resize(1000, 750)
            await open_page(name, marker)
            out["pages"][name] = await page.value("window.__measure()")
    return out


@pytest.fixture(scope="module")
def measured() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-server-rows-{uuid4().hex}"
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
        (folder / "measure.html").write_text(PAGE, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1280,800", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return asyncio.run(_sweep(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _row(measured_at: dict, name: str) -> dict:
    return next(row for row in measured_at["pickers"] if row["text"] == name)


def _inside_card(row: dict) -> bool:
    return row["pickerLeft"] >= row["cardLeft"] - 0.5 and row["pickerRight"] <= row["cardRight"] + 0.5


def test_in_a_narrow_window_the_names_stand_whole_and_the_picker_under_them(measured):
    at = measured["sweep"]["sprache-1000"]
    for name in ("Gesprochene Sprache", "Bereinigt durch"):
        row = _row(at, name)
        assert row["clipped"] is False, name
        assert row["stacked"] is True, name
        assert _inside_card(row), name
        # Under its name the picker is as wide as the row.
        assert row["pickerWidth"] > 232, name


def test_in_the_window_of_one_column_names_stand_whole_and_pickers_stay_in_their_cards(measured):
    for row in measured["sweep"]["sprache-800"]["pickers"]:
        assert row["clipped"] is False, row["text"]
        assert _inside_card(row), row["text"]


@pytest.mark.parametrize("size", ["sprache-720", "sprache-1920"])
def test_where_name_and_picker_fit_beside_each_other_the_row_is_as_it_was(measured, size):
    for row in measured["sweep"][size]["pickers"]:
        assert row["stacked"] is False, (size, row["text"])
        assert row["clipped"] is False, (size, row["text"])
        assert abs(row["pickerWidth"] - 232) <= 1, (size, row["text"], row["pickerWidth"])


def test_from_720_to_1920_no_picker_name_is_cut_and_no_picker_leaves_its_card(measured):
    seen = 0
    for key, at in measured["sweep"].items():
        if "-w" not in key:
            continue
        for row in at["pickers"]:
            seen += 1
            assert row["clipped"] is False, (key, row["text"])
            assert _inside_card(row), (key, row["text"])
    assert seen > 100


def test_a_name_that_does_not_fit_even_alone_ends_in_an_ellipsis_and_carries_itself_as_its_tooltip(measured):
    row = _row(measured["long"], LONG_NAME)
    assert row["clipped"] is True
    assert row["title"] == LONG_NAME
    assert row["stacked"] is True and _inside_card(row)


def test_the_speech_servers_picker_names_carry_themselves_as_their_tooltip(measured):
    for name in ("Gesprochene Sprache", "Bereinigt durch", "Sprache"):
        assert _row(measured["sweep"]["sprache-1000"], name)["title"] == name


def test_the_picture_servers_preparation_names_stand_whole(measured):
    at = measured["sweep"]["bild-1000"]
    for name in ("Verbessert von", "Bildfamilie"):
        row = _row(at, name)
        assert row["clipped"] is False and row["stacked"] is True and _inside_card(row), name


def test_the_other_server_pages_cut_no_picker_name(measured):
    for page, at in measured["pages"].items():
        for row in at["pickers"]:
            assert row["clipped"] is False, (page, row["text"])
            assert _inside_card(row), (page, row["text"])
    assert measured["pages"]["server"]["pickers"], "the chat server's picker rows were drawn"


def test_silence_rows_without_a_picker_do_not_wrap_and_cards_side_by_side_are_equally_tall(measured):
    for key, at in measured["sweep"].items():
        assert at["wrapping"] == 0, key
    # The conversation row of the speech server and every row of the picture
    # server and of the model servers end on one line.
    for key in ("sprache-1920", "sprache-1000"):
        left, right = measured["sweep"][key]["columns"][-1]
        assert abs(left - right) <= 1, (key, left, right)
    levels = measured["sweep"]["bild-1000"]["columns"] + [
        row for page in ("server", "agent", "einbettung") for row in measured["pages"][page]["columns"]
    ]
    assert levels
    for left, right in levels:
        assert abs(left - right) <= 1, (left, right)


def test_the_backend_name_stands_whole_and_its_field_under_it_in_a_narrow_window(measured):
    row = measured["sweep"]["bild-1000"]["backend"]
    assert row is not None, "the page has a row Backend"
    assert row["clipped"] is False
    assert row["stacked"] is True
    assert row["fieldLeft"] >= row["cardLeft"] - 0.5 and row["fieldRight"] <= row["cardRight"] + 0.5
    # Under its name the field is as wide as the row.
    assert row["fieldWidth"] > 232


@pytest.mark.parametrize("key", ["bild-w720", "bild-w1920"])
def test_where_the_backend_name_and_its_field_fit_beside_each_other_the_row_is_as_it_was(measured, key):
    row = measured["sweep"][key]["backend"]
    assert row["stacked"] is False and row["clipped"] is False, key
    assert abs(row["fieldWidth"] - 232) <= 1, (key, row["fieldWidth"])
    assert row["value"] in ("", "-"), key


def test_from_720_to_1920_the_backend_name_is_never_cut_and_its_field_stays_in_the_card(measured):
    seen = 0
    for key, at in measured["sweep"].items():
        if not key.startswith("bild-w"):
            continue
        row = at["backend"]
        seen += 1
        assert row["clipped"] is False, key
        assert row["fieldLeft"] >= row["cardLeft"] - 0.5 and row["fieldRight"] <= row["cardRight"] + 0.5, key
    assert seen > 30
