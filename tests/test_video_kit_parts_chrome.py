"""The parts of a video family stand as rows under the head of a model's parts,
measured in a real browser.

``Bildmodellwerte.svelte`` is built as shipped on the stub of
``tests/image_window_page.py``; the family table is the service's own
(``image_families.as_json()``), the answer about the model is made up per case.
A checkpoint of a kit family shows every part of its family and no row for a
diffusion model; a diffusion model on its own shows its own row and counts the
parts its docs name for it among the ones it cannot start without. Skipped where
there is no Chrome or no node.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from app import image_families
from tests import image_window_page as harness
from tests.image_window_page import needs_browser, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

ROOT = Path(__file__).resolve().parent.parent
GERMAN = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))

ENTRY_IMPORTS = """import { texte } from '../../src/lib/texte.svelte.js'
import { imageFamilies } from '../../src/lib/imageFamilies.svelte.js'
import german from '../../../app/locales/de.json'
texte.katalog = german
texte.sprache = 'de'
imageFamilies.list = __FAMILIES__
"""

FILES_JS = (
    "const FILES = { text: ['gemma.gguf', 'umt5.safetensors'], "
    "vaes: ['video.safetensors', 'wan_vae.safetensors', 'audio.safetensors'] }"
)

CASES = r"""
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const head = () => document.querySelector('.kitkopf')
const open = async (presets) => {
  window.scene.show = ''
  await wait(300)
  backend.presets = presets
  window.scene.show = 'values'
  for (let k = 0; k < 60 && !head(); k += 1) await wait(100)
  await wait(600)
}
const rowsUnder = () => {
  const row = head().closest('.zeile')
  const all = [...row.parentElement.children].filter((n) => n.classList.contains('zeile'))
  return all.slice(all.indexOf(row) + 1).map((n) => ({
    name: text(n.querySelector('.name')),
    value: text(n.querySelector('.wahl') || document.createElement('i')),
  }))
}
const cases = {
  ltxCheckpoint: {
    family: 'ltx', standalone: false, bare: true, family_detection: true, needed_parts: [],
    parts_taken: ['audio_vae', 'embeddings_connectors'],
    parts: { llm: 'gemma.gguf', audio_vae: 'audio.safetensors' },
  },
  ltxModel: {
    family: 'ltx', standalone: true, bare: false, family_detection: true,
    needed_parts: ['audio_vae', 'embeddings_connectors'],
    parts_taken: ['audio_vae', 'embeddings_connectors'],
    parts: { llm: 'gemma.gguf', vae: 'video.safetensors', audio_vae: 'audio.safetensors' },
  },
  wanI2v: {
    family: 'wan', standalone: true, bare: false, family_detection: true, needed_parts: ['clip_vision'],
    parts_taken: ['clip_vision'],
    parts: { t5xxl: 'umt5.safetensors', vae: 'wan_vae.safetensors' },
  },
  wanT2v: {
    family: 'wan', standalone: true, bare: false, family_detection: true, needed_parts: [],
    parts_taken: [],
    parts: { t5xxl: 'umt5.safetensors', vae: 'wan_vae.safetensors' },
  },
  wan22T2v: {
    family: 'wan', standalone: true, bare: false, family_detection: true, needed_parts: [],
    parts_taken: ['high_noise_diffusion_model'],
    parts: { t5xxl: 'umt5.safetensors', vae: 'wan_vae.safetensors' },
  },
  sdxl: {
    family: 'sdxl', standalone: false, bare: false, family_detection: true, needed_parts: [],
    parts_taken: [], parts: {},
  },
  free: { family: '', standalone: false, bare: false, family_detection: false, needed_parts: [], parts: {} },
}
report.cases = {}
for (const [name, presets] of Object.entries(cases)) {
  await open(presets)
  const entry = { folded: text(head()) }
  head().click()
  await wait(400)
  entry.rows = rowsUnder()
  report.cases[name] = entry
}
"""


@pytest.fixture(scope="module")
def report() -> dict:
    families = json.dumps(image_families.as_json())
    entry = harness.ENTRY_JS.replace(
        "import '../../src/stil/global.css'\n",
        "import '../../src/stil/global.css'\n" + ENTRY_IMPORTS.replace("__FAMILIES__", families),
    ).replace(
        "  if (path === '/bild/vorgaben') return answer(PRESETS)\n",
        "  if (path === '/bild/vorgaben') return answer({ ...PRESETS, ...(backend.presets || {}) })\n",
    )
    entry = entry.replace("  calls: [],\n  delay: 0,\n}", "  calls: [],\n  delay: 0,\n  presets: {},\n}")
    assert "backend.presets" in entry and "presets: {}" in entry and "texte.katalog = german" in entry
    page = harness.PAGE.replace(
        '<script src="out/entry.js"></script>',
        '<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">\n<script src="out/entry.js"></script>',
    )
    # The files the folders offer, so that a part set shows its file's name.
    shell = harness.SHELL.replace("listen={{}}", "listen={{ textversteher: FILES.text, vaes: FILES.vaes }}")
    shell = shell.replace("let switchRows", FILES_JS + "\n  let switchRows")
    assert "FILES.text" in shell and "const FILES" in shell
    with (
        mock.patch.object(harness, "ENTRY_JS", entry), mock.patch.object(harness, "PAGE", page),
        mock.patch.object(harness, "SHELL", shell),
    ):
        return run_cases(CASES, limit=240.0, window="1500,3000")


def _names(report, case: str) -> list[str]:
    return [row["name"] for row in report["cases"][case]["rows"]]


def _label(key: str) -> str:
    group, name = key.split(".")
    return GERMAN[group][name]


def test_a_ltx_checkpoint_shows_the_four_parts_of_its_family_and_no_diffusion_model(report):
    assert _names(report, "ltxCheckpoint") == [
        _label("bild.vae"), _label("bild.llm"), _label("bild.audio_vae"),
        _label("bild.embeddings_connectors"),
    ], report["cases"]["ltxCheckpoint"]
    rows = {row["name"]: row["value"] for row in report["cases"]["ltxCheckpoint"]["rows"]}
    assert rows[_label("bild.llm")] == "gemma.gguf"
    assert rows[_label("bild.audio_vae")] == "audio.safetensors"
    # Nothing is needed of a checkpoint: a part not given stands for "off".
    assert rows[_label("bild.embeddings_connectors")] == _label("bild.adetailer_keins")
    assert "bild.diffusion_model" not in _names(report, "ltxCheckpoint")


def test_the_head_of_a_checkpoint_counts_the_rows_and_no_missing_part(report):
    head = report["cases"]["ltxCheckpoint"]["folded"]
    assert head == GERMAN["bildserver"]["parts_count"].replace("{count}", "4"), head


def test_a_ltx_diffusion_model_shows_its_row_and_marks_the_missing_part(report):
    case = report["cases"]["ltxModel"]
    names = _names(report, "ltxModel")
    assert names[0] == _label("bild.diffusion_model") and len(names) == 5, case
    rows = {row["name"]: row["value"] for row in case["rows"]}
    assert rows[_label("bild.embeddings_connectors")] == _label("bildserver.teil_fehlt_kurz"), case
    assert rows[_label("bild.audio_vae")] == "audio.safetensors", case
    # The model, the LLM, the VAE, the sound decoder and the connectors are what it cannot
    # start without: four of the five are there.
    assert GERMAN["bildserver"]["teile_da"].replace("{da}", "4").replace("{alle}", "5") in case["folded"], case


def test_a_wan_i2v_model_shows_its_image_encoder_as_missing(report):
    rows = {row["name"]: row["value"] for row in report["cases"]["wanI2v"]["rows"]}
    assert rows[_label("bild.sw_clip_vision")] == _label("bildserver.teil_fehlt_kurz"), rows


def test_a_wan_t2v_model_shows_neither_the_image_encoder_nor_the_high_noise_model(report):
    names = _names(report, "wanT2v")
    assert _label("bild.sw_clip_vision") not in names, names
    assert _label("bild.high_noise_modell") not in names, names


def test_a_wan_i2v_model_shows_the_image_encoder_and_no_high_noise_model(report):
    names = _names(report, "wanI2v")
    assert _label("bild.sw_clip_vision") in names, names
    assert _label("bild.high_noise_modell") not in names, names


def test_a_wan_2_2_model_shows_the_high_noise_model_and_no_image_encoder(report):
    names = _names(report, "wan22T2v")
    assert _label("bild.high_noise_modell") in names, names
    assert _label("bild.sw_clip_vision") not in names, names
    # Silence: the rows the model keeps stay (its VAE and its text encoder).
    assert _label("bild.vae") in names and _label("bild.t5xxl") in names, names


def test_silence_a_model_that_is_no_kit_shows_its_vae_alone(report):
    assert _names(report, "sdxl") == [_label("bild.vae")], report["cases"]["sdxl"]


def test_a_model_whose_family_is_not_read_shows_every_part_there_is(report):
    names = _names(report, "free")
    assert _label("bild.sw_clip_vision") in names and _label("bild.audio_encoder") in names, names
    assert len(names) == 14, names
