"""A page of the picture server's windows for the browser tests: the parts
that keep their settings (memory and devices, the prompt preparation, a
model's values) are built as shipped and stand on a stub of the service.

The stub answers what the real service answers for the settings these
parts read and write: a PATCH merges the sent values into what it holds and
checks them as ``app/bildgeraete.py`` does — a split or a budget it cannot
read comes back as "Auto"; a switch value it refuses leaves the stored one
standing, and one sent as unset is taken out. ``backend.calls`` lists every
write in order, ``backend.settings`` is what the service holds.

``run_cases`` builds the page once, runs the given script in headless
Chrome and returns what the script put into ``report``. Skipped where there
is no Chrome or no node.
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

needs_browser = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
    reason="no node or no frontend dependencies on this machine",
)

SHELL = """<script>
  import BildGeraete from '../../src/teile/BildGeraete.svelte'
  import Promptaufbereitung from '../../src/teile/Promptaufbereitung.svelte'
  import Bildmodellwerte from '../../src/teile/Bildmodellwerte.svelte'
  import Serverabschnitt from '../../src/teile/Serverabschnitt.svelte'
  import { scene } from './scene.svelte.js'

  // The generator's further switches stand in the sd.cpp section of the page, the idle time under it.
  let switchRows = $state.raw(null)
</script>

<div style="width: 760px; margin: 0 auto;">
  {#if scene.show === 'devices'}
    <BildGeraete onklappe={(parts) => (switchRows = parts)} />
    <Serverabschnitt zeichen="server" titel="sd.cpp">{@render switchRows?.schalter()}</Serverabschnitt>
    {@render switchRows?.erweitert()}
  {/if}
  {#if scene.show === 'preparation'}<Promptaufbereitung />{/if}
  {#if scene.show === 'values'}<Bildmodellwerte modell="model.safetensors" listen={{}} />{/if}
</div>
"""

SCENE_JS = "export const scene = $state({ show: '' })\n"

ENTRY_JS = r"""import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { meldungen } from '../../src/lib/meldewesen.svelte.js'
import '../../src/stil/global.css'

const unset = (value) => value === null || value === '' || value === undefined || value === false
const NUMBER = '-?\\d+(?:\\.\\d+)?'
const NAME = '[A-Za-z0-9_*-]+'
const VRAM = new RegExp('^(?:' + NUMBER + '|' + NAME + '=' + NUMBER + '(?:,' + NAME + '=' + NUMBER + ')*)$')
const SPLIT = new RegExp('^(?:(?:layer|row)|' + NAME + '=(?:layer|row)(?:,' + NAME + '=(?:layer|row))*)$')
const stripped = (value) => (typeof value === 'string' && value.length <= 500 ? value.replace(/\s+/g, '') : '')

/* What app/bildgeraete.py keeps of a sent value; one switch value is
   refused when its row does not take it (here: a whole number from 0 on). */
function checkedDevices(stored, sent) {
  const out = { ...stored }
  if ('vram_limit' in sent) out.vram_limit = VRAM.test(stripped(sent.vram_limit)) ? stripped(sent.vram_limit) : ''
  if ('offload_to_cpu' in sent) out.offload_to_cpu = sent.offload_to_cpu === true
  if ('threads' in sent) out.threads = Number.isInteger(sent.threads) && sent.threads > 0 ? sent.threads : -1
  if ('split_mode' in sent) out.split_mode = SPLIT.test(stripped(sent.split_mode)) ? stripped(sent.split_mode) : ''
  if ('backend' in sent) out.backend = stripped(sent.backend)
  if ('zeitgrenze' in sent) out.zeitgrenze = Number.isInteger(sent.zeitgrenze) && sent.zeitgrenze > 0 ? sent.zeitgrenze : null
  if ('idle_minutes' in sent) out.idle_minutes = Number.isInteger(sent.idle_minutes) && sent.idle_minutes > 0 ? sent.idle_minutes : null
  if ('switches' in sent) {
    const switches = { ...(stored.switches || {}) }
    for (const [key, value] of Object.entries(sent.switches)) {
      if (unset(value)) { delete switches[key]; continue }
      const good = key === 'conditioning_cache_size'
        ? Number.isInteger(value) && value >= 0
        : typeof value === 'string' && value.length <= 500
      if (good) switches[key] = value
      // a refused value leaves the stored one standing
    }
    out.switches = switches
  }
  return out
}

const backend = {
  settings: {
    bildgeraete: {
      vram_limit: '', offload_to_cpu: false, threads: -1, split_mode: '', backend: '',
      switches: {}, zeitgrenze: null,
    },
    bildaufbereitung: {},
    bildmodellwerte: {},
  },
  calls: [],
  delay: 0,
}
window.backend = backend

const SWITCH_TABLE = [{
  key: 'conditioning_cache_size', kind: 'int', group: 'memory', flag: '--conditioning-cache-size',
  low: 0, high: null, needs: null, video: null, choices: [], folder: null, machine: false,
}]
const PREPARATION = {
  verbesserer: 'agent', anweisungen: { sdxl: 'works text' }, ab_werk: { sdxl: 'works text' },
  leser: { clip: ['sdxl'] },
}
const PRESETS = {
  breite: 512, hoehe: 512, schritte: 20, cfg: 7, guidance: null, flow_shift: null,
  sampler: '', scheduler: '', clip_skip: null, prediction: '', trigger: '', hinweis: '',
  family: '', standalone: false, family_detection: true, parts: {}, eigene: [], sources: {},
  switches: {}, vae: '', video_frames: null, fps: null, vae_format: '', rng: '', model_args: '',
  diffusion_model: '',
}
const answer = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
})

window.fetch = async (address, options = {}) => {
  const path = String(address).replace(/^.*?\/api\/v1/, '').split('?')[0]
  const method = (options.method || 'GET').toUpperCase()
  if (method === 'PATCH' && path.startsWith('/settings/global/')) {
    const key = path.split('/').pop()
    const sent = JSON.parse(options.body).wert
    backend.calls.push({ key, sent: structuredClone(sent) })
    if (backend.delay) await new Promise((resolve) => setTimeout(resolve, backend.delay))
    const stored = backend.settings[key] || {}
    backend.settings[key] = key === 'bildgeraete' ? checkedDevices(stored, sent) : { ...stored, ...sent }
    return answer({ bereich: 'global', schluessel: key, wert: structuredClone(backend.settings[key]) })
  }
  if (path.startsWith('/settings/resolved/')) {
    const key = path.split('/').pop()
    return answer({ schluessel: key, wert: structuredClone(backend.settings[key] || {}), herkunft: {}, scope: null })
  }
  if (path === '/bild/devices') return answer([])
  if (path === '/bild/switches') return answer({ switches: SWITCH_TABLE, files: {}, weight_types: [] })
  if (path === '/bild/prompt/aufbereitung') return answer(PREPARATION)
  if (path === '/bild/vorgaben') return answer(PRESETS)
  return answer({})
}

window.scene = scene
window.notices = meldungen
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

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html, body { margin: 0; background: #2a2a28; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    const report = {}
    const wait = (ms) => new Promise((r) => setTimeout(r, ms))
    // Types into a field the way a person does: the value, then `input`.
    const typeInto = (node, value) => {
      const proto = node.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(node, value)
      node.dispatchEvent(new Event('input', { bubbles: true }))
    }
    const show = async (what) => { window.scene.show = what; await wait(400) }
    const backend = window.backend, scene = window.scene, notices = window.notices
    try {
      %(cases)s
      document.getElementById('ergebnis').textContent = JSON.stringify(report)
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


async def _read_result(port: int, limit: float) -> str:
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


def run_cases(cases: str, *, limit: float = 120.0, window: str = "900,1200") -> dict:
    """Build the page, run ``cases`` in it and return its ``report``.

    ``window`` is the size of the browser window, width and height; the rows
    of two columns stand side by side only above 900 px."""
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-image-windows-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE % {"cases": cases}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                f"--window-size={window}", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_read_result(port, limit))
        finally:
            prozessstopp.beenden(browser, frist=5)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report
    finally:
        shutil.rmtree(folder, ignore_errors=True)
