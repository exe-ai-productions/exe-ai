"""On the picture server page the open model stands as two cards, Parameters and
Model, and the sd.cpp switches close the sd.cpp section, in a real browser.

The real page is built as shipped on the stub of ``tests/image_window_page.py``
(widened by the routes of the model files and the generator, like
``tests/test_image_server_layout_chrome.py``) at 1500 px. Under the head of the
model's values, which carries the choice of the model and the signs reset and
save, two cards stand side by side, each with its sign and its name, ending on one line; the
rows of a kind are equally tall. The kit of the model is the last row of the
Model card and stands folded. The fold of the sd.cpp switches is the last row
of the sd.cpp section and no longer stands in memory and devices; opened, it
shows the switches it showed before. Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from tests import image_window_page as harness
from tests.image_window_page import needs_browser, run_cases
from tests.test_image_server_layout_chrome import (
    ENTRY_IMPORTS,
    ROUTES,
    SHELL_IMPORTS,
    SHELL_SCENES,
)

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

ROOT = Path(__file__).resolve().parent.parent
GERMAN = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))

CASES = r"""
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const rect = (node) => { const r = node.getBoundingClientRect(); return { w: r.width, h: r.height, top: r.top, left: r.left, right: r.right, bottom: r.bottom } }
const cards = () => [...document.querySelectorAll('section.abschnitt, section.block')]
// The values block names its model in the choice at its head's left end.
const headOf = (card) => (card.matches('.block') ? text(card.querySelector('.kopf .feld .text')) : text(card.querySelector('.kopf')))
const card = (head) => cards().find((c) => headOf(c) === head)
const file = (name, size) => ({ name, size, collecting_imatrix: false, has_imatrix: false, gguf_type: null, convert_types: [] })
backend.files = [file('a.safetensors', 6.9e9), file('b.safetensors', 7.2e9)]

await show('page')
await wait(1800)
const switchTable = await (await fetch('/api/v1/bild/switches')).json()
report.memorySwitches = switchTable.switches.filter((row) => row.group === 'memory').length

const values = card('a.safetensors')
const inner = [...values.querySelectorAll('section.abschnitt')]
const rowsOf = (section) => [...section.querySelector('.karte').children].filter((n) => n.classList.contains('zeile'))
const rowLook = (row) => ({ cls: [...row.classList].filter((c) => !c.startsWith('svelte-')).sort().join(' '), h: rect(row).h })
report.values = {
  head: rect(values.querySelector('.kopf')), headText: headOf(values),
  hasCardOfItsOwn: Boolean(values.querySelector(':scope > .karte')),
  inner: inner.map((section) => ({
    head: headOf(section), headBox: rect(section.querySelector('.kopf')), sign: Boolean(section.querySelector('.kopf .zeichen svg')),
    card: rect(section.querySelector('.karte')), rows: rowsOf(section).map(rowLook),
    cardChildrenAreRows: [...section.querySelector('.karte').children].every((n) => n.classList.contains('zeile')),
  })),
}
const model = inner[1]
report.kit = { lastIsKit: false, folded: false, folder: false, expanded: null, rowsAfterOpen: 0, rowsBeforeOpen: 0 }
report.afterOpen = { parameters: { bottom: 0 }, model: { bottom: 1e6 } }
if (model) {
  const lastRow = rowsOf(model).slice(-1)[0]
  report.kit = {
    folded: !lastRow.nextElementSibling, lastIsKit: Boolean(lastRow.querySelector('.kitkopf')),
    expanded: lastRow.querySelector('.kitkopf')?.getAttribute('aria-expanded') ?? null,
    folder: Boolean(lastRow.querySelector('.foldersign')),
  }
  if (lastRow.querySelector('.kitkopf')) {
    lastRow.querySelector('.kitkopf').click()
    await wait(300)
    report.kit.rowsAfterOpen = rowsOf(model).length
    report.kit.rowsBeforeOpen = report.values.inner[1].rows.length
    report.afterOpen = { parameters: rect(inner[0].querySelector('.karte')), model: rect(model.querySelector('.karte')) }
    lastRow.querySelector('.kitkopf').click()
    await wait(300)
  }
}

// The sd.cpp section: the fold of the switches is its last row.
const sd = card('sd.cpp')
const sdRows = rowsOf(sd)
const foldRow = sdRows.slice(-1)[0]
const foldButton = sd.querySelector('.klappe')
const devices = cards().find((c) => headOf(c).startsWith('__DEVICES__'))
report.sd = {
  lastIsFold: Boolean(foldRow && foldRow.querySelector('.klappe')), foldText: foldRow ? text(foldRow) : '',
  nothingFollowsClosed: Boolean(foldRow) && !foldRow.nextElementSibling,
  fromDevices: devices ? Boolean(devices.querySelector('.klappe')) : null, devicesFound: Boolean(devices),
  inSd: Boolean(sd.querySelector('.klappe')),
}
report.sd.opened = { rows: 0, expanded: null }
if (foldButton) {
  foldButton.click()
  await wait(400)
  report.sd.opened = { rows: sd.querySelectorAll('.switchrow').length, expanded: foldButton.getAttribute('aria-expanded') }
}
report.sd.fromDevicesOpened = devices ? devices.querySelectorAll('.switchrow').length : null
"""


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
        "import '../../src/stil/global.css'\n", "import '../../src/stil/global.css'\n" + ENTRY_IMPORTS
    ).replace(
        "  if (path === '/bild/devices') return answer([])\n", ROUTES + "  if (path === '/bild/devices') return answer([])\n"
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
        return run_cases(CASES.replace("__DEVICES__", GERMAN["bild"]["gruppe_speicher"]), limit=240.0, window="1500,3000")


PARAMETERS = GERMAN["sprachserver"]["gruppe_parameter"]
MODEL = GERMAN["bildserver"]["modell_spalte"]
SWITCHES = GERMAN["bildserver"]["sdcpp_schalter"]


def _card(report: dict, head: str) -> dict:
    return next(card for card in report["values"]["inner"] if card["head"] == head)


# --- Two cards under the head of the model ---


def test_under_the_head_of_the_model_stand_two_cards_named_parameters_and_model(report):
    values = report["values"]
    assert values["headText"] == "a.safetensors" and values["hasCardOfItsOwn"] is False, values
    assert [card["head"] for card in values["inner"]] == [PARAMETERS, MODEL], values["inner"]
    for card in values["inner"]:
        assert card["sign"] is True, card
        assert card["cardChildrenAreRows"] is True, card


def test_the_cards_stand_side_by_side_and_their_lower_edges_lie_on_one_line(report):
    parameters, model = _card(report, PARAMETERS), _card(report, MODEL)
    assert model["card"]["left"] >= parameters["card"]["right"] + 10, (parameters["card"], model["card"])
    assert abs(model["headBox"]["top"] - parameters["headBox"]["top"]) <= 1
    assert abs(model["card"]["bottom"] - parameters["card"]["bottom"]) <= 1, (parameters["card"], model["card"])
    assert abs(model["card"]["h"] - parameters["card"]["h"]) <= 1
    # Under the head of the model, which carries the signs.
    assert parameters["headBox"]["top"] >= report["values"]["head"]["bottom"] - 1


def test_the_rows_of_one_kind_are_equally_tall(report):
    for head in (PARAMETERS, MODEL):
        kinds: dict[str, list[float]] = {}
        for row in _card(report, head)["rows"]:
            kinds.setdefault(row["cls"], []).append(row["h"])
        for cls, heights in kinds.items():
            assert max(heights) - min(heights) <= 1.5, (head, cls, heights)


# --- The kit is the last row of the Model card ---


def test_the_kit_is_the_last_row_of_the_model_card_folded_with_the_sign_of_its_folder(report):
    kit = report["kit"]
    assert kit["lastIsKit"] is True and kit["folded"] is True and kit["folder"] is True, kit
    assert kit["expanded"] == "false", kit
    assert kit["rowsAfterOpen"] > kit["rowsBeforeOpen"], kit


def test_opening_the_kit_does_not_pull_the_two_cards_apart(report):
    after = report["afterOpen"]
    assert abs(after["parameters"]["bottom"] - after["model"]["bottom"]) <= 1, after


# --- The sd.cpp switches close the sd.cpp section ---


def test_the_fold_of_the_switches_is_the_last_row_of_the_sd_cpp_section(report):
    sd = report["sd"]
    assert sd["lastIsFold"] is True and sd["nothingFollowsClosed"] is True, sd
    assert SWITCHES in sd["foldText"] and str(report["memorySwitches"]) in sd["foldText"], sd


def test_the_fold_no_longer_stands_in_memory_and_devices(report):
    sd = report["sd"]
    assert sd["devicesFound"] is True and sd["fromDevices"] is False, sd
    assert sd["fromDevicesOpened"] == 0, sd


def test_opened_the_fold_shows_the_switches_it_showed_before(report):
    opened = report["sd"]["opened"]
    assert opened["expanded"] == "true", opened
    assert opened["rows"] == report["memorySwitches"] > 0, (opened, report["memorySwitches"])
