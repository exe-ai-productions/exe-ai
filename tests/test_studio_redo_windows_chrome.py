"""In the picture studio Ctrl+Y steps forward on Windows only, measured in a real browser.

`StudioCanvas.svelte` is built as shipped and drawn in headless Chrome at
1920 x 1080 with the answers of the service made up in the page and a
picture standing in the area. The platform of the browser is set before the
page loads, once to Windows and once to a Mac. A stroke is painted with the
brush; Ctrl+Z takes it away and the forward step becomes available; Ctrl+Y
brings it back on Windows and does nothing on a Mac, where Ctrl+Shift+Z is
the key on both systems. Ctrl+Y typed into a field of the studio stays with
the field. The steps are read from the rail: the two buttons are enabled
exactly when there is a step to take.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import socket
import struct
import subprocess
import time
import urllib.request
import zlib
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


def _picture() -> str:
    """A plain 64 x 64 picture as an address of its own, so the area has a
    picture to paint on without the service."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\xcc\xcc\xcc" * 64 for _ in range(64))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode()


SHELL = """<script>
  import StudioCanvas from '../../src/teile/StudioCanvas.svelte'
</script>

<div id="frame" style="width: 1400px; height: 900px; position: relative; display: flex;">
  <StudioCanvas />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { texte, t } from %(texts)r
import { api } from %(api)r
import { studio, werte, surface } from %(studio)r

texte.sprache = 'en'
texte.katalog = english
api.bildAdresse = () => %(picture)r
window.fetch = async () =>
  new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
// A synthetic pointer has no capture to take; the surface asks for it.
Element.prototype.setPointerCapture = () => {}
Element.prototype.hasPointerCapture = () => true
Element.prototype.releasePointerCapture = () => {}
window.__studio = { studio, werte, surface, t }
studio.offen = true
werte.startbild = 'a-picture.png'
mount(Shell, { target: document.getElementById('wurzel') })
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
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { surface, t } = window.__studio
const os = new URLSearchParams(location.search).get('os')
const stage = () => document.querySelector('.buehne')
const button = (key) => document.querySelector(`.werkzeuge button[aria-label="${t(key)}"]`)
for (let k = 0; k < 100 && !(stage() && document.querySelector('.bild img')?.naturalWidth); k += 1) await wait(100)
await wait(500)

const report = { os, platform: navigator.platform, agent: navigator.userAgentData?.platform }
const steps = () => ({ back: !button('maske.zurueck').disabled, forward: !button('maske.vor').disabled })
const press = async (key, modifiers, target = document.body) => {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...modifiers }))
  await wait(120)
}

// The brush, the mask switched on, one stroke across the picture.
button('maske.pinsel').click()
surface.maskOn = true
await wait(200)
const box = stage().getBoundingClientRect()
const at = (x, y, type) => stage().dispatchEvent(new PointerEvent(type, {
  bubbles: true, button: 0, pointerId: 7, clientX: box.left + x, clientY: box.top + y,
}))
at(box.width / 2 - 20, box.height / 2, 'pointerdown')
at(box.width / 2, box.height / 2, 'pointermove')
at(box.width / 2 + 20, box.height / 2, 'pointermove')
at(box.width / 2 + 20, box.height / 2, 'pointerup')
await wait(300)
report.painted = steps()

await press('z', { ctrlKey: true })
report.afterCtrlZ = steps()

// Typed into a field of the studio, the key is the field's.
const field = document.createElement('input')
document.body.appendChild(field)
await press('y', { ctrlKey: true }, field)
report.inField = steps()
field.remove()

await press('y', { metaKey: true })
report.afterCmdY = steps()

await press('y', { ctrlKey: true })
report.afterCtrlY = steps()

await press('z', { ctrlKey: true })
report.backAgain = steps()
await press('z', { ctrlKey: true, shiftKey: true })
report.afterCtrlShiftZ = steps()

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1920px; position: relative; }</style>
<script>
  // The platform the page believes it runs on, before anything reads it.
  const windows = new URLSearchParams(location.search).get('os') === 'windows'
  Object.defineProperty(navigator, 'userAgentData', {
    get: () => ({ platform: windows ? 'Windows' : 'macOS' }), configurable: true,
  })
  Object.defineProperty(navigator, 'platform', {
    get: () => (windows ? 'Win32' : 'MacIntel'), configurable: true,
  })
</script>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
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
</body></html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 150.0) -> dict:
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
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


def _run_case(system: str) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-studio-redo-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "texts": "../../src/lib/texte.svelte.js",
                "api": "../../src/lib/api.js",
                "studio": "../../src/lib/studio.svelte.js",
                "picture": _picture(),
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        sheets = sorted((folder / "out").glob("*.css"))
        assert sheets, "the build emitted no stylesheet"
        (folder / "measure.html").write_text(
            PAGE.replace("out/style.css", f"out/{sheets[0].name}") % {"cases": CASES},
            encoding="utf-8",
        )
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1920,1080",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri() + f"?os={system}",
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
def windows() -> dict:
    return _run_case("windows")


@pytest.fixture(scope="module")
def mac() -> dict:
    return _run_case("mac")


def test_the_platform_the_page_runs_on_is_the_one_that_was_set(windows, mac):
    assert (windows["platform"], windows["agent"]) == ("Win32", "Windows"), windows
    assert (mac["platform"], mac["agent"]) == ("MacIntel", "macOS"), mac


def test_a_stroke_can_be_stepped_back_and_forward_with_ctrl_z_and_ctrl_y_on_windows(windows):
    assert windows["painted"] == {"back": True, "forward": False}, windows
    assert windows["afterCtrlZ"] == {"back": False, "forward": True}, windows
    assert windows["afterCtrlY"] == {"back": True, "forward": False}, windows


def test_ctrl_y_in_a_field_of_the_studio_stays_with_the_field(windows):
    assert windows["inField"] == {"back": False, "forward": True}, windows


def test_silence_on_a_mac_ctrl_y_and_cmd_y_do_nothing_and_ctrl_shift_z_steps_forward(mac):
    assert mac["painted"] == {"back": True, "forward": False}, mac
    assert mac["afterCtrlZ"] == {"back": False, "forward": True}, mac
    assert mac["afterCmdY"] == {"back": False, "forward": True}, mac
    assert mac["afterCtrlY"] == {"back": False, "forward": True}, mac
    assert mac["backAgain"] == {"back": False, "forward": True}, mac
    assert mac["afterCtrlShiftZ"] == {"back": True, "forward": False}, mac


def test_silence_on_windows_ctrl_shift_z_still_steps_forward(windows):
    assert windows["afterCtrlShiftZ"] == {"back": True, "forward": False}, windows
