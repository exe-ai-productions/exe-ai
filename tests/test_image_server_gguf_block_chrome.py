"""The picture server's "Convert to GGUF" block and the list of its model
files, in a real browser: the block has the file, the weight type with the
sign that converts, and the Imatrix row with its sentence, its folder button
and the one switch — nothing of it hangs at a file; the files stand in a folding
row of their own, closed to begin with, with the columns file, family, size
and state, the state as chips in the colour of what they say, no "···" at a
file and no arrow (a row opens nothing); on the whole page the block stands
under the model and the prompt preparation and the list under the block, not
in the model card.

The real parts are built as shipped on the stub of ``tests/image_window_page.py``,
which this file widens by the routes of the model files, converting, the matrix
switch and the folder (nothing in the shared file changes). Skipped where there
is no Chrome or no node.
"""

from __future__ import annotations

from unittest import mock

import pytest

from tests import image_window_page as harness
from tests.image_window_page import needs_browser, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

SHELL_IMPORTS = """  import { loadImageFiles } from '../../src/lib/imageModelFiles.svelte.js'
  import ImageConvert from '../../src/teile/ImageConvert.svelte'
  import ImageServerFiles from '../../src/teile/ImageServerFiles.svelte'
  import Bildserver from '../../src/teile/Bildserver.svelte'
"""

SHELL_SCENES = """  {#key scene.show}{#if scene.show === 'convert' || scene.show === 'files'}{void loadImageFiles()}{/if}{/key}
  {#if scene.show === 'convert'}<ImageConvert />{/if}
  {#if scene.show === 'files'}<ImageServerFiles familien={{ 'a.safetensors': 'sdxl' }} />{/if}
  {#if scene.show === 'page'}<Bildserver />{/if}
"""

ENTRY_IMPORTS = """import { texte } from '../../src/lib/texte.svelte.js'
import german from '../../../app/locales/de.json'
texte.katalog = german
window.__meldungen = meldungen
texte.sprache = 'de'
"""

ROUTES = """  if (path === '/bild/model-files') return answer(structuredClone(backend.files))
  if (path === '/bild/convert' && method === 'POST') {
    const sent = JSON.parse(options.body)
    backend.calls.push({ key: 'convert', sent })
    if (backend.running) {
      // A conversion that runs until the stop is asked for: answered 499, as a stopped picture is.
      await new Promise((resolve) => { backend.release = resolve })
      backend.running = false
      return answer({ detail: 'stopped' }, 499)
    }
    return answer({ file: sent.model.replace(/\\.[^.]+$/, '') + '.' + sent.weight_type + '.gguf' })
  }
  if (path === '/bild/convert-fp16' && method === 'POST') {
    const sent = JSON.parse(options.body)
    backend.calls.push({ key: 'convert-fp16', sent })
    if (backend.running) {
      await new Promise((resolve) => { backend.release = resolve })
      backend.running = false
      return answer({ detail: 'stopped' }, 499)
    }
    return answer({ file: sent.model.replace(/\\.[^.]+$/, '') + '.fp16.safetensors', capped: backend.capped ?? 0 })
  }
  if (path === '/bild/fortschritt') {
    return answer({ laeuft: backend.running, anteil: 0.6, schritt: 6, gesamt: 10, preview: 0 })
  }
  if (path === '/bild/stop' && method === 'POST') {
    backend.calls.push({ key: 'stop' })
    backend.release?.()
    return answer({})
  }
  if (path === '/bild/imatrix' && method === 'POST') {
    const sent = JSON.parse(options.body)
    backend.calls.push({ key: 'imatrix', sent })
    if (backend.imatrixFails) return answer({ detail: 'refused' }, 500)
    backend.settings.bildgeraete.imatrix = sent.on
    backend.files.forEach((file) => { file.collecting_imatrix = sent.on })
    return answer(sent.on)
  }
  if (path === '/bild/folder' && method === 'POST') {
    backend.calls.push({ key: 'folder' })
    return answer({})
  }
  if (path === '/bild/modelle') {
    backend.modelleReads += 1
    return answer({
      modelle: backend.files.map((file) => file.name), families: { 'a.safetensors': 'sdxl' },
      programm_da: true, standardmodell: '', sizes: {},
    })
  }
  if (path === '/bild/turbo') return answer({ zustand: 'aus' })
"""

CASES = r"""
const probe = document.createElement('span')
document.body.appendChild(probe)
const colourOf = (value) => { probe.style.color = value; const read = getComputedStyle(probe).color; probe.style.color = ''; return read }
// The page loads no stylesheet of the house: the colours of the chips are set here.
document.documentElement.style.setProperty('--gruen-text', 'rgb(10, 200, 10)')
document.documentElement.style.setProperty('--gruen', 'rgb(20, 160, 20)')
document.documentElement.style.setProperty('--text', 'rgb(230, 230, 230)')
const file = (name, size, extra = {}) => ({
  name, size, collecting_imatrix: true, has_imatrix: false, gguf_type: null, convert_types: [], ...extra,
})
backend.files = [
  file('a.safetensors', 6.9e9, { convert_types: ['q8_0', 'q4_K'] }),
  file('b.gguf', 7.2e9),
  file('c.q4_K.gguf', 1e9, { collecting_imatrix: false, gguf_type: 'q4_K' }),
]
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const rect = (node) => { const r = node.getBoundingClientRect(); return { w: r.width, h: r.height, top: r.top, left: r.left, bottom: r.bottom } }
const cards = () => [...document.querySelectorAll('section.abschnitt')]
const heads = () => cards().map((card) => text(card.querySelector('.kopf')))
const sw = () => document.querySelector('button[role="switch"]')

// --- The block ---
await show('convert')
await wait(400)
const block = cards()[0]
const rows = [...block.querySelectorAll('.karte > .zeile')]
const combos = [...block.querySelectorAll('button[role="combobox"]')]
report.block = {
  heads: heads(),
  hasSign: Boolean(block.querySelector('.kopf .zeichen svg')),
  tabs: [...block.querySelectorAll('.tab-switch button')].map((b) => [text(b), b.getAttribute('aria-pressed')]),
  rows: rows.map((row) => text(row)),
  combos: combos.map((combo) => text(combo)),
  comboWidths: combos.map((combo) => Math.round(rect(combo).w)),
  convertTitle: [...block.querySelectorAll('button.zeichenknopf')].map((b) => b.getAttribute('title')),
  buttonSize: [...block.querySelectorAll('button.zeichenknopf')].map((b) => [rect(b).w, rect(b).h]),
  switchOn: sw().getAttribute('aria-checked'),
  switchInTableOrMenu: Boolean(block.querySelector('.menue, [aria-haspopup="menu"]')),
}
// Converting asks for the shown file in the shown type.
block.querySelector('button.zeichenknopf').click()
await wait(500)
report.convertCall = backend.calls.filter((c) => c.key === 'convert').map((c) => c.sent)
// The folder button.
block.querySelectorAll('button.zeichenknopf')[1].click()
await wait(200)
report.folderCalls = backend.calls.filter((c) => c.key === 'folder').length
// A conversion that runs: the row of a running download under the weight type, the
// share the service reports, the locked fields, and the cross that asks for the stop.
backend.running = true
const runBlock = cards()[0]
runBlock.querySelector('button.zeichenknopf').click()
await wait(1600)
const runRow = runBlock.querySelector('.zeile.running')
report.running = {
  row: Boolean(runRow),
  text: runRow ? text(runRow) : '',
  fill: runRow ? runRow.querySelector('.bar i').style.width : '',
  buttons: runRow ? runRow.querySelectorAll('button').length : 0,
  after: runRow ? Boolean(runBlock.querySelectorAll('.karte > .zeile')[1].compareDocumentPosition(runRow) & Node.DOCUMENT_POSITION_FOLLOWING) : false,
  locked: [...runBlock.querySelectorAll('button[role="combobox"]')].map((combo) => combo.disabled),
  startLocked: runBlock.querySelector('button.zeichenknopf').disabled,
}
const readsBeforeStop = backend.modelleReads
const noticesBeforeStop = window.__meldungen.liste.map((m) => m.id)
runRow.querySelector('button').click()
await wait(800)
report.stopped = {
  row: Boolean(runBlock.querySelector('.zeile.running')),
  stopCalls: backend.calls.filter((c) => c.key === 'stop').length,
  startLocked: runBlock.querySelector('button.zeichenknopf').disabled,
  reads: backend.modelleReads - readsBeforeStop,
  notices: window.__meldungen.liste.filter((m) => !noticesBeforeStop.includes(m.id)).length,
}
// --- The FP16 tab: only a file of mostly BF16, no weight type, no matrix ---
backend.files[0].fp16_convertible = true
backend.files.push(file('e.safetensors', 5e9, { fp16_convertible: true }))
await show('files')
await show('convert')
await wait(400)
const tabButtons = () => [...cards()[0].querySelectorAll('.tab-switch button')]
tabButtons()[1].click()
await wait(400)
const fpBlock = cards()[0]
const fpCombo = fpBlock.querySelector('button[role="combobox"]')
fpCombo.click()
await wait(300)
const fpOptions = [...document.querySelectorAll('[role="option"]')].map((o) => text(o))
document.body.click()
await wait(200)
report.fp16 = {
  tabs: tabButtons().map((b) => [text(b), b.getAttribute('aria-pressed')]),
  rows: [...fpBlock.querySelectorAll('.karte > .zeile')].map((row) => text(row)),
  combo: text(fpCombo),
  options: fpOptions,
  hasSwitch: Boolean(fpBlock.querySelector('button[role="switch"]')),
  hasWeightType: fpBlock.textContent.includes('Gewichtstyp'),
  titles: [...fpBlock.querySelectorAll('button.zeichenknopf')].map((b) => b.getAttribute('title')),
  size: [...fpBlock.querySelectorAll('button.zeichenknopf')].map((b) => [rect(b).w, rect(b).h]),
}
// Converting asks for the shown file; a copy with capped values says how many.
const noticesBefore = window.__meldungen.liste.map((m) => m.id)
backend.capped = 3
fpBlock.querySelector('button.zeichenknopf').click()
await wait(600)
report.fp16Call = backend.calls.filter((c) => c.key === 'convert-fp16').map((c) => c.sent)
const fpTexts = window.__meldungen.liste.filter((m) => !noticesBefore.includes(m.id)).map((m) => m.text)
report.fp16Notices = fpTexts
// Without a capped value nothing but the ready sentence is told.
const quietBefore = window.__meldungen.liste.map((m) => m.id)
backend.capped = 0
fpBlock.querySelector('button.zeichenknopf').click()
await wait(600)
report.fp16Quiet = window.__meldungen.liste.filter((m) => !quietBefore.includes(m.id)).map((m) => m.text)
// A conversion that runs: the same bar and cross, the stop reaches the service, the row goes.
backend.running = true
const fpRunBlock = cards()[0]
fpRunBlock.querySelector('button.zeichenknopf').click()
await wait(1600)
const fpRunRow = fpRunBlock.querySelector('.zeile.running')
report.fp16Running = {
  row: Boolean(fpRunRow),
  text: fpRunRow ? text(fpRunRow) : '',
  locked: fpRunBlock.querySelector('button[role="combobox"]').disabled,
  startLocked: fpRunBlock.querySelector('button.zeichenknopf').disabled,
}
const fpStopsBefore = backend.calls.filter((c) => c.key === 'stop').length
fpRunRow.querySelector('button').click()
await wait(800)
report.fp16Stopped = {
  row: Boolean(fpRunBlock.querySelector('.zeile.running')),
  stops: backend.calls.filter((c) => c.key === 'stop').length - fpStopsBefore,
  startLocked: fpRunBlock.querySelector('button.zeichenknopf').disabled,
}
backend.files.pop()
backend.files[0].fp16_convertible = false
tabButtons()[0].click()
await wait(300)
report.backToGguf = [...cards()[0].querySelectorAll('.karte > .zeile')].map((row) => text(row).split(' ')[0])

// The switch: off, kept, and back on.
sw().click()
await wait(500)
report.off = { state: sw().getAttribute('aria-checked'), sent: backend.calls.filter((c) => c.key === 'imatrix').map((c) => c.sent), stored: backend.settings.bildgeraete.imatrix }
// A switch the service refuses goes back to what it was.
backend.imatrixFails = true
sw().click()
await wait(500)
report.refused = sw().getAttribute('aria-checked')
backend.imatrixFails = false
sw().click()
await wait(500)
report.on = { state: sw().getAttribute('aria-checked'), stored: backend.settings.bildgeraete.imatrix }

// --- The table ---
backend.files[2].collecting_imatrix = false
await show('files')
await wait(500)
const table = cards()[0]
// The list is a folding row: closed to begin with, no row drawn.
report.folded = {
  expanded: table.querySelector('.kopf.klapp')?.getAttribute('aria-expanded') ?? null,
  rows: table.querySelectorAll('.zeile').length,
}
table.querySelector('.kopf.klapp').click()
await wait(400)
const tableRows = [...table.querySelectorAll('.karte > .zeile')]
const chips = (row) => [...row.querySelectorAll('.chip')].map((chip) => text(chip))
const chipLook = (chip) => {
  const style = getComputedStyle(chip)
  return { h: rect(chip).h, padding: style.padding, radius: style.borderTopLeftRadius, size: style.fontSize, weight: style.fontWeight, colour: style.color, ground: style.backgroundColor }
}
report.table = {
  head: text(table.querySelector('.kopf')),
  expanded: table.querySelector('.kopf.klapp')?.getAttribute('aria-expanded') ?? null,
  headerCells: [...tableRows[0].children].map((cell) => text(cell)),
  headerHeight: rect(tableRows[0]).h,
  rowHeights: tableRows.slice(1).map((row) => rect(row).h),
  rowNames: tableRows.slice(1).map((row) => text(row.querySelector('.dateiname'))),
  families: tableRows.slice(1).map((row) => text(row.querySelector('.familie'))),
  sizes: tableRows.slice(1).map((row) => text(row.querySelector('.groesse'))),
  chips: tableRows.slice(1).map(chips),
  arrows: table.querySelectorAll('button.pfeil').length,
  menus: table.querySelectorAll('.menue, [aria-haspopup="menu"]').length,
  dots: table.textContent.includes('···'),
  imatrixChip: chipLook(table.querySelector('.chip.imatrix')),
  ggufChip: chipLook(table.querySelector('.chip.gguf')),
  green: colourOf('rgb(10, 200, 10)'),
  text: colourOf('rgb(230, 230, 230)'),
}
// A row opens nothing: the values of a model stand at the top of the page.
tableRows[1].click()
tableRows[1].querySelector('.dateiname').click()
await wait(400)
report.rowClick = { sections: cards().length, buttons: tableRows[1].querySelectorAll('button').length }

// --- The whole page ---
await show('page')
await wait(1200)
const page = cards()
report.page = {
  heads: heads(),
  modelCard: text(page[0].querySelector('.karte')),
}
// A conversion that ends well makes the page read its state again, the list of the
// default model among it; one that was stopped reads nothing.
const readsBefore = backend.modelleReads
document.querySelector('button.zeichenknopf[title="In GGUF umwandeln"]').click()
await wait(800)
report.pageReads = backend.modelleReads - readsBefore

"""

# An ENTRY with the routes and the texts: the harness' own stand-in stays as it is.
ENTRY_ANCHORS = (
    "import '../../src/stil/global.css'\n",
    "  if (path === '/bild/devices') return answer([])\n",
)


@pytest.fixture(scope="module")
def report() -> dict:
    for anchor in ENTRY_ANCHORS:
        assert anchor in harness.ENTRY_JS, f"the shared harness changed, widen it again: {anchor!r}"
    for anchor in (
        "  import { scene } from './scene.svelte.js'\n",
        "  {#if scene.show === 'values'}",
    ):
        assert anchor in harness.SHELL, f"the shared harness changed, widen it again: {anchor!r}"
    shell = harness.SHELL.replace(
        "  import { scene } from './scene.svelte.js'\n", SHELL_IMPORTS + "  import { scene } from './scene.svelte.js'\n"
    ).replace("  {#if scene.show === 'values'}", SHELL_SCENES + "  {#if scene.show === 'values'}")
    entry = harness.ENTRY_JS.replace(
        "import '../../src/stil/global.css'\n", "import '../../src/stil/global.css'\n" + ENTRY_IMPORTS
    ).replace(
        "  if (path === '/bild/devices') return answer([])\n", ROUTES + "  if (path === '/bild/devices') return answer([])\n"
    )
    # The stub's settings hold the machine's picture row; the files list is the stub's own.
    entry = entry.replace("  calls: [],\n  delay: 0,\n}", "  calls: [],\n  delay: 0,\n  files: [],\n  imatrixFails: false,\n  running: false,\n  release: null,\n  modelleReads: 0,\n}")
    assert "modelleReads: 0" in entry and "texte.katalog = german" in entry
    with mock.patch.object(harness, "SHELL", shell), mock.patch.object(harness, "ENTRY_JS", entry):
        return run_cases(CASES, limit=180.0)


# --- The block ---


def test_the_block_has_the_file_the_weight_type_the_sign_and_the_imatrix_row(report):
    block = report["block"]
    assert block["heads"][0] == "GGUF-Konvertierung" and block["hasSign"] is True
    # The tabs head the card, GGUF pressed; then the rows of the GGUF tab.
    assert block["tabs"] == [["GGUF", "true"], ["FP16", "false"]]
    assert [row.split(" ")[0] for row in block["rows"][1:]] == ["Datei", "Gewichtstyp", "Imatrix"]
    # The first file a smaller copy is possible from, with the first of its types.
    assert block["combos"] == ["a.safetensors", "q8_0"]
    assert block["comboWidths"][0] == 300 and block["comboWidths"][1] == 160


def test_the_sentence_stands_under_imatrix_and_the_buttons_are_34_signs_with_tooltips(report):
    block = report["block"]
    assert block["rows"][3].startswith("Imatrix Um Daten für eine Imatrix-Quantisierung zu erhalten, bitte vor dem Umwandeln nach GGUF mindestens fünf Bilder zeichnen.")
    assert block["convertTitle"] == ["In GGUF umwandeln", "Ordner öffnen"]
    assert block["buttonSize"] == [[34, 34], [34, 34]]
    assert block["switchInTableOrMenu"] is False


def test_the_switch_is_on_from_the_start_and_is_one_for_all_files(report):
    assert report["block"]["switchOn"] == "true"
    assert report["off"]["state"] == "false"
    # No file name goes with it, and the machine's setting holds it.
    assert report["off"]["sent"] == [{"on": False}, ] or report["off"]["sent"][0] == {"on": False}
    assert report["off"]["stored"] is False
    assert report["on"] == {"state": "true", "stored": True}


def test_a_switch_the_service_refuses_goes_back_to_what_it_was(report):
    assert report["refused"] == "false"


def test_converting_asks_for_the_shown_file_in_the_shown_type(report):
    assert report["convertCall"] == [{"model": "a.safetensors", "weight_type": "q8_0"}]


def test_the_folder_button_opens_the_model_folder(report):
    assert report["folderCalls"] == 1


# --- The table ---


def test_the_list_is_closed_to_begin_with_and_its_rows_come_with_the_press_on_its_head(report):
    assert report["folded"] == {"expanded": "false", "rows": 0}
    assert report["table"]["expanded"] == "true"


def test_the_table_has_its_head_the_four_columns_and_no_arrow_at_a_file(report):
    table = report["table"]
    assert table["head"] == "Bildmodelle im Ordner"
    # Four columns, every one with its word: the empty column of the arrow is gone.
    assert len(table["headerCells"]) == 4 and all(table["headerCells"]), table["headerCells"]
    assert table["arrows"] == 0
    assert table["rowNames"] == ["a.safetensors", "b.gguf", "c.q4_K.gguf"]
    assert table["sizes"] == ["6,9 GB", "7,2 GB", "1,0 GB"]


def test_no_dots_menu_stands_at_a_file(report):
    assert report["table"]["menus"] == 0 and report["table"]["dots"] is False


def test_the_rows_are_56_and_the_head_row_40_high(report):
    assert report["table"]["headerHeight"] == 40
    assert report["table"]["rowHeights"] == [56, 56, 56]


def test_the_state_column_names_what_is_collected_and_the_type_of_a_converted_file(report):
    chips = report["table"]["chips"]
    # The source of a conversion carries no GGUF chip, whatever copy lies beside it.
    assert chips[0] == ["Imatrix wird analysiert"]
    assert chips[1] == ["Imatrix wird analysiert"]
    # The file a conversion wrote carries the chip with its type.
    assert chips[2] == ["GGUF q4_K"]


def test_the_chips_are_19_high_with_padding_2_8_radius_5_12_px_semibold_in_the_colour_of_their_word(report):
    table = report["table"]
    for chip in (table["imatrixChip"], table["ggufChip"]):
        assert (chip["h"], chip["padding"], chip["radius"], chip["size"], chip["weight"]) == (19, "2px 8px", "5px", "12px", "600")
        assert chip["ground"] != "rgba(0, 0, 0, 0)", chip
    assert table["imatrixChip"]["colour"] == table["green"]
    assert table["ggufChip"]["colour"] == table["text"]


def test_a_row_of_the_list_opens_nothing_and_has_no_button(report):
    # Only the list's own section stands there after a press on a row.
    assert report["rowClick"] == {"sections": 1, "buttons": 0}


# --- The whole page ---


def test_the_block_stands_under_the_model_and_the_preparation_and_the_table_under_the_block(report):
    heads = report["page"]["heads"]
    assert heads[0].startswith("Bildmodell")
    convert = heads.index("GGUF-Konvertierung")
    table = heads.index("Bildmodelle im Ordner")
    # The generator stands under the table, the card with the idle time under
    # the generator, the log at the foot.
    assert heads.index("Prompt-Aufbereitung") < convert < table < heads.index("sd.cpp") == len(heads) - 2
    assert heads[-1] == "Erweitert"


def test_the_files_do_not_stand_in_the_model_card(report):
    card = report["page"]["modelCard"]
    assert "a.safetensors" not in card and "b.gguf" not in card


# --- A conversion that runs ---


def test_a_running_conversion_shows_the_bar_the_percent_and_the_cross_under_the_weight_type(report):
    running = report["running"]
    assert running["row"] is True
    assert running["text"] == "60 %"
    assert running["fill"] == "60%"
    assert running["buttons"] == 1
    assert running["after"] is True
    # The fields and the sign stay shut while it runs, as before.
    assert running["locked"] == [True, True] and running["startLocked"] is True


def test_the_cross_asks_for_the_stop_and_the_row_goes_quietly(report):
    stopped = report["stopped"]
    assert stopped["stopCalls"] == 1
    assert stopped["row"] is False
    assert stopped["startLocked"] is False
    # Stopped is no failure and no success: nothing is told and nothing is read again.
    assert stopped["notices"] == 0
    assert stopped["reads"] == 0


def test_a_conversion_that_ends_well_makes_the_page_read_its_state_again(report):
    assert report["pageReads"] >= 1


def test_the_fp16_tab_offers_only_the_files_of_mostly_bf16_and_has_no_type_and_no_matrix(report):
    fp16 = report["fp16"]
    assert fp16["tabs"] == [["GGUF", "false"], ["FP16", "true"]]
    assert [row.split(" ")[0] for row in fp16["rows"][1:]] == ["Datei"]
    assert fp16["combo"] == "a.safetensors"
    assert fp16["options"] == ["a.safetensors", "e.safetensors"]
    assert fp16["hasSwitch"] is False and fp16["hasWeightType"] is False
    # One sign, the size of the others, with its own tooltip.
    assert fp16["titles"] == ["In FP16 umwandeln"]
    assert fp16["size"] == [[34, 34]]
    assert report["backToGguf"] == ["GGUFFP16", "Datei", "Gewichtstyp", "Imatrix"]


def test_the_fp16_sign_asks_for_the_shown_file_and_tells_the_capped_values(report):
    assert report["fp16Call"][0] == {"model": "a.safetensors"}
    assert any("3 Werte lagen außerhalb des FP16-Bereichs" in text for text in report["fp16Notices"])
    assert any("a.fp16.safetensors" in text for text in report["fp16Notices"])
    # Silence: nothing capped, only the ready sentence.
    assert len(report["fp16Quiet"]) == 1 and "fp16.safetensors" in report["fp16Quiet"][0]


def test_the_fp16_tab_shows_the_same_bar_and_the_cross_asks_for_the_stop(report):
    running = report["fp16Running"]
    assert running["row"] is True and "60 %" in running["text"]
    assert running["locked"] is True and running["startLocked"] is True
    stopped = report["fp16Stopped"]
    assert stopped["row"] is False and stopped["stops"] == 1
    assert stopped["startLocked"] is False
