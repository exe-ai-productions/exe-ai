"""The studio's model choice offers only models whose kit is complete.

The service names, for every model of the picture folder that cannot be drawn
for want of a kit part, the first part it misses (``missing_parts`` of
``GET /bild/modelle``, ``missing_kit_part`` in ``app/api/v1/bild.py``) — the
same rule the start of a model refuses with. The studio's choice leaves such a
model out; a stored one that misses a part, or is gone, shows the default
model; a default that misses a part itself leaves the field empty and says,
under the choice, which part it misses. The picture server page lists every
model, and the start of an incomplete model still answers 412 with the part.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest

from app import appfenster, bildmodellwerte, prozessstopp
from app.api.v1 import bild
from tests import test_studio_generate_stays_chrome as page
from tests.studio_test_run import needs_node, run
from tests.test_bild_bausatz_api import _kopf
from tests.test_video_kit_parts import (
    LTX_AUDIO,
    LTX_CONNECTORS,
    LTX_MODEL,
    _AUDIO_VAE_HEAD,
    _after,
    _CONNECTORS_HEAD,
    _ltx_folder,
    _own_vae,
    hand_start,  # noqa: F401  (a fixture of the kit tests)
)

FRONTEND = page.FRONTEND
ROOT = Path(__file__).resolve().parent.parent
VIDEO_VAE = "ltx-2.3-22b-dev_video_vae.safetensors"


# --- The service ---------------------------------------------------------------------------


def _models(client) -> dict:
    return client.get("/api/v1/bild/modelle").json()


def test_a_model_of_a_kit_family_without_its_vae_is_named_with_the_part_it_misses(client, config, tmp_path):
    folder = _ltx_folder(tmp_path, audio=True, connectors=True)
    config.app.bildmodelle_verzeichnis = str(folder)
    answer = _models(client)
    assert LTX_MODEL in answer["modelle"]
    assert answer["missing_parts"] == {LTX_MODEL: "VAE"}, answer["missing_parts"]


def test_the_part_that_misses_next_is_named_once_the_first_is_there(client, config, tmp_path):
    folder = _ltx_folder(tmp_path, audio=False, connectors=False)
    config.app.bildmodelle_verzeichnis = str(folder)
    _own_vae(client, LTX_MODEL, VIDEO_VAE)
    assert _models(client)["missing_parts"] == {LTX_MODEL: "Audio VAE"}
    _kopf(folder / "vae" / LTX_AUDIO, dict(_AUDIO_VAE_HEAD))
    assert _models(client)["missing_parts"] == {LTX_MODEL: "Embeddings connectors"}


def test_silence_a_complete_model_is_not_named(client, config, tmp_path):
    folder = _ltx_folder(tmp_path, audio=True, connectors=True)
    config.app.bildmodelle_verzeichnis = str(folder)
    _own_vae(client, LTX_MODEL, VIDEO_VAE)
    answer = _models(client)
    assert LTX_MODEL in answer["modelle"] and answer["missing_parts"] == {}, answer["missing_parts"]


def test_silence_a_checkpoint_with_a_vae_of_its_own_misses_nothing(client, config, tmp_path):
    name = "sdxl.safetensors"
    folder = tmp_path / "bildmodelle"
    folder.mkdir()
    _kopf(folder / name, {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "conditioner.embedders.1.model.token_embedding.weight": [49408, 1280],
        "first_stage_model.decoder.conv_in.weight": [512, 4, 3, 3],
    })
    config.app.bildmodelle_verzeichnis = str(folder)
    answer = _models(client)
    assert answer["modelle"] == [name] and answer["missing_parts"] == {}


def test_a_model_whose_family_is_not_read_misses_nothing(client, config, tmp_path):
    from app.db.repositories.einstellungen import GLOBAL

    folder = _ltx_folder(tmp_path, audio=False, connectors=False)
    config.app.bildmodelle_verzeichnis = str(folder)
    assert LTX_MODEL in _models(client)["missing_parts"]
    client.app.state.repositories.einstellungen.zusammenlegen(
        GLOBAL, bildmodellwerte.SCHLUESSEL, {LTX_MODEL: {bildmodellwerte.FAMILY_DETECTION: False}},
        pruefen=bildmodellwerte.pruefen,
    )
    assert LTX_MODEL not in _models(client)["missing_parts"]


def test_the_list_and_the_start_name_a_missing_part_by_one_rule(hand_start, client, config, tmp_path):  # noqa: F811
    folder = _ltx_folder(tmp_path, audio=False, connectors=False)
    _own_vae(client, LTX_MODEL, VIDEO_VAE)
    repositories = client.app.state.repositories
    path = folder / LTX_MODEL
    config.app.bildmodelle_verzeichnis = str(folder)
    # Incomplete: the list names the part, the start refuses with the same one.
    answer, command = hand_start(folder, LTX_MODEL)
    assert answer.status_code == 412 and "Audio VAE" in answer.json()["detail"], answer.text
    assert command is None
    assert bild.missing_kit_part(config, repositories, LTX_MODEL, path) == "Audio VAE"
    # Complete: the list names nothing, the start goes through.
    _kopf(folder / "vae" / LTX_AUDIO, dict(_AUDIO_VAE_HEAD))
    _kopf(folder / "text_encoders" / LTX_CONNECTORS, dict(_CONNECTORS_HEAD))
    assert bild.missing_kit_part(config, repositories, LTX_MODEL, path) is None
    answer, command = hand_start(folder, LTX_MODEL)
    assert answer.status_code == 200, answer.text
    assert _after(command, "--audio-vae") == str(folder / "vae" / LTX_AUDIO)


# --- The studio's own modules, in node -----------------------------------------------------

LISTS = """
studio.listen.geladen = true
studio.listen.modelle = ['complete.safetensors', 'partial.safetensors']
studio.listen.missingParts = { 'partial.safetensors': 'VAE' }
"""


@needs_node
def test_only_a_model_in_the_folder_whose_parts_are_there_is_offered():
    report = run(f"""{LISTS}
    return ['complete.safetensors', 'partial.safetensors', 'gone.safetensors'].map((n) => studio.modellDa(n))
    """)
    assert report == [True, False, False], report


@needs_node
def test_nothing_is_judged_as_missing_before_the_lists_were_read():
    """Silence probe: a list that was not read leaves no model out for want of a part."""
    report = run("""
    studio.listen.geladen = false
    studio.listen.modelle = ['a.safetensors']
    return [studio.modellDa('a.safetensors'), studio.listen.missingParts]
    """)
    assert report == [True, {}], report


@needs_node
def test_a_press_with_no_model_and_a_default_that_misses_a_part_names_the_part():
    report = run(f"""{LISTS}
    studio.listen.standardmodell = 'partial.safetensors'
    studio.werte.modell = ''
    studio.werte.prompt = 'a cat'
    await draw.studioZeichnen()
    await settled()
    return {{ said: said.map((s) => s[0]), drawn: wishes.length }}
    """)
    assert report == {"said": ["bild.teil_fehlt"], "drawn": 0}, report


@needs_node
def test_a_press_with_no_model_and_no_default_says_where_it_is_chosen():
    """Silence probe: without a default model the sentence stays the one it was."""
    report = run(f"""{LISTS}
    studio.listen.standardmodell = ''
    studio.werte.modell = ''
    studio.werte.prompt = 'a cat'
    await draw.studioZeichnen()
    await settled()
    return {{ said: said.map((s) => s[0]), drawn: wishes.length }}
    """)
    assert report == {"said": ["bildserver.kein_standardmodell"], "drawn": 0}, report


# --- The studio's column, in a browser -----------------------------------------------------

SHELL = """<script>
  import StudioBasics from '../../src/teile/StudioBasics.svelte'
</script>

<div id="frame" style="width: 360px; height: 1400px; position: relative; overflow: hidden;"><StudioBasics /></div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { werte, listen, auswahl } from %(studio)r

const q = JSON.parse(new URLSearchParams(location.search).get('s'))
const answers = {
  '/bild/modelle': {
    programm_da: true, modelle: q.modelle, standardmodell: q.standard, families: {}, sampler: [], scheduler: [],
    loras: [], sizes: {}, missing_parts: q.missing, upscalers: [], upscaler_scales: {}, taesd_files: [], yolos: [],
  },
  '/bild/familien': [],
  '/bild/vorgaben': { family: '', breite: 1024, hoehe: 1024, schritte: 8, cfg: 1 },
  '/bilder': { bilder: [] },
  '/settings/resolved/bildfenster': { wert: { modell: q.stored, prompt: 'a cat' } },
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
const text = (node) => node?.textContent.replace(/\s+/g, ' ').trim() ?? null
const row = () => document.querySelector('.zeile[data-suche="bild.modell"]')
for (let k = 0; k < 100 && !(listen.geladen && row()); k += 1) await wait(100)
await wait(1500)
const report = { value: werte.modell }
const combo = document.querySelector('.zeile.voll [role=combobox]')
report.shown = text(combo)
report.note = text(document.querySelector('.zeile.leer'))
report.options = []
if (combo) {
  combo.click()
  await wait(300)
  report.options = Array.from(document.querySelectorAll('[role=option]')).map((o) => text(o))
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

BOTH = ["complete.safetensors", "partial.safetensors"]
SCENARIOS = {
    "stored_partial": {
        "modelle": BOTH, "missing": {"partial.safetensors": "VAE"}, "standard": "complete.safetensors",
        "stored": "partial.safetensors",
    },
    "stored_gone": {
        "modelle": BOTH, "missing": {"partial.safetensors": "VAE"}, "standard": "complete.safetensors",
        "stored": "gone.safetensors",
    },
    "stored_complete": {
        "modelle": BOTH, "missing": {"partial.safetensors": "VAE"}, "standard": "complete.safetensors",
        "stored": "complete.safetensors",
    },
    "default_partial": {
        "modelle": BOTH, "missing": {"partial.safetensors": "VAE"}, "standard": "partial.safetensors",
        "stored": "partial.safetensors",
    },
    "all_partial": {
        "modelle": ["partial.safetensors"], "missing": {"partial.safetensors": "VAE"},
        "standard": "partial.safetensors", "stored": "",
    },
    "no_default": {
        "modelle": BOTH, "missing": {"partial.safetensors": "VAE"}, "standard": "", "stored": "partial.safetensors",
    },
    "nothing_missing": {
        "modelle": BOTH, "missing": {}, "standard": "complete.safetensors", "stored": "partial.safetensors",
    },
}


@pytest.fixture(scope="module")
def reports() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists():
        pytest.skip("no node or no frontend dependencies on this machine")
    folder = FRONTEND / "node_modules" / f".harness-complete-models-{uuid4().hex}"
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
                    "--allow-file-access-from-files", "--mute-audio", "--window-size=1000,1400",
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


browser_only = pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only")
COMPLETE = "complete.safetensors"
NOTE = "partial.safetensors: bild.teil_fehlt"


@browser_only
def test_the_choice_lists_the_complete_models_and_not_the_one_that_misses_a_part(reports):
    assert reports["stored_complete"]["options"] == [COMPLETE], reports["stored_complete"]
    assert reports["stored_complete"]["shown"] == COMPLETE


@browser_only
def test_a_stored_model_that_misses_a_part_shows_the_default_model(reports):
    report = reports["stored_partial"]
    assert report["value"] == COMPLETE and report["shown"] == COMPLETE, report
    assert report["note"] is None, report


@browser_only
def test_a_stored_model_that_is_gone_still_shows_the_default_model(reports):
    """Silence probe: what a gone model did before stays."""
    report = reports["stored_gone"]
    assert report["value"] == COMPLETE and report["shown"] == COMPLETE, report


@browser_only
def test_a_default_that_misses_a_part_leaves_the_field_empty_and_names_its_file_and_part(reports):
    report = reports["default_partial"]
    assert report["value"] == "" and report["options"] == [COMPLETE], report
    assert report["note"] == NOTE, report


@browser_only
def test_the_note_stands_too_when_every_model_of_the_folder_misses_a_part(reports):
    report = reports["all_partial"]
    assert report["value"] == "" and report["options"] == [], report
    assert report["note"] == NOTE, report


@browser_only
def test_with_no_default_model_the_field_stays_empty_and_no_part_is_named(reports):
    report = reports["no_default"]
    assert report["value"] == "" and report["note"] is None, report
    assert report["options"] == [COMPLETE], report


@browser_only
def test_silence_where_no_part_misses_every_model_is_offered_and_a_stored_one_stays(reports):
    report = reports["nothing_missing"]
    assert report["options"] == BOTH and report["value"] == "partial.safetensors", report
    assert report["note"] is None, report


# --- Where the page of the picture server stands ---------------------------------------------


def test_the_picture_server_page_still_lists_every_model():
    source = (ROOT / "frontend/src/teile/Bildserver.svelte").read_text(encoding="utf-8")
    assert "missingParts" not in source and "missing_parts" not in source
    assert "modelle={(stand?.modelle ?? [])" in source


def test_a_picture_taken_over_from_the_infos_offers_the_same_models_as_the_choice():
    source = (ROOT / "frontend/src/lib/studiobilder.svelte.js").read_text(encoding="utf-8")
    assert "i.modell && modellDa(i.modell)" in source
