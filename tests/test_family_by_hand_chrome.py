"""A family said by hand brings the start values of the model's variant,
measured in a real browser.

``StudioBasics.svelte`` and ``StudioDetails.svelte`` are built as shipped and
drawn in headless Chrome with the picture service made up in the page: the
table of families carries the family without a schedule, and the answer of the
start values carries the Turbo model's schedule only when the request names the
family by hand (``chosen_family``). A model whose header names no family and
a family said by hand → the 8 steps, the CFG of 1 and the nine numbers. A model
whose header names another family takes that family's values, and the family
said by hand goes. A model without a header family keeps the family said by
hand through a change of model, and is asked for again with it. Skipped where
there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_studio_generate_stays_chrome as page

FRONTEND = page.FRONTEND
SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"

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

<div id="frame" style="width: 800px; height: 1400px; position: relative; display: flex;">
  <div style="width: 340px; position: relative; overflow: hidden;"><StudioBasics /></div>
  <div style="width: 420px; position: relative; display: flex; flex-direction: column;"><StudioDetails /></div>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { werte, listen, auswahl, familieWaehlen } from %(studio)r

const TURBO = 'Qwen-Image-2.1-Turbo-Q4_K_M.gguf'
const OTHER = 'sd15-model.safetensors'
// The table the browser holds: the family without a schedule. The Turbo
// values reach the studio only through the answer of the service.
const table = [
  { name: 'qwen_image_2_1', label: 'Qwen-Image 2.1',
    start: { width: 1328, height: 1328, steps: 20, cfg: 4, sampler: 'euler', scheduler: '', sigmas: '', switches: {} } },
  { name: 'sd15', label: 'SD 1.5',
    start: { width: 512, height: 512, steps: 30, cfg: 7, sampler: 'euler_a', scheduler: '', sigmas: '', switches: {} } },
]
const asked = []
const answerFor = (model, chosen) => {
  const header = model === OTHER ? 'sd15' : ''
  const family = chosen || header
  const base = { family: header, parts: {}, eigene: [], sources: {}, switches: {}, vae_format: '', rng: '',
                 guidance: null, flow_shift: null, scheduler: '' }
  if (family === 'qwen_image_2_1') {
    return model === TURBO
      ? { ...base, breite: 2048, hoehe: 2048, schritte: 8, cfg: 1, sampler: 'euler', sigmas: %(sigmas)r }
      : { ...base, breite: 1328, hoehe: 1328, schritte: 20, cfg: 4, sampler: 'euler', sigmas: '' }
  }
  if (family === 'sd15') return { ...base, breite: 512, hoehe: 512, schritte: 30, cfg: 7, sampler: 'euler_a', sigmas: '' }
  return { ...base, breite: 512, hoehe: 512, schritte: 20, cfg: 7, sampler: 'euler', sigmas: '' }
}
window.fetch = async (address) => {
  const url = new URL(String(address), location.href)
  const path = url.pathname.replace(/^.*?\\/api\\/v1/, '')
  let body = {}
  if (path === '/bild/modelle') {
    body = { programm_da: true, modelle: [TURBO, OTHER], standardmodell: TURBO, families: {}, sampler: [],
             scheduler: [], loras: [], sizes: {} }
  } else if (path === '/bild/familien') {
    body = table
  } else if (path === '/bild/vorgaben') {
    const model = url.searchParams.get('modell')
    const chosen = url.searchParams.get('chosen_family') || ''
    asked.push({ model, chosen })
    body = answerFor(model, chosen)
  } else if (path === '/bilder') {
    body = { bilder: [] }
  } else if (path === '/settings/resolved/bildfenster') {
    body = { wert: { modell: TURBO, prompt: 'a cat' } }
  }
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
window.__studio = { werte, listen, auswahl, familieWaehlen, asked }
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { werte, listen, familieWaehlen, asked } = window.__studio
const row = (key) => document.querySelector(`.zeile[data-suche="${key}"]`)
for (let k = 0; k < 100 && !(listen.geladen && row('bild.modell')); k += 1) await wait(100)
await wait(1200)

const now = () => ({ family: werte.familie, steps: werte.schritte, cfg: werte.cfg, sigmas: werte.sigmas })
const chooseModel = async (name) => {
  row('bild.modell').querySelector('[role=combobox]').click()
  await wait(300)
  const option = Array.from(document.querySelectorAll('[role=option]'))
    .find((o) => o.textContent.replace(/\s+/g, ' ').trim().startsWith(name))
  option.click()
  await wait(700)
}
const report = {}

report.start = now()

// A family said by hand on the Turbo file, whose header names none.
asked.length = 0
await familieWaehlen('qwen_image_2_1')
await wait(300)
report.byHand = { ...now(), requests: asked.splice(0) }

// A model whose header names another family: its values, the hand family goes.
await chooseModel('sd15-model')
report.other = { ...now(), requests: asked.splice(0) }

// Said by hand again on that model, then back to the Turbo file (header none):
// the hand family stays and its values are asked for again.
await familieWaehlen('qwen_image_2_1')
asked.length = 0
await chooseModel('Qwen-Image-2.1-Turbo')
report.back = { ...now(), requests: asked.splice(0) }

// "Automatic" empties it and the model starts at its own.
await familieWaehlen('')
await wait(300)
report.auto = now()

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-family-by-hand-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css", "studio": "../../src/lib/studio.svelte.js",
                        "sigmas": SIGMAS},
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
                "--allow-file-access-from-files", "--window-size=1000,1400",
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


def test_the_studio_starts_at_the_model_without_a_family(report):
    assert report["start"]["family"] == "" and report["start"]["sigmas"] == "", report


def test_a_family_said_by_hand_brings_the_turbo_values_of_the_file(report):
    said = report["byHand"]
    assert said["family"] == "qwen_image_2_1", said
    assert (said["steps"], said["cfg"], said["sigmas"]) == (8, 1, SIGMAS), said
    # The family goes to the service with the request.
    assert said["requests"][-1] == {"model": "Qwen-Image-2.1-Turbo-Q4_K_M.gguf", "chosen": "qwen_image_2_1"}, said


def test_a_model_whose_header_names_a_family_takes_its_values_and_the_hand_family_goes(report):
    other = report["other"]
    assert other["family"] == "", other
    assert (other["steps"], other["cfg"], other["sigmas"]) == (30, 7, ""), other
    # One request, made without the old hand family.
    assert other["requests"] == [{"model": "sd15-model.safetensors", "chosen": ""}], other


def test_a_model_without_a_header_family_keeps_the_hand_family_and_asks_with_it(report):
    back = report["back"]
    assert back["family"] == "qwen_image_2_1", back
    assert (back["steps"], back["cfg"], back["sigmas"]) == (8, 1, SIGMAS), back
    assert back["requests"] == [
        {"model": "Qwen-Image-2.1-Turbo-Q4_K_M.gguf", "chosen": ""},
        {"model": "Qwen-Image-2.1-Turbo-Q4_K_M.gguf", "chosen": "qwen_image_2_1"},
    ], back


def test_silence_automatic_takes_the_hand_family_away_and_with_it_the_schedule(report):
    auto = report["auto"]
    assert auto["family"] == "" and auto["sigmas"] == "" and auto["steps"] == 20, auto
