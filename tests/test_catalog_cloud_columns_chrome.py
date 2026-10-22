"""The page's own left column of the catalogue and of the cloud menu, drawn as
shipped in headless Chrome: rows 40 px high with an 18 px sign in the quiet ink,
the name in full ink, 13 px and medium (the chosen row semibold on the button
glass); the column padded 16 px above and 10 px at the sides (the cloud card 6 and 10 under its
heading, which stands over it like the table's); in the catalogue
the line between the kinds and the downloads and the quiet blue number of the
downloads; in the cloud menu the heading over the card, the counts in 11 px, the model
rows 32 px high under their provider's name, the tick in a 22 px box and the way
to a new provider as a 40 px row. The rows of the other lists keep their size.

The two pages are built as the tests of their lists build them
(`tests/test_catalog_settings_list_chrome.py`,
`tests/test_cloud_settings_list_chrome.py`); the service is not asked — the
pages answer every request themselves. Skipped where there is no Chrome or no
node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_catalog_settings_list_chrome as catalogue_page
from tests import test_cloud_settings_list_chrome as cloud_page

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

# What both pages measure the same way.
HELPERS = r"""
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const rect = (node) => { const r = node.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height } }
const ink = (token) => {
  const probe = document.createElement('span')
  probe.style.color = `var(${token})`
  document.body.appendChild(probe)
  const color = getComputedStyle(probe).color
  probe.remove()
  return color
}
const rowFacts = (row) => {
  const title = getComputedStyle(row.querySelector('.titel'))
  const sign = row.querySelector('.zeichen')
  const box = rect(sign)
  return {
    height: rect(row).height, sign: [box.width, box.height], signColor: getComputedStyle(sign).color,
    titleSize: title.fontSize, titleWeight: title.fontWeight, titleColor: title.color,
    radius: getComputedStyle(row).borderTopLeftRadius, padding: getComputedStyle(row).padding,
    gap: getComputedStyle(row).columnGap, background: getComputedStyle(row).backgroundColor,
    chosen: row.getAttribute('aria-current') === 'true',
  }
}
"""

CATALOGUE_CASES = HELPERS + r"""
const report = {}
for (let k = 0; k < 100 && !document.querySelector('.chatkopf'); k += 1) await wait(100)
await wait(600)
window.__show('katalog')
await wait(900)
// Something runs, so the downloads row carries its number.
// The page asks the service and the page's stand-in answers.
window.__scenario.stand = { datei: 'a.gguf', geladen: 1, gesamt: 10, anteil: 0.1, fertig: false, fehler: null }
window.__downloads.laufend = window.__scenario.stand
for (let k = 0; k < 40 && !document.querySelector('nav.kinds .dlzahl'); k += 1) await wait(100)
await wait(500)
const column = document.querySelector('nav.kinds')
const rows = [...column.querySelectorAll('.kind-rows .menuezeile')]
const columnStyle = getComputedStyle(column)
report.count = rows.length
report.padding = [columnStyle.paddingTop, columnStyle.paddingRight, columnStyle.paddingBottom, columnStyle.paddingLeft]
report.rows = rows.map(rowFacts)
report.titles = rows.map((row) => row.querySelector('.titel').textContent.trim())
report.ink = { text: ink('--text'), quiet: ink('--text-leise'), blue: ink('--blau-text'), glass: ink('--glass-button') }
const divider = column.querySelector('.divider')
const columnBox = rect(column)
report.divider = {
  left: rect(divider).left - columnBox.left, right: columnBox.right - rect(divider).right,
  height: rect(divider).height, marginTop: getComputedStyle(divider).marginTop, marginBottom: getComputedStyle(divider).marginBottom,
}
const number = column.querySelector('.dlzahl')
report.number = { text: number?.textContent.trim() ?? null, color: number ? getComputedStyle(number).color : null,
  size: number ? getComputedStyle(number).fontSize : null, weight: number ? getComputedStyle(number).fontWeight : null }
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

CLOUD_CASES = HELPERS + r"""
const report = {}
const side = () => document.getElementById('leiste')
const page = () => document.getElementById('seite')
const column = () => page().querySelector('nav.providers')
const rendered = () => column() && column().querySelectorAll('.menuezeile').length === 5
for (let k = 0; k < 60 && !rendered(); k += 1) await wait(100)
if (!rendered()) throw new Error('the page did not render the providers')
await wait(600)
const nav = column()
const style = getComputedStyle(nav)
report.padding = [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft]
report.ink = { text: ink('--text'), quiet: ink('--text-leise'), red: ink('--rot-text'), green: ink('--gruen'), glass: ink('--glass-button') }
const providers = [...nav.querySelectorAll('.menuezeile')]
report.providers = providers.map((row) => ({
  ...rowFacts(row), title: row.querySelector('.titel').textContent.trim(),
  titleLeft: rect(row.querySelector('.titel')).left,
  count: row.querySelector('.count') ? {
    text: row.querySelector('.count').textContent.trim().replace(/\s+/g, ' '),
    size: getComputedStyle(row.querySelector('.count')).fontSize, color: getComputedStyle(row.querySelector('.count')).color,
    missing: row.querySelector('.count').classList.contains('missing'),
  } : null,
  dot: row.querySelector('.count .lp circle') ? rect(row.querySelector('.count .lp circle')).width : null,
}))
// The heading stands over the card, as the heading of the table on the right.
const head = nav.previousElementSibling
const headStyle = getComputedStyle(head)
report.head = { text: head.textContent.trim(), cls: head.className.split(' ')[0], size: headStyle.fontSize,
  weight: headStyle.fontWeight, left: rect(head).left - rect(nav).left, gap: rect(nav).top - rect(head).bottom,
  firstRow: rect(providers[0]).top - rect(nav).top }
const models = [...nav.querySelectorAll('.listenzeile:not(.dazu)')]
report.models = models.map((row) => {
  const tick = row.querySelector('.haken')
  return {
    height: rect(row).height, padding: getComputedStyle(row).padding,
    nameLeft: rect(row.querySelector('.mname')).left, nameSize: getComputedStyle(row.querySelector('.mname')).fontSize,
    tick: [rect(tick).width, rect(tick).height], tickSign: rect(tick.querySelector('svg')).width,
    tickColor: getComputedStyle(tick).color,
  }
})
const add = nav.querySelector('.listenzeile.dazu')
const before = add.previousElementSibling
report.add = {
  height: rect(add).height, padding: getComputedStyle(add).padding, gap: getComputedStyle(add).columnGap,
  gapAbove: rect(add).top - rect(before).bottom, plus: rect(add.querySelector('.plus svg')).width,
  plusColor: getComputedStyle(add.querySelector('.plus')).color,
  nameSize: getComputedStyle(add.querySelector('.mname')).fontSize, nameWeight: getComputedStyle(add.querySelector('.mname')).fontWeight,
  nameColor: getComputedStyle(add.querySelector('.mname')).color,
}
// Silence: the settings list in the sidebar keeps its own size.
const sideRow = side().querySelector('.menuezeile')
report.sideRow = { height: rect(sideRow).height, size: getComputedStyle(sideRow.querySelector('.titel')).fontSize }
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _replaced(text: str, *changes: tuple[str, str]) -> str:
    """The sibling page with each change made — a change that finds nothing is an error."""
    for old, new in changes:
        assert old in text, f"the page of the sibling test no longer holds {old!r}"
        text = text.replace(old, new)
    return text


def _build_and_run(name: str, files: dict[str, str], page: str, size: str, query: str = "") -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-{name}-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        for file_name, content in files.items():
            (folder / file_name).write_text(content, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2500:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        assert links, "the build emitted no stylesheet: the colour probes would measure nothing"
        (folder / "measure.html").write_text(page.replace("@@LINKS@@", links), encoding="utf-8")
        port = cloud_page._free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking",
                "--allow-file-access-from-files", f"--window-size={size}", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", (folder / "measure.html").as_uri() + query,
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return asyncio.run(cloud_page._drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def catalogue() -> dict:
    page = _replaced(
        catalogue_page.PAGE,
        ('<link rel="stylesheet" href="out/style.css">', "@@LINKS@@"),
        ("@@CASES@@", CATALOGUE_CASES),
        ("width: 1280px; height: 700px", "width: 1900px; height: 1000px"),
    )
    files = {
        "entry.js": catalogue_page.ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json")),
        "vite.config.js": catalogue_page.VITE_CONFIG,
    }
    return _build_and_run("catalogue-column", files, page, "1920,1080")


@pytest.fixture(scope="module")
def cloud() -> dict:
    page = _replaced(
        cloud_page.PAGE,
        ("%(links)s", "@@LINKS@@"),
        ("%(cases)s", CLOUD_CASES),
        ("width: 1280px; position: relative", "width: 1900px; position: relative"),
    )
    files = {
        "Shell.svelte": cloud_page.SHELL
        % {"cloud": "../../src/teile/ModelleCloud.svelte", "zustand": "../../src/lib/zustand.svelte.js"},
        "entry.js": cloud_page.ENTRY_JS
        % {
            "global": "../../src/stil/global.css",
            "english": "../../../app/locales/en.json",
            "zustand": "../../src/lib/zustand.svelte.js",
            "texts": "../../src/lib/texte.svelte.js",
        },
        "vite.config.js": cloud_page.VITE_CONFIG,
    }
    return _build_and_run("cloud-column", files, page, "1920,1080", "?providers=two")


def _near(value: float, expected: float, tolerance: float = 1.0) -> bool:
    return abs(value - expected) <= tolerance


def _row_is_of_the_drawing(row: dict, ink: dict) -> None:
    assert _near(row["height"], 40), row
    assert row["sign"] == [18, 18], row
    assert row["titleSize"] == "13px", row
    assert row["titleColor"] == ink["text"], row
    assert row["signColor"] == ink["quiet"], row
    assert row["radius"] == "8px" and row["padding"] == "0px 10px" and row["gap"] == "12px", row


# --- The catalogue ------------------------------------------------------------------


def test_every_kind_and_the_downloads_row_is_40_high_with_an_18_px_sign_and_13_px_medium_name(catalogue):
    assert catalogue["count"] >= 6
    for row in catalogue["rows"]:
        _row_is_of_the_drawing(row, catalogue["ink"])
    assert catalogue["rows"][-1]["titleWeight"] in ("500", "600")
    assert catalogue["titles"][-1] == "Downloads"


def test_only_the_chosen_kind_is_semibold_and_stands_on_the_button_glass(catalogue):
    chosen = [row for row in catalogue["rows"] if row["chosen"]]
    assert len(chosen) == 1, chosen
    assert chosen[0]["titleWeight"] == "600" and chosen[0]["background"] == catalogue["ink"]["glass"], chosen
    assert all(row["titleWeight"] == "500" for row in catalogue["rows"] if not row["chosen"])


def test_the_column_is_padded_16_above_and_10_at_the_sides(catalogue):
    assert catalogue["padding"] == ["16px", "10px", "16px", "10px"]


def test_the_line_before_the_downloads_stands_10_px_from_the_sides_with_8_px_around_it(catalogue):
    divider = catalogue["divider"]
    assert _near(divider["left"], 10) and _near(divider["right"], 10) and _near(divider["height"], 1), divider
    assert divider["marginTop"] == "8px" and divider["marginBottom"] == "8px", divider


def test_the_number_of_the_downloads_is_14_px_semibold_in_the_quiet_blue(catalogue):
    number = catalogue["number"]
    assert number["text"] == "1", number
    assert number["size"] == "14px" and number["weight"] == "600", number
    assert number["color"] == catalogue["ink"]["blue"], number


# --- The cloud menu -------------------------------------------------------------------


def test_every_provider_row_is_40_high_with_an_18_px_sign_and_a_13_px_name(cloud):
    assert len(cloud["providers"]) == 5
    for row in cloud["providers"]:
        _row_is_of_the_drawing(row, cloud["ink"])


def test_the_chosen_provider_is_semibold_on_the_button_glass(cloud):
    chosen = [row for row in cloud["providers"] if row["chosen"]]
    assert len(chosen) == 1, chosen
    assert chosen[0]["titleWeight"] == "600" and chosen[0]["background"] == cloud["ink"]["glass"], chosen
    assert all(row["titleWeight"] == "500" for row in cloud["providers"] if not row["chosen"])


def test_the_card_is_padded_6_above_and_10_at_the_sides_and_the_heading_stands_over_it(cloud):
    assert cloud["padding"] == ["6px", "10px", "6px", "10px"]
    head = cloud["head"]
    # The heading of the table on the right (`tafelkopf`), over the card, 10 px away from it.
    assert head["cls"] == "tafelkopf" and head["weight"] == "600", head
    assert _near(head["left"], 0) and _near(head["gap"], 10) and _near(head["firstRow"], 6), head


def test_the_counts_are_11_px_and_a_missing_key_is_red(cloud):
    counts = [row["count"] for row in cloud["providers"] if row["count"]]
    assert counts, "no provider carries a count"
    for count in counts:
        assert count["size"] == "11px", count
    missing = [count for count in counts if count["missing"]]
    assert missing and all(count["color"] == cloud["ink"]["red"] for count in missing), counts
    dots = [row["dot"] for row in cloud["providers"] if row["dot"]]
    assert dots and all(dot == 7 for dot in dots), dots


def test_a_model_row_is_32_high_and_its_name_starts_under_the_name_of_its_provider(cloud):
    assert cloud["models"], "no chosen model under an answering provider"
    openai = next(row for row in cloud["providers"] if row["title"] == "OpenAI")
    for model in cloud["models"]:
        assert _near(model["height"], 32) and model["padding"] == "5px 10px 5px 40px", model
        assert _near(model["nameLeft"], openai["titleLeft"]), (model, openai["titleLeft"])
        assert model["nameSize"] == "12.5px", model


def test_the_tick_sits_in_a_22_px_box_with_a_14_px_sign_in_green(cloud):
    for model in cloud["models"]:
        assert model["tick"] == [22, 22] and model["tickSign"] == 14, model
        assert model["tickColor"] == cloud["ink"]["green"], model


def test_the_way_to_a_new_provider_is_a_40_px_row_two_px_under_the_row_before(cloud):
    add = cloud["add"]
    assert _near(add["height"], 40) and add["padding"] == "0px 10px" and add["gap"] == "12px", add
    assert _near(add["gapAbove"], 2), add
    assert add["plus"] == 14 and add["plusColor"] == cloud["ink"]["quiet"], add
    assert add["nameSize"] == "13px" and add["nameWeight"] == "500" and add["nameColor"] == cloud["ink"]["quiet"], add


def test_silence_the_settings_list_in_the_sidebar_keeps_its_36_px_rows(cloud):
    assert _near(cloud["sideRow"]["height"], 36) and cloud["sideRow"]["size"] == "13px", cloud["sideRow"]


def test_silence_the_phone_settings_page_asks_for_no_size():
    source = (SRC / "phone" / "pages" / "Settings.svelte").read_text(encoding="utf-8")
    assert 'size="list"' not in source and 'size="sidebar"' not in source
