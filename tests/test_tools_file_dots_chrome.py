"""The dots of the tools file page, as drawn: a disc of 10 px in a box of 12 px.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome, with the
tools file made up in the page (the service is not asked): a faulty file with a
reason, and two servers that are at work. The page reports for the red dot in the
warning box and for the green dot before each server under "Live": the disc of
10 px in a box of 12 px, and the colour. And what stays: the sentence of the
warning box with its reason, and the names of the servers.

The build of the harness links the built stylesheet, so every colour probe reads
the real tokens.

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

REASON = "Invalid YAML: line 3"

SHELL = """<script>
  import SystemPrompt from %(page)r

  let { offen = true } = $props()
</script>

<div id="frame" style="width: 1100px; height: 800px; position: relative;">
  <SystemPrompt {offen} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { zustand } from %(zustand)r
import { texte } from %(texts)r

texte.sprache = 'en'
texte.katalog = english
const answers = {
  '/tools/config': { content: '{}', kaputt: %(reason)s, platzhalter: [] },
  '/tools': { aktiv: true, server: ['websearch', 'files'], werkzeuge: [] },
  '/dateien/zugangsdaten': { inhalt: 'KEY=value', kaputt: null },
  '/agents': [], '/agent-files': [], '/skills': [], '/cronjobs': [], '/jobs': [], '/werkzeuge': [],
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
zustand.promptOffen = true
zustand.promptStart = 'tools_datei'
window.__zustand = zustand
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
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const probe = (token, property = 'color') => {
  const node = document.createElement('i')
  node.style[property] = `var(${token})`
  document.body.appendChild(node)
  const value = getComputedStyle(node)[property]
  node.remove()
  return value
}
for (let k = 0; k < 80; k += 1) {
  await wait(100)
  if (document.querySelector('.warnung') && document.querySelectorAll('.lese .server').length === 2) break
  if (k === 79) throw new Error('the tools file page did not show its warning and its servers')
}
await wait(500)
const dotOf = (holder) => {
  const dot = holder.querySelector('svg.lp')
  const disc = dot.querySelector('circle.scheibe')
  return {
    box: [dot.getBoundingClientRect().width, dot.getBoundingClientRect().height],
    disc: Math.round(parseFloat(disc.getAttribute('r')) * 2),
    colour: dot.getAttribute('data-farbe'), fill: getComputedStyle(disc).fill,
  }
}
const warning = document.querySelector('.warnung')
report.warning = { ...dotOf(warning), text: warning.textContent.replace(/\s+/g, ' ').trim() }
report.servers = Array.from(document.querySelectorAll('.lese .server')).map((server) => ({
  ...dotOf(server), name: server.textContent.trim(),
}))
report.tokens = { red: probe('--rot'), green: probe('--gruen') }
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1100px; position: relative; }</style>
%(links)s
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
                response = json.loads(await asyncio.wait_for(connection.recv(), max(1.0, end - time.monotonic())))
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


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-tool-dots-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"page": "../../src/teile/SystemPrompt.svelte"}, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "texts": "../../src/lib/texte.svelte.js",
                "reason": json.dumps(REASON),
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
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        assert links, "the build emitted no stylesheet: the colour probes would measure nothing"
        (folder / "measure.html").write_text(PAGE % {"cases": CASES, "links": links}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1100,1200",
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


def test_the_dot_in_the_warning_box_is_a_disc_of_10_px_in_a_box_of_12_px(measured):
    warning = measured["warning"]
    assert warning["box"] == [12, 12] and warning["disc"] == 10, warning


def test_the_dot_before_a_server_is_a_disc_of_10_px_in_a_box_of_12_px(measured):
    assert len(measured["servers"]) == 2
    for server in measured["servers"]:
        assert server["box"] == [12, 12] and server["disc"] == 10, server


def test_silence_the_colours_stay_red_in_the_warning_box_and_green_at_the_servers(measured):
    tokens = measured["tokens"]
    warning = measured["warning"]
    assert warning["colour"] == "rot" and warning["fill"] == tokens["red"], warning
    for server in measured["servers"]:
        assert server["colour"] == "gruen" and server["fill"] == tokens["green"], server


def test_silence_the_sentence_with_its_reason_and_the_names_of_the_servers_stand_as_before(measured):
    assert measured["warning"]["text"] == "Invalid file: " + REASON, measured["warning"]["text"]
    assert [server["name"] for server in measured["servers"]] == ["websearch", "files"]
