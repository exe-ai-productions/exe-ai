"""The sidebar opens 285 px wide and the seam does not go narrower, in a real
browser.

The drawing's sidebar is 285 px wide: the five 40 px signs at its foot stand
12 px from either edge, a little over 15 px apart, and none of them has to
shrink. The default and the lowest width the seam takes were 314 px, so the
sidebar opened wider than drawn and could not be dragged to the drawn width.
Now both are 285. A width stored earlier stays as it is (314 and 340 keep
their width); one above 400 comes back as 400.

`App.svelte` is built as shipped and drawn in headless Chrome with the global
stylesheet; the service is not asked: the page answers every request itself,
with empty lists, so there is no stored layout (the sidebar starts folded
then, and the test unfolds it). Skipped where there is no
Chrome or no node, like the other browser tests.
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
import { zustand, seitenBreiteSetzen, seitenleisteAnwenden } from '../../src/lib/zustand.svelte.js'

texte.katalog = german
texte.sprache = 'de'
window.__zustand = zustand
window.__api = { seitenBreiteSetzen, seitenleisteAnwenden }
const LISTS = ['/models', '/agents', '/skills', '/jobs', '/cronjobs', '/chats', '/projects', '/endpoints']
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = LISTS.includes(path) ? [] : path === '/runner' ? { speicher_gb: 64, modelle: [], mmproj: [], mtp: [] } : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
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
const rect = (node) => {
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
const zustand = window.__zustand
const api = window.__api
for (let k = 0; k < 150 && !document.querySelector('.seitenleiste .fensterzeile button'); k += 1) await wait(100)
await wait(1000)

const side = () => document.querySelector('.seitenleiste')
const measure = async () => {
  await wait(500)
  const aside = side()
  const row = aside.querySelector('.fensterzeile')
  const signs = Array.from(row.querySelectorAll('button')).map(rect)
  const asideBox = rect(aside)
  const rowBox = rect(row)
  const head = aside.querySelector('.markenkopf')
  return {
    stored: zustand.seitenBreite,
    width: asideBox.width,
    signs: signs.map((s) => ({ left: s.x - asideBox.x, width: s.width, height: s.height, right: asideBox.right - s.right })),
    rowOverflows: row.scrollWidth > row.clientWidth,
    asideOverflows: aside.scrollWidth > aside.clientWidth,
    headOverflows: head ? head.scrollWidth > head.clientWidth : null,
    rowRight: rowBox.right - asideBox.right,
  }
}

// A fresh installation starts with the sidebar folded: open it, as the click on its sign does.
zustand.seitenleisteEingeklappt = false
report.start = await measure()
api.seitenBreiteSetzen(200)
report.dragged200 = await measure()
api.seitenleisteAnwenden({ seitenleiste_zu: false, seitenleiste_breite: 250 })
report.applied250 = await measure()
api.seitenleisteAnwenden({ seitenleiste_zu: false, seitenleiste_breite: 314 })
report.applied314 = await measure()
api.seitenBreiteSetzen(340)
report.dragged340 = await measure()
api.seitenBreiteSetzen(600)
report.dragged600 = await measure()
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: @@WIDTH@@px; height: @@HEIGHT@@px; position: relative; }</style>
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


def _run_case(width: int, height: int) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-sidebar-285-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        entry = ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
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
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", CASES).replace("@@WIDTH@@", str(width)).replace("@@HEIGHT@@", str(height)), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                f"--window-size={width},{height}",
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
def report() -> dict:
    return _run_case(1920, 1080)


def test_the_sidebar_opens_285_wide_with_its_five_signs_in_full_size(report):
    start = report["start"]
    assert start["width"] == 285 and start["stored"] == 285, start
    assert len(start["signs"]) == 5, start
    for sign in start["signs"]:
        assert abs(sign["width"] - 40) <= 0.5 and abs(sign["height"] - 40) <= 0.5, sign
    assert abs(start["signs"][0]["left"] - 12) <= 0.5, start
    assert abs(start["signs"][-1]["right"] - 12) <= 0.5, start


def test_nothing_of_the_sidebar_runs_over_at_285(report):
    start = report["start"]
    assert not start["rowOverflows"] and not start["asideOverflows"], start
    assert not start["headOverflows"], start
    assert start["rowRight"] <= 0.5, start


def test_the_seam_does_not_go_narrower_than_285(report):
    assert report["dragged200"]["width"] == 285 and report["dragged200"]["stored"] == 285, report["dragged200"]


def test_a_width_arriving_from_the_service_is_clamped_to_285(report):
    assert report["applied250"]["width"] == 285 and report["applied250"]["stored"] == 285, report["applied250"]


def test_silence_a_width_stored_earlier_keeps_its_width(report):
    assert report["applied314"]["width"] == 314 and report["applied314"]["stored"] == 314, report["applied314"]
    assert report["dragged340"]["width"] == 340, report["dragged340"]


def test_silence_the_sidebar_stays_at_most_400_wide(report):
    assert report["dragged600"]["width"] == 400 and report["dragged600"]["stored"] == 400, report["dragged600"]


def test_silence_the_signs_keep_their_size_at_every_width(report):
    for name in ("start", "dragged200", "applied250", "applied314", "dragged340", "dragged600"):
        for sign in report[name]["signs"]:
            assert abs(sign["width"] - 40) <= 0.5 and abs(sign["height"] - 40) <= 0.5, (name, sign)
