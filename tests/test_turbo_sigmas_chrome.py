"""The studio lays the Turbo model's noise schedule into the field "Sigmas",
measured in a real browser.

``StudioDetails.svelte`` is built as shipped and drawn in headless Chrome with
the picture service made up in the page: the start values of the Turbo model
carry the nine numbers, those of the base model none. Choosing the Turbo model
puts the list into the field (folded under the fine tuning until opened), and
choosing the base model afterwards empties it again, as with every other start
value. Skipped where there is no Chrome or no node, like the other browser tests.
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
  import StudioDetails from '../../src/teile/StudioDetails.svelte'
</script>

<div id="frame" style="width: 420px; height: 1400px; position: relative; display: flex; flex-direction: column;">
  <StudioDetails />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { werte, familieWaehlen } from %(studio)r

const start = (sigmas) => ({
  breite: 2048, hoehe: 2048, schritte: 8, cfg: 1, guidance: null, sampler: 'euler', scheduler: '',
  flow_shift: null, sigmas, family: 'qwen_image_2_1', parts: {}, eigene: [], sources: {},
  switches: {}, vae_format: '', rng: '',
})
window.fetch = async (address) => {
  const url = String(address)
  const path = url.replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  let body = {}
  if (path === '/bild/vorgaben') body = start(url.includes('Turbo') ? %(sigmas)r : '')
  if (path === '/bild/modelle') body = { programm_da: true, modelle: [], families: {}, sampler: [], scheduler: [], loras: [], sizes: {} }
  if (path === '/bild/familien') body = []
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
window.__studio = { werte, familieWaehlen }
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { werte, familieWaehlen } = window.__studio
const heads = () => Array.from(document.querySelectorAll('section.abschnitt'))
for (let k = 0; k < 100 && heads().length < 3; k += 1) await wait(100)
await wait(300)

const open = async () => {
  const section = heads().find((s) => s.textContent.includes('bild.gruppe_feintuning'))
  const fold = section.querySelector('.klappe')
  if (fold.getAttribute('aria-expanded') !== 'true') fold.click()
  await wait(300)
}
const shown = () => document.querySelector('.zeile[data-suche="bild.sigmas"] input')?.value ?? null
const report = {}

report.start = { value: werte.sigmas }
werte.modell = 'Qwen-Image-2.1-Turbo-Q4_K_M.gguf'
await familieWaehlen('')
await open()
report.turbo = { value: werte.sigmas, field: shown(), steps: werte.schritte, cfg: werte.cfg, sampler: werte.sampler }

werte.modell = 'Qwen-Image-2.1-Q4_K_M.gguf'
await familieWaehlen('')
await wait(300)
report.base = { value: werte.sigmas, field: shown() }

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-turbo-sigmas-{uuid4().hex}"
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


def test_the_studio_starts_with_no_schedule(report):
    assert report["start"]["value"] == "", report


def test_choosing_the_turbo_model_puts_its_schedule_into_the_field(report):
    assert report["turbo"]["value"] == SIGMAS, report
    assert report["turbo"]["field"] == SIGMAS, report
    assert (report["turbo"]["steps"], report["turbo"]["cfg"], report["turbo"]["sampler"]) == (8, 1, "euler"), report


def test_silence_choosing_the_base_model_afterwards_takes_it_out_again(report):
    assert report["base"] == {"value": "", "field": ""}, report
