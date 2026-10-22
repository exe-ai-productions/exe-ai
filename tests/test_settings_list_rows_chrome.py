"""The settings list in the sidebar, drawn as shipped in headless Chrome: rows
36 px high and as wide as the drawing, a 20 px sign, the name in 13 px (the
chosen row semibold), the value in 11 px, the dot 8 px; the heading of a group
small and semibold with the room of the drawing around it; the search field
32 px high with the field line. The rows of the other lists keep their size.

The real sidebar (`Seitenleiste.svelte`) holds the real list
(`Einstellungsliste.svelte`) as the settings page hands it over; the service's
answers are not needed. Skipped where there is no Chrome or no node, like the
other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests.model_windows_page import _free_port, _read_result

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

SHELL = """<script>
  import Seitenleiste from '../../src/teile/Seitenleiste.svelte'
  import Einstellungsliste from '../../src/teile/Einstellungsliste.svelte'
  import Menuezeile from '../../src/teile/Menuezeile.svelte'
  import Hauszeichen from '../../src/teile/Hauszeichen.svelte'
  import { zustand } from '../../src/lib/zustand.svelte.js'

  $effect(() => {
    zustand.menuSections = { snippet: settings, label: 'Settings' }
    return () => { zustand.menuSections = null }
  })
</script>

{#snippet settings()}
  <Einstellungsliste
    aktuell="konfiguration"
    wert={(id) => (id === 'sprache' ? 'Deutsch' : '')}
    punkt={(id) => (id === 'memory' ? 'gruen' : null)}
  />
{/snippet}

<div id="desktop" style="height: 900px; display: flex;"><Seitenleiste /></div>
<div id="plain" style="width: 285px; padding: 8px;">
  <div class="menuegruppe">Group</div>
  <Menuezeile titel="Plain row" wert="value" punkt="gruen">
    {#snippet zeichen()}<Hauszeichen zeichen="palette" groesse="gross" />{/snippet}
  </Menuezeile>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import german from '../../../app/locales/de.json'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand, seiteZeigen, seitenSchliessen } from '../../src/lib/zustand.svelte.js'
import '../../src/stil/global.css'

texte.katalog = german
// A look in which the field line and the button's edge differ.
document.documentElement.setAttribute('data-modus', 'hell')
// The drawing's sidebar is 285 px wide.
zustand.seitenBreite = 285
window.zustand = zustand
window.seiteZeigen = seiteZeigen
window.seitenSchliessen = seitenSchliessen
try {
  mount(Shell, { target: document.getElementById('root') })
} catch (failure) {
  window.__mountError = String(failure && failure.stack || failure)
}
"""

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  logLevel: 'error',
  build: {
    outDir: 'out',
    emptyOutDir: true,
    minify: false,
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js' },
  },
})
"""

PAGE = """<!doctype html><meta charset=utf-8><title>windows</title>
<style>body { margin: 0; background: #fff; }</style>
<div id="root"></div><pre id="ergebnis"></pre>
<script>
  window.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16)
  window.cancelAnimationFrame = (id) => clearTimeout(id)
</script>
<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      %(cases)s
    } catch (failure) {
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure) })
    }
  })
</script>
"""

CASES = r"""
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const report = {}
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const rect = (node) => { const r = node.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, width: r.width, height: r.height } }
const rowsOf = (scope) => [...scope.querySelectorAll('.menuezeile')]
await wait(500)
if (window.__mountError) throw new Error(window.__mountError)

// 1. The settings stand open in the sidebar.
window.seiteZeigen('prompt')
for (let k = 0; k < 60 && !document.querySelector('.menueliste .menuezeile'); k += 1) await wait(100)
await wait(500)
const nav = document.querySelector('.menueliste')
const rows = rowsOf(nav)
const chosen = rows.find((row) => row.getAttribute('aria-current') === 'true')
const withValue = rows.find((row) => row.querySelector('.wert'))
const withDot = rows.find((row) => row.querySelector('.punkt'))
const describe = (row) => {
  const style = getComputedStyle(row)
  const title = getComputedStyle(row.querySelector('.titel'))
  const sign = row.querySelector('.zeichen').getBoundingClientRect()
  return {
    height: rect(row).height, width: rect(row).width, left: rect(row).left,
    padding: [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft],
    gap: style.columnGap, radius: style.borderTopLeftRadius,
    sign: [sign.width, sign.height],
    titleSize: title.fontSize, titleWeight: title.fontWeight, background: style.backgroundColor,
  }
}
report.navPadding = [getComputedStyle(nav).paddingLeft, getComputedStyle(nav).paddingRight]
report.navWidth = rect(nav).width
report.rowCount = rows.length
report.rows = rows.map((row) => ({ height: rect(row).height, width: rect(row).width }))
report.first = describe(rows[0])
report.chosen = describe(chosen)
report.unchosenWeight = getComputedStyle(rows.find((row) => row !== chosen).querySelector('.titel')).fontWeight
const valueStyle = getComputedStyle(withValue.querySelector('.wert'))
report.value = { text: withValue.querySelector('.wert').textContent, size: valueStyle.fontSize, weight: valueStyle.fontWeight }
// The disc that is drawn; the box around it is a pixel wider on each side.
const dot = withDot.querySelector('.punkt circle').getBoundingClientRect()
report.dot = [dot.width, dot.height]

// 2. The headings of the groups and the room around them.
// A heading of a group is the one a list of rows follows.
const isHead = (node) => node.nextElementSibling?.classList.contains('gruppenzeilen')
const heads = [...nav.querySelectorAll('.menuegruppe')].filter(isHead)
const search = nav.querySelector('.einstellungssuche')
const headStyle = getComputedStyle(heads[0])
report.heads = {
  count: heads.length, size: headStyle.fontSize, weight: headStyle.fontWeight,
  indent: heads.map((head) => Math.round((rect(head).left - rect(rows[0]).left) * 10) / 10),
}
const groupRows = [...nav.querySelectorAll('.gruppenzeilen')]
report.afterSearch = {
  toHead: rect(heads[0]).top - rect(search).bottom,
  toRow: rect(groupRows[0].querySelector('.menuezeile')).top - rect(search).bottom,
}
report.betweenGroups = heads.slice(1).map((head, k) => {
  const last = rowsOf(groupRows[k]).slice(-1)[0]
  const first = rowsOf(groupRows[k + 1])[0]
  return { toHead: rect(head).top - rect(last).bottom, toRow: rect(first).top - rect(last).bottom }
})

// 3. The search field.
const searchStyle = getComputedStyle(search)
const input = search.querySelector('input')
report.search = {
  height: rect(search).height, width: rect(search).width, radius: searchStyle.borderTopLeftRadius,
  padding: [searchStyle.paddingTop, searchStyle.paddingRight, searchStyle.paddingBottom, searchStyle.paddingLeft],
  gap: searchStyle.columnGap, inputSize: getComputedStyle(input).fontSize,
  shadow: searchStyle.boxShadow, background: searchStyle.backgroundColor,
  line: getComputedStyle(document.documentElement).getPropertyValue('--feldstrich').trim(),
  edge: getComputedStyle(document.documentElement).getPropertyValue('--glass-button-edge').trim(),
  lens: search.querySelector('svg').getBoundingClientRect().width,
}

// 4. A search that finds rows and switches.
input.value = 'Töne'
input.dispatchEvent(new Event('input', { bubbles: true }))
await wait(400)
const found = [...nav.querySelectorAll('.gruppenzeilen.schalter .menuezeile')]
report.found = found.map((row) => ({ height: rect(row).height, sign: row.querySelector('.zeichen').getBoundingClientRect().width,
  text: row.querySelector('.titel').textContent }))
input.value = 'qqqqqq'
input.dispatchEvent(new Event('input', { bubbles: true }))
await wait(400)
const none = [...nav.querySelectorAll('.menuegruppe')].filter((node) => !isHead(node))
report.noHit = none.map((node) => ({ text: node.textContent.trim(), size: getComputedStyle(node).fontSize, weight: getComputedStyle(node).fontWeight }))
input.value = ''
input.dispatchEvent(new Event('input', { bubbles: true }))
await wait(300)

// 5. Silence: a row and a heading of any other list keep their size, the chat list its edge.
const plain = document.querySelector('#plain .menuezeile')
const plainStyle = getComputedStyle(plain)
report.plain = {
  height: rect(plain).height, size: plainStyle.fontSize, weight: plainStyle.fontWeight,
  sign: [plain.querySelector('.zeichen').getBoundingClientRect().width, plain.querySelector('.zeichen').getBoundingClientRect().height],
  value: getComputedStyle(plain.querySelector('.wert')).fontSize,
  dot: plain.querySelector('.punkt circle').getBoundingClientRect().width,
  head: { size: getComputedStyle(document.querySelector('#plain .menuegruppe')).fontSize, weight: getComputedStyle(document.querySelector('#plain .menuegruppe')).fontWeight },
}
window.seitenSchliessen()
await wait(500)
const chatList = document.querySelector('.liste')
report.chatList = [getComputedStyle(chatList).paddingLeft, getComputedStyle(chatList).paddingRight]
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-settingslist-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        built = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=300,
        )
        assert built.returncode == 0, (built.stdout + built.stderr)[-2500:]
        page = folder / "measure.html"
        page.write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-background-networking", "--allow-file-access-from-files",
                "--window-size=1400,1000", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", page.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            raw = asyncio.run(_read_result(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
        assert raw, "the page reported nothing"
        result = json.loads(raw)
        assert "failure" not in result, result["failure"]
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _near(value: float, expected: float, tolerance: float = 1.0) -> bool:
    return abs(value - expected) <= tolerance


def test_every_row_is_36_high_and_269_wide_in_a_column_8_px_from_the_edge(report):
    assert report["navPadding"] == ["8px", "8px"]
    assert report["navWidth"] == 285
    assert report["rowCount"] > 10
    for row in report["rows"]:
        assert _near(row["height"], 36) and _near(row["width"], 269), row


def test_a_row_has_the_padding_gap_radius_and_sign_of_the_drawing(report):
    row = report["first"]
    assert row["padding"] == ["0px", "12px", "0px", "10px"], row
    assert row["gap"] == "10px" and row["radius"] == "9px", row
    assert row["sign"] == [20, 20], row


def test_the_name_is_13_px_regular_and_the_chosen_name_semibold_on_the_glass(report):
    assert report["first"]["titleSize"] == "13px" and report["first"]["titleWeight"] == "400"
    chosen = report["chosen"]
    assert chosen["titleSize"] == "13px" and chosen["titleWeight"] == "600", chosen
    assert report["unchosenWeight"] == "400"
    assert chosen["background"] != "rgba(0, 0, 0, 0)", chosen


def test_the_value_is_11_px_regular_and_the_dot_is_8_px(report):
    assert report["value"] == {"text": "Deutsch", "size": "11px", "weight": "400"}
    assert report["dot"] == [8, 8]


def test_a_group_heading_is_11_px_semibold_and_indented_by_10_px(report):
    heads = report["heads"]
    assert heads["count"] >= 4
    assert heads["size"] == "11px" and heads["weight"] == "600", heads
    assert all(_near(indent, 10) for indent in heads["indent"]), heads


def test_the_room_between_groups_and_under_the_search_is_the_drawings(report):
    after = report["afterSearch"]
    assert _near(after["toHead"], 18) and _near(after["toRow"], 39), after
    assert report["betweenGroups"], "no group after the first"
    for between in report["betweenGroups"]:
        assert _near(between["toHead"], 14) and _near(between["toRow"], 35), between


def test_the_search_field_is_32_high_with_13_px_type_and_the_field_line(report):
    search = report["search"]
    assert _near(search["height"], 32) and _near(search["width"], 269), search
    assert search["padding"] == ["0px", "8px", "0px", "10px"] and search["gap"] == "8px", search
    assert search["radius"] == "9px" and search["inputSize"] == "13px" and search["lens"] == 15, search
    # The edge is the field line, not the button's edge: the two differ in this look.
    assert search["line"] != search["edge"], search
    assert _hex_to_rgb(search["line"]) in search["shadow"], search


def _hex_to_rgb(color: str) -> str:
    color = color.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(color[i : i + 2], 16) for i in (0, 2, 4)))


def test_the_switches_found_by_a_search_are_36_high_rows_with_a_20_px_sign(report):
    assert report["found"], "the search found no switch"
    for row in report["found"]:
        assert _near(row["height"], 36) and row["sign"] == 20, row


def test_the_line_without_a_hit_keeps_its_own_look(report):
    assert report["noHit"], "the line without a hit is gone"
    for line in report["noHit"]:
        assert line["size"] == "12.5px" and line["weight"] == "500", line


def test_silence_a_row_of_another_list_keeps_52_px_and_14_5_px_and_the_chat_list_its_edge(report):
    plain = report["plain"]
    assert _near(plain["height"], 52) and plain["size"] == "14.5px" and plain["weight"] == "500", plain
    assert plain["sign"] == [24, 24] and plain["value"] == "12.5px" and plain["dot"] == 11, plain
    assert plain["head"] == {"size": "12.5px", "weight": "500"}, plain
    assert report["chatList"] == ["12px", "12px"]


def test_silence_the_phone_settings_keep_the_plain_row():
    source = (SRC / "phone" / "pages" / "Settings.svelte").read_text(encoding="utf-8")
    assert 'size="sidebar"' not in source
