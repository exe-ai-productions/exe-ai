"""The sidebar of the catalogue pages, measured in a real browser.

On the pages Catalogue and Downloads the sidebar carries the list of the
settings — the component the local models and the server pages carry — with
the row of the open page chosen: "Downloads" while the downloads are open,
"Catalogue" otherwise, also in the detail of a model. The kinds of model and
"Downloads" with the number of what runs and waits stand in the left column of
the page, as before. A click on a row of the list switches the page by the
wish the page already reads.

`App.svelte` is built as shipped and drawn in headless Chrome with the global
stylesheet; the service is not asked — the page answers every request itself.
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
import { downloads } from '../../src/lib/downloads.svelte.js'

texte.katalog = german
texte.sprache = 'de'
const scenario = { stand: null }
window.__scenario = scenario
window.__zustand = zustand
window.__show = seiteZeigen
window.__downloads = downloads
window.fetch = async (address, options = {}) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  if (path === '/runner/download') return json(scenario.stand)
  if (path === '/runner') return json({ speicher_gb: 64, modelle: [], mmproj: [], mtp: [] })
  if (path === '/models/token') return json({ gesetzt: false })
  return json({})
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
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const zustand = window.__zustand
const rowsOf = (selector) => Array.from(document.querySelectorAll(selector)).map((b) => ({
  text: b.querySelector('.titel')?.textContent.trim() ?? b.textContent.trim(),
  full: b.textContent.trim().replace(/\s+/g, ' '),
  current: b.getAttribute('aria-current') === 'true',
}))
const probe = () => ({
  catalogue: zustand.katalogOffen === true,
  local: zustand.lokalOffen === true,
  sidebar: rowsOf('aside .menuezeile'),
  column: rowsOf('nav.kinds .menuezeile'),
  heading: document.querySelector('.vorauswahl span')?.textContent.trim() ?? null,
  detail: Boolean(document.querySelector('.detail')),
  sidebarSigns: Array.from(document.querySelectorAll('aside .menuezeile .zeichen svg')).length,
})
const clickSidebar = async (title) => {
  const row = Array.from(document.querySelectorAll('aside .menuezeile')).find((b) => b.querySelector('.titel')?.textContent.trim() === title)
  row?.click()
  await wait(900)
}
for (let k = 0; k < 100 && !document.querySelector('.chatkopf'); k += 1) await wait(100)
await wait(600)

window.__show('katalog')
await wait(900)
report.opened = probe()

await clickSidebar('Downloads')
report.downloads = probe()

await clickSidebar('Katalog')
report.catalogue = probe()

// The detail of a model: the row of the catalogue stays the chosen one.
document.querySelector('.raster .karte')?.click()
await wait(700)
report.detail = probe()

// The chosen row "Katalog" leaves the detail again.
await clickSidebar('Katalog')
report.leftDetail = probe()
document.querySelector('.raster .karte')?.click()
await wait(700)
report.detailAgain = probe()

await clickSidebar('Downloads')
report.fromDetailToDownloads = probe()

await clickSidebar('Lokale Modelle')
report.local = probe()
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; height: 700px; position: relative; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      @@CASES@@
    } catch (failure) {
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure) })
    }
  })
</script>
</body></html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 180.0) -> dict:
    """Read the page's report over the debug port."""
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

        async def value_of(expression: str):
            nonlocal number
            number += 1
            await connection.send(
                json.dumps({"id": number, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True}})
            )
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response.get("result", {}).get("result", {}).get("value")

        raw = ""
        while time.monotonic() < end and not raw:
            raw = await value_of("document.getElementById('ergebnis')?.textContent || ''")
            if not raw:
                await asyncio.sleep(0.5)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-catalog-list-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        entry = (
            ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
        )
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", CASES), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1280,700",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return asyncio.run(_drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def measured() -> dict:
    return _run_case()


def _chosen(rows: list[dict]) -> list[str]:
    return [row["text"] for row in rows if row["current"]]


KINDS = ["Chat", "Einbettung", "Sprache", "Bild", "Video", "Zubehör", "Downloads"]


def test_the_sidebar_of_the_catalogue_carries_the_settings_list_with_the_catalogue_chosen(measured):
    opened = measured["opened"]
    assert opened["catalogue"]
    titles = [row["text"] for row in opened["sidebar"]]
    # The list of the settings, as the local models carry it: its groups'
    # rows are all there, among them the two of this page.
    for row in ("Erscheinungsbild", "Anweisungen", "Lokale Modelle", "Cloud-Anbieter", "Katalog", "Downloads", "Hilfe"):
        assert row in titles, (row, titles)
    assert _chosen(opened["sidebar"]) == ["Katalog"]


def test_the_sidebar_has_no_kind_of_model_and_no_number_on_its_downloads_row(measured):
    opened = measured["opened"]
    titles = [row["text"] for row in opened["sidebar"]]
    # "Language" is a row of the settings as well; the kinds of the catalogue
    # are told apart by the rest of the list: Embedding, Picture, Accessories.
    for kind in ("Chat", "Einbettung", "Bild", "Video", "Zubehör"):
        assert kind not in titles, kind
    downloads = next(row for row in opened["sidebar"] if row["text"] == "Downloads")
    assert downloads["full"] == "Downloads"


def test_the_left_column_of_the_page_keeps_the_kinds_and_the_downloads(measured):
    opened = measured["opened"]
    assert [row["text"] for row in opened["column"]] == KINDS
    assert _chosen(opened["column"]) == ["Chat"]
    assert opened["heading"] == "Vorauswahl an Chatmodellen"


def test_a_click_on_downloads_in_the_sidebar_shows_the_downloads_page(measured):
    page = measured["downloads"]
    assert page["catalogue"] and page["heading"] == "Downloads"
    assert _chosen(page["sidebar"]) == ["Downloads"]
    assert _chosen(page["column"]) == ["Downloads"]


def test_a_click_on_the_catalogue_shows_the_preselection_of_chat_models_again(measured):
    page = measured["catalogue"]
    assert page["catalogue"] and page["heading"] == "Vorauswahl an Chatmodellen"
    assert _chosen(page["sidebar"]) == ["Katalog"]
    assert _chosen(page["column"]) == ["Chat"]


def test_the_catalogue_stays_the_chosen_row_in_the_detail_of_a_model(measured):
    page = measured["detail"]
    assert page["detail"], "the card did not open its detail"
    assert _chosen(page["sidebar"]) == ["Katalog"]
    # Clicking the chosen row leaves the detail for the preselection.
    left = measured["leftDetail"]
    assert not left["detail"] and left["heading"] == "Vorauswahl an Chatmodellen"
    assert measured["detailAgain"]["detail"], "the card did not open its detail again"
    # ... and from the detail the list still takes to the downloads.
    later = measured["fromDetailToDownloads"]
    assert later["heading"] == "Downloads" and _chosen(later["sidebar"]) == ["Downloads"]


def test_a_click_on_local_models_opens_that_page(measured):
    page = measured["local"]
    # The local page draws itself from answers of the service that this page
    # does not make up, so only that it is the page that opened is measured.
    assert page["local"] and not page["catalogue"]
