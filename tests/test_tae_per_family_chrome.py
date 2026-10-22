"""The VAE list of a model on the picture server page offers the tiny
autoencoders (TAE) of the model's family only, in a real browser.

``Bildmodellwerte.svelte`` is built as shipped on the stub of
``tests/image_window_page.py``; the family table is the service's own
(``image_families.as_json()``), the folder holds one file of each kind plus one
whose name carries no kind, and the model's family is made up per case. A model
whose family is not read is offered every file. Skipped where there is no
Chrome or no node.
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

FILES = {
    "taesd.safetensors": "taesd", "taesdxl.safetensors": "taesdxl", "taesd3.safetensors": "taesd3",
    "taef1.safetensors": "taef1", "taef2.safetensors": "taef2", "taew2_1.safetensors": "taew2_1",
    "taew2_2.safetensors": "taew2_2", "taeqi2_1.safetensors": "taeqi2_1",
    "diffusion_pytorch_model.safetensors": "",
}

ENTRY_IMPORTS = """import { texte } from '../../src/lib/texte.svelte.js'
import { imageFamilies } from '../../src/lib/imageFamilies.svelte.js'
import german from '../../../app/locales/de.json'
texte.katalog = german
texte.sprache = 'de'
imageFamilies.list = __FAMILIES__
window.__lists = { vaes: ['ae.safetensors'], taesd_files: __FILES__, tae_kinds: __KINDS__ }
"""

CASES = r"""
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const head = () => document.querySelector('.kitkopf')
const field = () => [...document.querySelectorAll('button[role="combobox"]')].find((b) => b.getAttribute('aria-label') === '__VAE__')
const open = async (presets) => {
  window.scene.show = ''
  await wait(300)
  backend.presets = presets
  window.scene.show = 'values'
  for (let k = 0; k < 60 && !head(); k += 1) await wait(100)
  await wait(600)
  head().click()
  await wait(400)
}
const listed = async () => {
  field().click()
  await wait(300)
  const list = document.querySelector('.klapp [role="listbox"]')
  const entries = [...list.children].map((n) => (n.classList.contains('group-name') ? { group: text(n) } : { option: text(n) }))
  field().click()
  await wait(200)
  return entries
}
const cases = {
  sd15: { family: 'sd15' }, sd2: { family: 'sd2' }, sdxl: { family: 'sdxl' }, pixart: { family: 'pixart' },
  sd3: { family: 'sd3' }, flux: { family: 'flux' }, flux2: { family: 'flux2' }, krea2: { family: 'krea2' },
  wan22_ti2v: { family: 'wan22_ti2v' }, qwen_image_2_1: { family: 'qwen_image_2_1' },
  pid: { family: 'pid' },
  free: { family: '', family_detection: false },
  unread: { family: '' },
}
report.cases = {}
for (const [name, presets] of Object.entries(cases)) {
  await open(presets)
  report.cases[name] = await listed()
}
"""


@pytest.fixture(scope="module")
def report() -> dict:
    families = json.dumps(image_families.as_json())
    entry = harness.ENTRY_JS.replace(
        "import '../../src/stil/global.css'\n",
        "import '../../src/stil/global.css'\n" + ENTRY_IMPORTS.replace("__FAMILIES__", families)
        .replace("__FILES__", json.dumps(sorted(FILES))).replace("__KINDS__", json.dumps(FILES)),
    ).replace(
        "  if (path === '/bild/vorgaben') return answer(PRESETS)\n",
        "  if (path === '/bild/vorgaben') return answer({ ...PRESETS, ...(backend.presets || {}) })\n",
    )
    entry = entry.replace("  calls: [],\n  delay: 0,\n}", "  calls: [],\n  delay: 0,\n  presets: {},\n}")
    assert "backend.presets" in entry and "presets: {}" in entry
    shell = harness.SHELL.replace('listen={{}}', 'listen={window.__lists}')
    assert "window.__lists" in shell
    page = harness.PAGE.replace(
        '<script src="out/entry.js"></script>',
        '<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">\n<script src="out/entry.js"></script>',
    )
    cases = CASES.replace("__VAE__", GERMAN["bild"]["vae"])
    with (
        mock.patch.object(harness, "SHELL", shell),
        mock.patch.object(harness, "ENTRY_JS", entry),
        mock.patch.object(harness, "PAGE", page),
    ):
        return run_cases(cases, limit=300.0, window="1500,3000")


def _taes(entries: list[dict]) -> list[str]:
    """The files under the line of the tiny autoencoders, as the list shows them."""
    shown = [e.get("group") or e["option"] for e in entries]
    line = GERMAN["bild"]["vae_group_tae"]
    return [name.removesuffix(".safetensors") for name in shown[shown.index(line) + 1:]] if line in shown else []


@pytest.mark.parametrize("name,files", [
    ("sd15", ["taesd"]), ("sd2", ["taesd"]), ("sdxl", ["taesdxl"]), ("pixart", ["taesd", "taesdxl"]),
    ("sd3", ["taesd3"]), ("flux", ["taef1"]), ("flux2", ["taef2"]), ("krea2", ["taew2_1"]),
    ("wan22_ti2v", ["taew2_2"]), ("qwen_image_2_1", ["taeqi2_1"]),
])
def test_a_model_is_offered_the_tae_of_its_family_only(report, name, files):
    assert _taes(report["cases"][name]) == files, report["cases"][name]


def test_a_family_without_a_tae_gets_no_line_of_them(report):
    entries = report["cases"]["pid"]
    assert _taes(entries) == [] and {"group": GERMAN["bild"]["vae_group_tae"]} not in entries, entries


def test_silence_the_vae_files_stand_in_every_list(report):
    for name, entries in report["cases"].items():
        assert {"option": "ae.safetensors"} in entries, (name, entries)


def test_silence_a_model_whose_family_is_not_read_is_offered_every_file(report):
    expected = sorted(file.removesuffix(".safetensors") for file in FILES)
    assert sorted(_taes(report["cases"]["free"])) == expected, report["cases"]["free"]
    # The same where the header names no family.
    assert sorted(_taes(report["cases"]["unread"])) == expected, report["cases"]["unread"]
