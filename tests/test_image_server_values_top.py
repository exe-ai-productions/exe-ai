"""The picture server page: the values of one model at the top with a choice of
the folder's models, the folding list of the files, the audio VAE and the
maker's mark in front of every model.

The page is built as shipped on the stub of ``tests/image_window_page.py``
(widened like ``tests/test_image_server_layout_chrome.py``) at 1500 px. The
values block stands right under the first row and before the conversion; its
head carries a choice of every model file of the folder, the default model
chosen to begin with; the list of the files is a folding row, closed to begin
with, whose rows have no arrow and open nothing. Before every file name in the
list and before every entry of the choice stands the mark of the file's family
(Qwen, Microsoft) or, where the house has none, the first letter. A family with
an audio VAE (LTX-2, MiniMax-H3) shows it as a field of its own beside the VAE;
it is saved apart from the VAE and the start hands it over as ``--audio-vae``.
Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from app import bildmodellwerte
from app.api.v1.bild import bild_familien
from tests import image_window_page as harness
from tests.image_window_page import needs_browser, run_cases
from tests.test_image_server_layout_chrome import (
    ENTRY_IMPORTS,
    ROUTES,
    SHELL_IMPORTS,
    SHELL_SCENES,
)
from tests.test_video_kit_parts import (
    LTX_AUDIO,
    LTX_MODEL,
    _after,
    _kopf,
    _ltx_folder,
    _own_vae,
    hand_start,  # noqa: F401  (a fixture of the kit tests)
)

ROOT = Path(__file__).resolve().parent.parent
TEILE = ROOT / "frontend" / "src" / "teile"
GERMAN = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))

FILES = {
    "qwen-image-Q4.gguf": "qwen_image",
    "mage-flow.safetensors": "mage_flow",
    "sdxl-base.safetensors": "sdxl",
    "ltx-2.3.safetensors": "ltx",
}
DEFAULT_MODEL = "sdxl-base.safetensors"
VIDEO_VAE = "video-vae.safetensors"
AUDIO_VAE = "audio-vae.safetensors"


def _source(name: str) -> str:
    return (TEILE / name).read_text(encoding="utf-8")


# --- The source: where the pieces stand --------------------------------------------------


def test_the_values_block_stands_under_the_first_row_and_before_the_conversion():
    page = _source("Bildserver.svelte")
    markup = page.split("<Servertafel", 1)[1]
    first_row_ends = markup.index("</Serverreihe>")
    assert first_row_ends < markup.index("<Bildmodellwerte") < markup.index("<ImageConvert")
    assert markup.index("<ImageConvert") < markup.index("<ImageServerFiles")


def test_the_list_of_the_files_is_a_folding_row_without_arrows_and_clicks():
    files = _source("ImageServerFiles.svelte")
    assert "klappbar offen={false}" in files
    for gone in ("pfeil", "pfeilplatz", "offen = $state", "toggle(", "<Bildmodellwerte", "import Bildmodellwerte"):
        assert gone not in files, gone
    # A row is no control: nothing in it listens to a press.
    row = files.split('class="zeile datei-zeile"', 1)[1].split("{/each}", 1)[0]
    assert "onclick" not in row and "<button" not in row


def test_the_list_the_choice_and_the_quick_picker_draw_the_one_mark_piece():
    files = _source("ImageServerFiles.svelte")
    assert "<MakerMark mark={familyMark(familien[file.name])} name={file.name} />" in files
    assert "<MakerMark {mark} name={r.name} />" in _source("QuickPickTable.svelte")
    # The choice's entries carry the family's mark, else the first letter.
    page = _source("Bildserver.svelte")
    assert "familyMark(families[file.name])" in page
    assert "letter: file.name.slice(0, 1).toUpperCase()" in page


def test_the_default_model_is_what_the_choice_shows_to_begin_with():
    page = _source("Bildserver.svelte")
    assert "[viewed, startModel].find(" in page


def test_choosing_another_default_model_does_not_swap_the_values_under_the_editing_hands():
    # Once a model stands at the top it is kept in `viewed`, so a new default model
    # in the card cannot replace the block (and drop a change not saved).
    assert "if (!viewed && shown) viewed = shown" in _source("Bildserver.svelte")


# --- The service: the audio VAE is saved apart and handed over ---------------------------


def test_an_audio_vae_of_the_model_s_own_goes_to_the_start_apart_from_the_vae(hand_start, client, tmp_path):  # noqa: F811
    folder = _ltx_folder(tmp_path, audio=True, connectors=True)
    other = "my-own-audio-vae.safetensors"
    _kopf(folder / "vae" / other, {"some.weight": [4]})
    _own_vae(client, LTX_MODEL, "ltx-2.3-22b-dev_video_vae.safetensors")
    repositories = client.app.state.repositories
    bildmodellwerte.set_part(repositories, LTX_MODEL, "audio_vae", other)
    own = bildmodellwerte.eigene(repositories, LTX_MODEL)
    assert (own["vae"], own["audio_vae"]) == ("ltx-2.3-22b-dev_video_vae.safetensors", other)
    answer, command = hand_start(folder, LTX_MODEL)
    assert answer.status_code == 200, answer.text
    assert _after(command, "--audio-vae") == str(folder / "vae" / other)
    assert _after(command, "--vae") == str(folder / "vae" / "ltx-2.3-22b-dev_video_vae.safetensors")


def test_silence_without_an_own_choice_the_folder_s_audio_vae_goes_to_the_start(hand_start, client, tmp_path):  # noqa: F811
    folder = _ltx_folder(tmp_path, audio=True, connectors=True)
    _own_vae(client, LTX_MODEL, "ltx-2.3-22b-dev_video_vae.safetensors")
    answer, command = hand_start(folder, LTX_MODEL)
    assert answer.status_code == 200, answer.text
    assert _after(command, "--audio-vae") == str(folder / "vae" / LTX_AUDIO)


# --- The page in a browser -----------------------------------------------------------------

_FAMILY_TABLE = json.dumps(bild_familien())
_FAMILIES = json.dumps(FILES)

PAGE_ROUTES = (
    f"""  if (path === '/bild/familien') return answer({_FAMILY_TABLE})
  if (path === '/bild/vorgaben') {{
    const asked = new URL(String(address), 'http://x').searchParams.get('modell')
    ;(backend.asked ||= []).push(asked)
    const family = {_FAMILIES}[asked] || ''
    const ltx = family === 'ltx'
    return answer({{
      ...PRESETS, family, standalone: ltx, bare: false, family_detection: true,
      needed_parts: ltx ? ['audio_vae', 'embeddings_connectors'] : [],
      parts_taken: ltx ? ['audio_vae', 'embeddings_connectors'] : [],
      parts: ltx ? {{ llm: 'gemma.gguf', vae: '{VIDEO_VAE}' }} : {{}},
    }})
  }}
"""
    + ROUTES.replace("standardmodell: ''", f"standardmodell: '{DEFAULT_MODEL}'")
    .replace(
        "families: { 'a.safetensors': 'sdxl', 'b.safetensors': 'sdxl' },",
        f"families: {_FAMILIES}, vaes: ['{VIDEO_VAE}', '{AUDIO_VAE}'],",
    )
)

PAGE_IMPORTS = ENTRY_IMPORTS + "import { LOGOS } from '../../src/lib/logos.js'\nwindow.LOGOS = LOGOS\n"

CASES = (
    r"""
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const rect = (node) => { const r = node.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, w: r.width, h: r.height } }
const file = (name, size) => ({ name, size, collecting_imatrix: false, has_imatrix: false, gguf_type: null, convert_types: [] })
backend.files = %(files)s.map((name) => file(name, 5e9))
// The embedded vector as the browser keeps it, to tell which mark a node shows.
const vectorOf = (mark) => { const probe = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); probe.innerHTML = mark.html; return probe.innerHTML }
const markOf = (node) => {
  const svg = node.querySelector('svg.logo, .logo svg')
  if (svg) {
    const name = Object.keys(window.LOGOS).find((key) => vectorOf(window.LOGOS[key]) === svg.innerHTML)
    return { mark: name || 'unknown', letter: null, size: svg.getAttribute('width') }
  }
  const letter = node.querySelector('.letter')
  return { mark: null, letter: letter ? letter.textContent : null, size: null }
}
const block = () => document.querySelector('section.block')
const shown = () => text(block().querySelector('.kopf .feld .text'))

await show('page')
await wait(1800)
const heads = [...document.querySelectorAll('section.abschnitt, section.block')]
report.order = heads.map((c) => ({ block: c.matches('.block'), head: text(c.querySelector('.kopf')), ...rect(c) }))

// --- The choice at the head of the values ---
report.start = { shown: shown(), asked: [...backend.asked], fields: block().querySelectorAll('.karte .zeile').length > 0 }
block().querySelector('.kopf button[role="combobox"]').click()
await wait(400)
report.choice = [...document.querySelectorAll('[role="option"]')].map((o) => ({ text: text(o).replace(/^[A-Z] /, ''), ...markOf(o) }))
document.body.click()
await wait(200)

// --- The list: folded, then open ---
const list = () => heads.find((c) => text(c.querySelector('.kopf')) === %(table)s)
report.folded = { expanded: list().querySelector('.kopf.klapp').getAttribute('aria-expanded'), rows: list().querySelectorAll('.zeile').length }
list().querySelector('.kopf.klapp').click()
await wait(400)
report.rows = [...list().querySelectorAll('.datei-zeile')].map((row) => ({
  name: text(row.querySelector('.dateiname')), buttons: row.querySelectorAll('button').length, ...markOf(row.querySelector('.datei')),
  box: rect(row.querySelector('.datei .logo')).w,
}))
list().querySelector('.kopf.klapp').click()
await wait(200)

// --- Another model: its values are read, the audio VAE stands beside the VAE ---
const choose = async (name) => {
  block().querySelector('.kopf button[role="combobox"]').click()
  await wait(300)
  ;[...document.querySelectorAll('[role="option"]')].find((o) => text(o).endsWith(name)).click()
  await wait(900)
}
const kitRows = () => {
  const kit = block().querySelector('.kitkopf')
  if (kit.getAttribute('aria-expanded') !== 'true') kit.click()
  return null
}
const kitNames = () => [...block().querySelectorAll('.karte .zeile .name')].map((n) => text(n))
const before = backend.asked.length
await choose('ltx-2.3.safetensors')
report.ltx = { shown: shown(), asked: backend.asked.slice(before) }
kitRows()
await wait(400)
report.ltx.names = kitNames()
const row = [...block().querySelectorAll('.karte .zeile')].find((r) => text(r.querySelector('.name') || document.body) === %(audio)s)
row.querySelector('button[role="combobox"]').click()
await wait(300)
;[...document.querySelectorAll('[role="option"]')].find((o) => text(o) === %(audio_file)s).click()
await wait(300)
const calls = backend.calls.length
block().querySelectorAll('.kopf .signs button')[1].click()
await wait(700)
report.ltx.saved = backend.calls.slice(calls).map((c) => c.sent)

// --- Silence: a model without an audio VAE shows the VAE alone ---
await choose('sdxl-base.safetensors')
kitRows()
await wait(400)
report.sdxl = { shown: shown(), names: kitNames() }
"""
    % {
        "files": json.dumps(list(FILES)),
        "table": json.dumps(GERMAN["bildserver"]["bildmodelle_im_ordner"]),
        "audio": json.dumps(GERMAN["bild"]["audio_vae"]),
        "audio_file": json.dumps(AUDIO_VAE),
    }
)


@pytest.fixture(scope="module")
def report() -> dict:
    shell = (
        harness.SHELL.replace(
            "  import { scene } from './scene.svelte.js'\n", SHELL_IMPORTS + "  import { scene } from './scene.svelte.js'\n"
        )
        .replace("  {#if scene.show === 'values'}", SHELL_SCENES + "  {#if scene.show === 'values'}")
        .replace("width: 760px", "width: 1180px")
    )
    entry = harness.ENTRY_JS.replace(
        "import '../../src/stil/global.css'\n", "import '../../src/stil/global.css'\n" + PAGE_IMPORTS
    ).replace(
        "  if (path === '/bild/devices') return answer([])\n", PAGE_ROUTES + "  if (path === '/bild/devices') return answer([])\n"
    )
    entry = entry.replace("  calls: [],\n  delay: 0,\n}", "  calls: [],\n  delay: 0,\n  files: [],\n  update: false,\n}")
    page = harness.PAGE.replace(
        '<script src="out/entry.js"></script>',
        '<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">\n<script src="out/entry.js"></script>',
    )
    with (
        mock.patch.object(harness, "SHELL", shell),
        mock.patch.object(harness, "ENTRY_JS", entry),
        mock.patch.object(harness, "PAGE", page),
    ):
        return run_cases(CASES, limit=240.0, window="1500,3000")


@pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only")
@needs_browser
class TestInTheBrowser:
    def test_the_values_block_stands_before_the_conversion_and_the_list(self, report):
        order = report["order"]
        block = next(c for c in order if c["block"])
        convert = next(c for c in order if c["head"].startswith(GERMAN["bildserver"]["gguf_konvertierung"]))
        table = next(c for c in order if c["head"].startswith(GERMAN["bildserver"]["bildmodelle_im_ordner"]))
        assert block["bottom"] <= convert["top"] + 1 and convert["bottom"] <= table["top"] + 1

    def test_the_choice_shows_the_default_model_and_its_values_are_read_at_once(self, report):
        start = report["start"]
        assert start["shown"] == DEFAULT_MODEL
        assert start["asked"] == [DEFAULT_MODEL]

    def test_a_change_of_the_choice_reads_the_values_of_the_new_model(self, report):
        assert report["ltx"]["shown"] == "ltx-2.3.safetensors"
        assert report["ltx"]["asked"] == ["ltx-2.3.safetensors"]

    def test_the_list_is_closed_to_begin_with_and_no_row_has_an_arrow(self, report):
        assert report["folded"] == {"expanded": "false", "rows": 0}
        assert [row["buttons"] for row in report["rows"]] == [0, 0, 0, 0]

    def test_a_family_shows_the_mark_of_its_maker(self, report):
        marks = {row["name"]: (row["mark"], row["letter"]) for row in report["rows"]}
        assert marks["qwen-image-Q4.gguf"] == ("qwen", None)
        assert marks["mage-flow.safetensors"] == ("microsoft", None)
        assert marks[DEFAULT_MODEL] == ("stabilityai", None)
        assert marks["ltx-2.3.safetensors"] == ("lightricks", None)

    def test_the_marks_in_the_list_are_22_wide(self, report):
        assert {row["box"] for row in report["rows"]} == {22}

    def test_every_entry_of_the_choice_shows_the_same_mark_as_its_row(self, report):
        rows = {row["name"]: (row["mark"], row["letter"]) for row in report["rows"]}
        choice = {entry["text"]: (entry["mark"], entry["letter"]) for entry in report["choice"]}
        assert choice.keys() == rows.keys(), (choice, rows)
        for name, mark in rows.items():
            assert choice[name][0] == mark[0], name
            if mark[0] is None:
                assert choice[name][1] == mark[1], name

    def test_a_ltx_model_shows_two_fields_the_video_vae_and_the_audio_vae(self, report):
        names = report["ltx"]["names"]
        assert "VAE" in names and GERMAN["bild"]["audio_vae"] in names, names

    def test_saving_stores_the_audio_vae_and_nothing_else(self, report):
        assert report["ltx"]["saved"] == [{"ltx-2.3.safetensors": {"audio_vae": AUDIO_VAE}}]

    def test_silence_an_sdxl_model_shows_the_vae_alone(self, report):
        sdxl = report["sdxl"]
        assert sdxl["shown"] == DEFAULT_MODEL
        assert "VAE" in sdxl["names"] and GERMAN["bild"]["audio_vae"] not in sdxl["names"], sdxl["names"]
