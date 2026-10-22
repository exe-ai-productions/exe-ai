"""The head of a model's parts on the picture server page reads "Parts · n" and
counts as many as the family needs, in a real browser.

``Bildmodellwerte.svelte`` is built as shipped on the stub of
``tests/image_window_page.py``; the family table is the service's own
(``image_families.as_json()``), the start values of the model are made up per
case. The head stands as the last row of the Model card, folded; n is the number
of rows that stand under it once it is unfolded. Skipped where there is no Chrome
or no node.
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
ENGLISH = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))

ENTRY_IMPORTS = """import { texte } from '../../src/lib/texte.svelte.js'
import { imageFamilies } from '../../src/lib/imageFamilies.svelte.js'
import german from '../../../app/locales/de.json'
import english from '../../../app/locales/en.json'
texte.katalog = german
texte.sprache = 'de'
imageFamilies.list = __FAMILIES__
window.texte = texte
window.german = german
window.english = english
"""

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
const look = () => {
  const button = head()
  if (!button) return { found: false }
  const row = button.closest('.zeile')
  const rows = () => [...row.parentElement.children].filter((n) => n.classList.contains('zeile'))
  return {
    found: true, word: text(button.querySelector('span')), expanded: button.getAttribute('aria-expanded'),
    count: text(button.querySelector('.stand') || document.createElement('i')),
    dot: button.querySelector('.stand svg')?.getAttribute('data-farbe') ?? '',
    folder: Boolean(row.querySelector('.foldersign')), last: rows().indexOf(row) === rows().length - 1,
  }
}
const underHead = () => {
  const row = head().closest('.zeile')
  return [...row.parentElement.children].filter((n) => n.classList.contains('zeile')).length
    - [...row.parentElement.children].filter((n) => n.classList.contains('zeile')).indexOf(row) - 1
}
const cases = {
  sdxl: { family: 'sdxl', standalone: false, family_detection: true, parts: {} },
  flux: { family: 'flux', standalone: true, family_detection: true, parts: { t5xxl: 't5.safetensors', clip_l: 'cl.safetensors', vae: 'ae.safetensors' } },
  fluxMissing: { family: 'flux', standalone: true, family_detection: true, parts: { t5xxl: 't5.safetensors' } },
  free: { family: '', standalone: false, family_detection: false, parts: {} },
}
report.cases = {}
for (const [name, presets] of Object.entries(cases)) {
  await open(presets)
  const entry = { folded: look() }
  head().click()
  await wait(400)
  entry.unfolded = look()
  entry.rowsUnder = underHead()
  window.texte.katalog = window.english
  window.texte.sprache = 'en'
  await wait(300)
  entry.english = look()
  window.texte.katalog = window.german
  window.texte.sprache = 'de'
  await wait(300)
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
    with mock.patch.object(harness, "ENTRY_JS", entry), mock.patch.object(harness, "PAGE", page):
        return run_cases(CASES, limit=240.0, window="1500,3000")


WORD = GERMAN["bildserver"]["parts_count"]
WORD_EN = ENGLISH["bildserver"]["parts_count"]
KIT = GERMAN["bildserver"]["bausatz"]


def _word(template: str, count: int) -> str:
    return template.replace("{count}", str(count))


def test_the_catalogues_carry_the_word_in_both_languages():
    assert (WORD, WORD_EN) == ("Teile · {count}", "Parts · {count}")


@pytest.mark.parametrize("name,count", [("sdxl", 1), ("flux", 4), ("fluxMissing", 4), ("free", 14)])
def test_the_head_counts_the_rows_that_stand_under_it(report, name, count):
    entry = report["cases"][name]
    assert entry["folded"]["word"] == _word(WORD, count), entry
    assert entry["unfolded"]["word"] == _word(WORD, count), entry
    assert entry["rowsUnder"] == count, entry


def test_the_head_reads_parts_in_english(report):
    assert report["cases"]["flux"]["english"]["word"] == _word(WORD_EN, 4), report["cases"]["flux"]


def test_silence_the_head_stands_folded_as_the_last_row_with_its_folder_sign(report):
    for name, entry in report["cases"].items():
        assert entry["folded"]["expanded"] == "false" and entry["folded"]["last"] is True, (name, entry)
        assert entry["folded"]["folder"] is True, (name, entry)
        assert entry["unfolded"]["expanded"] == "true", (name, entry)


def test_silence_the_count_of_what_is_there_stays_beside_the_head_with_its_dot(report):
    full, missing = report["cases"]["flux"]["folded"], report["cases"]["fluxMissing"]["folded"]
    assert full["count"] == GERMAN["bildserver"]["teile_da"].replace("{da}", "4").replace("{alle}", "4"), full
    assert full["dot"] == "gruen", full
    assert missing["count"] == GERMAN["bildserver"]["teile_da"].replace("{da}", "2").replace("{alle}", "4"), missing
    assert missing["dot"] == "still", missing
    # A model that is no kit and one whose family is not read carry no count.
    assert report["cases"]["sdxl"]["folded"]["count"] == "", report["cases"]["sdxl"]
    assert report["cases"]["free"]["folded"]["count"] == "", report["cases"]["free"]


def test_the_catalogue_detail_keeps_the_word_kit():
    source = (ROOT / "frontend" / "src" / "teile" / "Modelldetail.svelte").read_text(encoding="utf-8")
    start = source.index("<Bausatzkopf")
    call = source[start: source.index("/>", start)]
    assert "word=" not in call, call
    assert KIT == "Bausatz"
