"""The studio's fields that name a file of a companion folder, in a real browser.

``StudioBasics.svelte`` (which fills the values) and ``StudioDetails.svelte``
are built as shipped and drawn in headless Chrome with the picture service made
up in the page: two upscaler files, one tiny autoencoder. The row "Upscaler"
starts with "-" like the other rows, offers it first and can be set back to it;
a file the stored choice names and the folder does not hold (any more) shows
"-" and goes nowhere. A stored choice whose file is there stays chosen.
Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from urllib.parse import quote
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
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

<div id="frame" style="width: 800px; height: 1400px; position: relative; display: flex;">
  <div style="width: 340px; position: relative; overflow: hidden;"><StudioBasics /></div>
  <div style="width: 420px; position: relative; display: flex; flex-direction: column;"><StudioDetails /></div>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { werte, listen, auswahl } from %(studio)r

const q = JSON.parse(new URLSearchParams(location.search).get('s'))
const answers = {
  '/bild/modelle': {
    programm_da: true, modelle: ['model-a'], standardmodell: 'model-a', families: {}, sampler: [], scheduler: [],
    loras: ['a.safetensors'], sizes: {},
    upscalers: ['x2.pth', 'x4.pth'], upscaler_scales: { 'x2.pth': 2, 'x4.pth': 4 },
    taesd_files: ['taesdxl.safetensors'], yolos: ['face.pt'],
  },
  '/bild/familien': [],
  '/bild/vorgaben': { family: '', breite: 1024, hoehe: 1024, schritte: 8, cfg: 1 },
  '/bilder': { bilder: [] },
  '/settings/resolved/bildfenster': { wert: { modell: 'model-a', prompt: 'a cat', ...q.stored } },
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
window.__studio = { werte, listen, auswahl }
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { werte, listen } = window.__studio
const row = (key) => document.querySelector(`.zeile[data-suche="${key}"]`)
const shown = (key) => row(key)?.querySelector('[role=combobox]')?.textContent.replace(/\s+/g, ' ').trim() ?? null
for (let k = 0; k < 100 && !(listen.geladen && row('bild.upscaler')); k += 1) await wait(100)
await wait(1200)

// The row of the tiny autoencoder lies in the section "Fine tuning", shut at first.
Array.from(document.querySelectorAll('button'))
  .find((b) => b.textContent.trim() === 'bild.gruppe_feintuning')?.click()
await wait(500)
const report = {}
report.start = { shown: shown('bild.upscaler'), value: werte.upscale_model, taesdShown: shown('bild.taesd'),
                 taesd: werte.taesd, lora: JSON.parse(JSON.stringify(werte.stapel)),
                 hires: werte.hires_upscaler, ad: werte.ad_modell }

const open = async () => {
  row('bild.upscaler').querySelector('[role=combobox]').click()
  await wait(250)
  return Array.from(document.querySelectorAll('[role=option]')).map((o) => o.textContent.replace(/\s+/g, ' ').trim())
}
const choose = async (text) => {
  const option = Array.from(document.querySelectorAll('[role=option]'))
    .find((o) => o.textContent.replace(/\s+/g, ' ').trim() === text)
  option?.click()
  await wait(250)
}
report.options = await open()
await choose('x4.pth')
report.picked = { shown: shown('bild.upscaler'), value: werte.upscale_model }
await open()
await choose('bild.adetailer_keins')
report.back = { shown: shown('bild.upscaler'), value: werte.upscale_model }

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

SCENARIOS = {
    "fresh": {"stored": {}},
    "gone": {"stored": {
        "live_preview": "tae", "taesd": "gone.safetensors", "upscale_model": "gone.pth",
        "hires_upscaler": "gone.pth", "ad_modell": "gone.pt",
        "stapel": [{"name": "a.safetensors", "staerke": 0.7}, {"name": "gone.safetensors", "staerke": 1}],
    }},
    "there": {"stored": {
        "live_preview": "tae", "taesd": "taesdxl.safetensors", "upscale_model": "x2.pth",
        "hires_upscaler": "x4.pth", "ad_modell": "face.pt",
        "stapel": [{"name": "a.safetensors", "staerke": 0.7}],
    }},
}


@pytest.fixture(scope="module")
def reports() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-dash-fields-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css", "studio": "../../src/lib/studio.svelte.js"},
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(page.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(page.PAGE % {"cases": CASES}, encoding="utf-8")
        out: dict = {}
        for name, scenario in SCENARIOS.items():
            port = page._free_port()
            browser = subprocess.Popen(
                [
                    program, "--headless=new", "--no-first-run", "--disable-background-networking",
                    "--allow-file-access-from-files", "--window-size=1000,1400",
                    f"--remote-debugging-port={port}", f"--user-data-dir={folder / ('profile-' + name)}",
                    (folder / "measure.html").as_uri() + "?s=" + quote(json.dumps(scenario)),
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                out[name] = asyncio.run(page._drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


KEEPS = "bild.adetailer_keins"


def test_the_row_upscaler_starts_with_the_dash_and_shows_it_while_none_is_chosen(reports):
    start = reports["fresh"]["start"]
    assert start["value"] == "" and start["shown"] == KEEPS, start


def test_the_row_upscaler_offers_the_dash_first_then_the_files(reports):
    assert reports["fresh"]["options"] == [KEEPS, "x2.pth", "x4.pth"], reports["fresh"]


def test_a_file_chosen_can_be_taken_back_to_the_dash(reports):
    report = reports["fresh"]
    assert report["picked"] == {"shown": "x4.pth", "value": "x4.pth"}, report
    assert report["back"] == {"shown": KEEPS, "value": ""}, report


def test_a_stored_choice_whose_file_is_gone_shows_the_dash_and_goes_nowhere(reports):
    start = reports["gone"]["start"]
    assert start["taesd"] == "" and start["taesdShown"] == KEEPS, start
    assert start["value"] == "" and start["shown"] == KEEPS, start
    assert start["hires"] == "" and start["ad"] == "", start
    # The stack keeps the LoRA the folder holds and loses the one it does not.
    assert [entry["name"] for entry in start["lora"]] == ["a.safetensors"], start


def test_a_stored_choice_whose_file_is_there_stays_chosen(reports):
    """Silence probe: nothing is taken back that the folders hold."""
    start = reports["there"]["start"]
    assert start["taesd"] == "taesdxl.safetensors" and start["taesdShown"] == "taesdxl.safetensors", start
    assert start["value"] == "x2.pth" and start["shown"] == "x2.pth", start
    assert start["hires"] == "x4.pth" and start["ad"] == "face.pt", start
    assert [entry["name"] for entry in start["lora"]] == ["a.safetensors"], start
