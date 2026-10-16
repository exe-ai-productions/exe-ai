"""The real model and agent server windows in headless Chrome, with only the
service's answers replaced.

The windows are built as they ship (Vite, from the sources under
``frontend/src``); ``lib/api.js`` is swapped for a stand-in that keeps the
stored settings in the page and lists every call with its order. A case is a
piece of script that opens and closes the windows, types, clicks and writes
what it saw into ``#ergebnis``; ``run_cases`` hands that back as a dict.

Skipped by the callers where there is no Chrome or no node.
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

BROWSER_TESTS_POSSIBLE = shutil.which("node") is not None and (
    FRONTEND / "node_modules" / "vite"
).exists()

SHELL = """<script>
  import Modellserver from '../../src/teile/Modellserver.svelte'
  import Agentserver from '../../src/teile/Agentserver.svelte'
  import { scene } from './scene.svelte.js'
</script>

<div style="width: 1100px; margin: 0 auto;">
  {#if scene.show === 'modell'}<Modellserver />{/if}
  {#if scene.show === 'agent'}<Agentserver />{/if}
</div>
"""

SCENE_JS = "export const scene = $state({ show: null })\n"

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import '../../src/stil/global.css'

window.scene = scene
mount(Shell, { target: document.getElementById('root') })
"""

# The service's answers, kept in the page: the stored settings (a set of
# values per key) and the list of calls with their order. Anything not
# listed answers with an empty set.
API_STUB = r"""const stub = (window.__stub = {
  settings: {
    runnermodell: {},
    agentenmodell: { sorte: 'slot', wert: 'a.gguf' },
    feineinstellungen: {},
  },
  calls: [],
  running: { chat: false, agent: false },
  runFein: null,
})
const copy = (value) => JSON.parse(JSON.stringify(value))
const program = { programm: '/bin/llama-server', version: 'b1', updatable: false, restorable: false }
const files = [{ name: 'a.gguf', groesse_gb: 2 }, { name: 'b.gguf', groesse_gb: 3 }]
const auskunft = (which) => ({
  ...program,
  ordner: '/m',
  modelle: files,
  mmproj: ['a-mmproj-f16.gguf'],
  projector_size_gb: { 'a-mmproj-f16.gguf': 0.6 },
  mtp: [],
  speicher_gb: 32,
  kerne: 8,
  belegt_gb: null,
  laeuft: stub.running[which],
  modell: stub.running[which] ? 'a.gguf' : null,
  kontext: stub.running[which] ? 8192 : null,
  schichten: stub.running[which] ? 99 : null,
  port: which === 'chat' ? 8080 : 8083,
  drafter: null,
  vision: null,
  fein: stub.running[which] ? copy(stub.runFein) : null,
  flash_aktiv: null,
  mtp_aktiv: null,
  unknown_architecture: null,
  zuordnung: { 'a.gguf': { mmproj: 'a-mmproj-f16.gguf', mtp: null } },
  vorgaben: { kontext: 16384, schichten: 99, port: null, vorladen: true },
  vorgabe: 'a.gguf',
})
const methods = {
  runnerAuskunft: async () => auskunft('chat'),
  agentenmodellAuskunft: async () => auskunft('agent'),
  runnerProtokoll: async () => [],
  agentenmodellProtokoll: async () => [],
  einstellungAufgeloest: async (key) => ({ wert: copy(stub.settings[key] || {}), herkunft: {} }),
  einstellungMischen: async (scope, key, values) => {
    stub.calls.push({ name: 'patch', key, values: copy(values), at: performance.now() })
    await new Promise((done) => setTimeout(done, 40))
    const row = stub.settings[key] || (stub.settings[key] = {})
    for (const [name, value] of Object.entries(values)) {
      if (value === null) delete row[name]
      else if (value && typeof value === 'object' && !Array.isArray(value)) {
        row[name] = { ...(row[name] || {}), ...copy(value) }
      } else row[name] = value
    }
    return { wert: copy(row) }
  },
  einstellungSetzen: async (scope, key, value) => {
    stub.calls.push({ name: 'put', key, values: copy(value), at: performance.now() })
    await new Promise((done) => setTimeout(done, 40))
    stub.settings[key] = copy(value)
    return { wert: copy(value) }
  },
  runnerStarten: async (values) => {
    stub.calls.push({ name: 'start', server: 'chat', values: copy(values) })
    stub.running.chat = true
    return auskunft('chat')
  },
  agentenmodellStarten: async (file) => {
    stub.calls.push({ name: 'start', server: 'agent', file })
    stub.running.agent = true
    return auskunft('agent')
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
            await asyncio.sleep(0.25)
    return ""


def run_cases(cases_js: str) -> dict:
    """Builds the two windows, runs ``cases_js`` in a page that has ``scene``
    and ``window.__stub``, and returns what it wrote to ``#ergebnis``."""
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-modelwindows-{uuid4().hex}"
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
        page.write_text(PAGE % {"cases": "const { scene } = window;\n" + cases_js}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1200,1400", f"--remote-debugging-port={port}",
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
