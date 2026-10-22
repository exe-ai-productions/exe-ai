"""A video model's frames and frame rate stand under "Parameter" and are saved at
the model, measured in a real browser.

``Bildmodellwerte.svelte`` is built as shipped on the stub of
``tests/image_window_page.py``; the family table is the service's own
(``image_families.as_json()``), the answer about the model is made up per case.
A family that starts with frames shows the row for them, one that also has a
frame rate it can set shows that row too; a picture family shows neither, and
Wan 2.2 S2V, which draws at one rate, shows frames only. A number typed into a
row travels under the route's own name when the save sign is pressed. Skipped
where there is no Chrome or no node.
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
const rows = () => [...document.querySelectorAll('.zeile .name')].map(text)
const open = async (presets) => {
  window.scene.show = ''
  await wait(300)
  backend.presets = presets
  window.scene.show = 'values'
  for (let k = 0; k < 60 && !rows().length; k += 1) await wait(100)
  await wait(600)
}
const cases = {
  wan: { family: 'wan', video_frames: 81, fps: 16 },
  s2v: { family: 'wan22_s2v', video_frames: 81, fps: null },
  sdxl: { family: 'sdxl', video_frames: null, fps: null },
}
report.cases = {}
for (const [name, presets] of Object.entries(cases)) {
  await open(presets)
  report.cases[name] = rows()
}
// A number typed into the frames row of the first case, then saved.
await open(cases.wan)
const row = [...document.querySelectorAll('.zeile')].find((n) => text(n.querySelector('.name') || n) === "__FRAMES__")
const field = row.querySelector('input')
field.focus()
field.value = '17'
field.dispatchEvent(new Event('input', { bubbles: true }))
field.dispatchEvent(new Event('change', { bubbles: true }))
field.blur()
await wait(400)
const save = document.querySelector('button[aria-label="__SAVE__"]')
report.saveEnabled = !save.disabled
save.click()
await wait(600)
report.sent = backend.calls.map((c) => c.sent)
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
        cases = CASES.replace("__FRAMES__", GERMAN["bild"]["video_frames"]).replace(
            "__SAVE__", GERMAN["app"]["sichern"],
        )
        return run_cases(cases, limit=240.0, window="1500,3000")


def _label(key: str) -> str:
    group, name = key.split(".")
    return GERMAN[group][name]


def test_a_video_family_shows_frames_and_the_rate_under_parameter(report):
    names = report["cases"]["wan"]
    assert _label("bild.video_frames") in names and _label("bild.fps") in names, names


def test_wan_22_s2v_shows_frames_and_no_rate(report):
    names = report["cases"]["s2v"]
    assert _label("bild.video_frames") in names, names
    assert _label("bild.fps") not in names, names


def test_silence_a_picture_family_shows_neither(report):
    names = report["cases"]["sdxl"]
    assert _label("bild.video_frames") not in names and _label("bild.fps") not in names, names


def test_frames_typed_into_the_row_are_saved_under_the_name_of_the_route(report):
    assert report["saveEnabled"] is True, report
    assert report["sent"] == [{"model.safetensors": {"video_frames": 17}}], report
