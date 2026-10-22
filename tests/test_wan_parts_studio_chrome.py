"""The studio shows the values of a Wan model's second, high-noise model only at
the models that take it, measured in a real browser.

``StudioBasics.svelte`` and ``StudioDetails.svelte`` are built as shipped and
drawn in headless Chrome with the picture service made up in the page: the
family table is the service's own, the switches are two rows of the group "Fine
tuning" for videos (one of them the high-noise steps) and the answer of the start
values names, per model, the parts it takes. A Wan 2.1 model → the fold of the
switches counts the one row that acts; a Wan 2.2 A14B model → it counts both.
A model of a family without the second model keeps the rows it had. Skipped
where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from uuid import uuid4

import pytest

from app import appfenster, image_families, prozessstopp
from tests import test_studio_generate_stays_chrome as page

FRONTEND = page.FRONTEND

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import StudioBasics from '../../src/teile/StudioBasics.svelte'
  import StudioDetails from '../../src/teile/StudioDetails.svelte'
</script>

<div id="frame" style="width: 800px; height: 1600px; position: relative; display: flex;">
  <div style="width: 340px; position: relative; overflow: hidden;"><StudioBasics /></div>
  <div style="width: 420px; position: relative; display: flex; flex-direction: column;"><StudioDetails /></div>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { werte, listen, auswahl, modelParts } from %(studio)r

const WAN_21 = 'wan2.1_t2v_1.3B_fp16.safetensors'
const WAN_21_I2V = 'wan2.1_i2v_14B_480p_fp16.safetensors'
const WAN_22 = 'wan2.2_t2v_low_noise_14B_fp16.safetensors'
const TAKEN = { [WAN_21]: [], [WAN_21_I2V]: ['clip_vision'], [WAN_22]: ['high_noise_diffusion_model'] }
const table = %(families)s
const switches = [
  { key: 'high_noise_steps', kind: 'int', group: 'tuning', needs: 'high_noise', video: true, flag: '--high-noise-steps' },
  { key: 'video_strength_x', kind: 'float', group: 'tuning', video: true, flag: '--video-strength' },
]
window.fetch = async (address) => {
  const url = new URL(String(address), location.href)
  const path = url.pathname.replace(/^.*?\\/api\\/v1/, '')
  let body = {}
  if (path === '/bild/modelle') {
    body = { programm_da: true, modelle: [WAN_21, WAN_21_I2V, WAN_22], standardmodell: WAN_21,
             families: {}, sampler: [], scheduler: [], loras: [], sizes: {} }
  } else if (path === '/bild/familien') {
    body = table
  } else if (path === '/bild/switches') {
    body = { switches, files: {}, weight_types: [] }
  } else if (path === '/bild/vorgaben') {
    const model = url.searchParams.get('modell')
    body = { family: 'wan', parts: {}, eigene: [], sources: {}, switches: {}, vae_format: '', rng: '',
             guidance: null, flow_shift: 5, scheduler: '', breite: 832, hoehe: 480, schritte: 20, cfg: 5,
             sampler: 'euler', sigmas: '', parts_taken: TAKEN[model] ?? [], needed_parts: [],
             standalone: true, bare: false }
  } else if (path === '/bilder') {
    body = { bilder: [] }
  } else if (path === '/settings/resolved/bildfenster') {
    body = { wert: { modell: WAN_21, prompt: 'a cat' } }
  }
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
window.__studio = { werte, listen, auswahl, modelParts }
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { werte, listen, auswahl, modelParts } = window.__studio
const row = (key) => document.querySelector(`.zeile[data-suche="${key}"]`)
for (let k = 0; k < 100 && !(listen.geladen && row('bild.modell')); k += 1) await wait(100)
await wait(1200)
auswahl.medium = 'video'
auswahl.art = 't2v'
await wait(500)

const chooseModel = async (name) => {
  row('bild.modell').querySelector('[role=combobox]').click()
  await wait(300)
  const option = Array.from(document.querySelectorAll('[role=option]'))
    .find((o) => o.textContent.replace(/\s+/g, ' ').trim().startsWith(name))
  option.click()
  await wait(900)
}
// The fold of the switches of "Fine tuning": how many rows it counts.
const counted = () => {
  const counter = document.querySelector('.klappe .zaehler')
  return counter ? counter.textContent.trim() : null
}
const report = {}
// "Fine tuning" is shut to begin with.
Array.from(document.querySelectorAll('button'))
  .find((b) => b.textContent.trim() === 'bild.gruppe_feintuning')?.click()
await wait(500)
for (const model of ['wan2.1_t2v', 'wan2.1_i2v', 'wan2.2_t2v']) {
  await chooseModel(model)
  report[model] = { counted: counted(), taken: modelParts.taken, family: auswahl.klasse }
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-wan-parts-studio-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css", "studio": "../../src/lib/studio.svelte.js",
                "families": json.dumps(image_families.as_json()),
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(page.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(page.PAGE % {"cases": CASES}, encoding="utf-8")
        port = page._free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking",
                "--allow-file-access-from-files", "--window-size=1000,1700",
                f"--remote-debugging-port={port}", f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return asyncio.run(page._drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_answer_of_the_service_reaches_the_studio(report):
    """Silence probe: the run reads what the model takes and the family it is of."""
    assert report["wan2.2_t2v"]["taken"] == ["high_noise_diffusion_model"], report
    assert report["wan2.1_t2v"]["taken"] == [] and report["wan2.1_t2v"]["family"] == "wan", report


def test_a_wan_2_1_model_shows_no_high_noise_values_in_the_studio(report):
    assert report["wan2.1_t2v"]["counted"] == "0/1", report["wan2.1_t2v"]
    assert report["wan2.1_i2v"]["counted"] == "0/1", report["wan2.1_i2v"]


def test_a_wan_2_2_a14b_model_keeps_its_high_noise_values_in_the_studio(report):
    assert report["wan2.2_t2v"]["counted"] == "0/2", report["wan2.2_t2v"]
