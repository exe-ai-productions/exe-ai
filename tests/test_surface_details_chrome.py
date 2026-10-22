"""Small details of the surface, measured in headless Chrome as shipped.

* The sign of the wired memory bar stands level with the name, not between the
  name and the track (`MemoryBar.svelte`).
* The stripes of the Todoist sign stand in the middle of the red tile.
* The overview of the servers wears the house sign `ranking_bars`.
* The row "Updates" of the settings list shows the running version at rest and
  the answer to a look at its right end, with no block of its own under the
  list; the row "Web-App" shows its own version at its right end.
* The context ring and the dots of the thinking stages are lit in the text
  colour and quiet beyond it; the check mark of the thinking menu is the quiet
  ink of the other menus.
* The code of the web app carries no border of its own, and the address it
  shows ends on the path of the app.

The parts are built and drawn as they are; the service's answers are not
needed. Skipped where there is no Chrome or no node, like the other browser
tests.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import segno

from app import appfenster, prozessstopp, qr_code, web_app
from tests.model_windows_page import _free_port, _read_result

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"

SHELL = """<script>
  import MemoryBar from '../../src/teile/MemoryBar.svelte'
  import Einstellungsliste from '../../src/teile/Einstellungsliste.svelte'
  import ContextRing from '../../src/teile/ContextRing.svelte'
  import Denkschalter from '../../src/teile/Denkschalter.svelte'
  import Hauszeichen from '../../src/teile/Hauszeichen.svelte'
  import { LOGOS } from '../../src/lib/logos.js'
  import { rowValue } from '../../src/lib/settingsState.svelte.js'

  const profile = { art: 'stufen', stufen: ['off', 'low', 'medium', 'high'] }
</script>

<div id="wired" style="width: 300px; padding: 20px;"><MemoryBar wired={10} total={32} /></div>
<div id="todoist" style="width: 152px; height: 152px;">
  <svg viewBox={LOGOS.todoist.vb} width="152" height="152">{@html LOGOS.todoist.html}</svg>
</div>
<div id="bars" style="width: 40px; height: 40px;"><Hauszeichen zeichen="ranking_bars" groesse={32} /></div>
<div id="ring" style="padding: 20px;"><ContextRing /></div>
<div id="thinking" style="padding: 20px 20px 260px 300px;">
  <Denkschalter denkprofil={profile} denken="medium" />
</div>
<div id="list" style="width: 285px; padding: 8px;"><Einstellungsliste aktuell="" wert={rowValue} /></div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import german from '../../../app/locales/de.json'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import { updates } from '../../src/lib/updates.svelte.js'
import '../../src/stil/global.css'

texte.katalog = german
// A model with a window of 1,000 tokens and an answer that used 300 of them.
zustand.modelle = [{ id: 'm', name: 'Model', context_tokens: 1000 }]
zustand.modellId = 'm'
zustand.aktiverChat = 'c'
zustand.nachrichtenChatId = 'c'
zustand.nachrichten = [{ rolle: 'assistant', zustand: 'fertig', gesamt_tokens: 300 }]
// The shell is there and says which version runs.
updates.present = true
updates.version = '0.6.50'
window.__updates = updates
window.fetch = async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
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

PAGE = """<!doctype html><meta charset=utf-8><title>details</title>
<style>body { margin: 0; background: #2a2a28; }</style>
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
const rect = (node) => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom, top: r.top, left: r.left } }
const middleY = (node) => { const r = node.getBoundingClientRect(); return r.top + r.height / 2 }
await wait(600)
if (window.__mountError) throw new Error(window.__mountError)
const probe = document.createElement('span')
document.body.appendChild(probe)
const colourOf = (variable, property = 'color') => {
  probe.style.cssText = property + ': var(' + variable + ');'
  return getComputedStyle(probe)[property === 'background' ? 'backgroundColor' : property]
}
const report = {}
for (const look of ['dunkel', 'hell']) {
  document.documentElement.setAttribute('data-modus', look)
  // The dots and the ring ease their colour over 0.2 to 0.5 s.
  await wait(900)
  const one = {}
  one.tokens = { text: colourOf('--text'), quiet: colourOf('--text-leise'), empty: colourOf('--indicator-empty'), blue: colourOf('--blau') }

  // The wired memory bar: the sign on the line of the name.
  const bar = document.querySelector('#wired .bar')
  const name = bar.querySelector('.line span')
  const range = document.createRange()
  range.selectNodeContents(name)
  one.wired = { sign: rect(bar.querySelector('.sign svg')), name: rect(range), track: rect(bar.querySelector('.track')) }
  // The same bar at another type size: the sign's box and the name's line keep their common height.
  bar.style.fontSize = '20px'
  await wait(100)
  const range2 = document.createRange()
  range2.selectNodeContents(bar.querySelector('.line span'))
  one.wiredBig = { sign: rect(bar.querySelector('.sign svg')), box: rect(bar.querySelector('.sign')), line: rect(bar.querySelector('.line')), name: rect(range2) }
  bar.style.fontSize = ''

  // The Todoist sign: the tile and the stripes.
  const groups = document.querySelectorAll('#todoist svg g')
  one.todoist = { tile: rect(groups[0]), stripes: rect(groups[1]) }

  // The ranking-bars sign.
  one.bars = { paths: Array.from(document.querySelectorAll('#bars svg path')).map((p) => p.getAttribute('d')) }

  // The ring of the context.
  const fill = document.querySelector('#ring .fill')
  const track = document.querySelector('#ring .track')
  one.ring = { fill: getComputedStyle(fill).stroke, track: getComputedStyle(track).stroke }

  // The dots of the thinking stages and the check mark of its menu.
  const dots = Array.from(document.querySelectorAll('#thinking .punkte i'))
  one.dots = dots.map((dot) => ({ full: dot.classList.contains('voll'), colour: getComputedStyle(dot).backgroundColor }))
  if (!document.querySelector('.eintrag')) {
    document.querySelector('#thinking .pille').click()
    await wait(300)
  }
  const mark = document.querySelector('.eintrag[aria-checked="true"] .haken')
  one.mark = mark ? getComputedStyle(mark).color : null
  document.querySelector('#thinking .pille').click()
  await wait(200)

  report[look] = one
}

// The list: the rows "Updates" and "Web-App" and the overview.
document.documentElement.setAttribute('data-modus', 'dunkel')
await wait(300)
const rows = Array.from(document.querySelectorAll('#list .menuezeile'))
const rowOf = (title) => rows.find((row) => row.querySelector('.titel')?.textContent.trim() === title)
const describeRow = (row) => {
  const result = row.querySelector('.update-ergebnis')
  const value = result || row.querySelector('.wert')
  const action = row.querySelector('.update-tat')
  return {
    row: rect(row), value: value ? rect(value) : null, text: value ? value.textContent.trim() : null,
    kind: result ? result.className.replace('update-ergebnis', '').replace(/svelte-\w+/g, '').trim() : null,
    action: action ? action.textContent.trim() : null,
  }
}
const list = { updates: {}, count: rows.length, own: document.querySelectorAll('.updates').length }
list.updates.rest = describeRow(rowOf('Updates'))
const shell = window.__updates
shell.state = 'none'; shell.looked = true; await wait(150)
list.updates.current = describeRow(rowOf('Updates'))
shell.looked = false; shell.state = 'available'; shell.found = '0.7.0'; await wait(150)
list.updates.available = describeRow(rowOf('Updates'))
shell.state = 'downloading'; shell.percent = 40; await wait(150)
list.updates.downloading = describeRow(rowOf('Updates'))
shell.state = 'downloaded'; await wait(150)
list.updates.downloaded = describeRow(rowOf('Updates'))
shell.state = 'error'; shell.step = 'check'; shell.reason = 'offline'; await wait(150)
list.updates.failed = describeRow(rowOf('Updates'))
shell.state = 'store'; await wait(150)
list.updates.store = describeRow(rowOf('Updates'))
list.web = describeRow(rowOf('Web-App'))
list.overview = describeRow(rowOf('Übersicht'))
list.overviewSign = Array.from(rowOf('Übersicht').querySelectorAll('.zeichen svg path')).map((p) => p.getAttribute('d'))
report.list = list
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    if sys.platform != "darwin":
        pytest.skip("the browser run of the interface is checked on macOS only")
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists():
        pytest.skip("no node or no frontend dependencies on this machine")
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-surface-details-{uuid4().hex}"
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
                "--window-size=1100,1400", f"--remote-debugging-port={port}",
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


LOOKS = ("dunkel", "hell")


def _near(value: float, expected: float, tolerance: float = 1.0) -> bool:
    return abs(value - expected) <= tolerance


@pytest.mark.parametrize("look", LOOKS)
def test_the_wired_memory_sign_stands_on_the_line_of_the_name_and_not_between_name_and_track(report, look):
    wired = report[look]["wired"]
    sign, name, track = wired["sign"], wired["name"], wired["track"]
    sign_middle = sign["y"] + sign["height"] / 2
    name_middle = name["y"] + name["height"] / 2
    assert abs(sign_middle - name_middle) <= 1.5, wired
    assert sign_middle < track["y"], "the sign is above the track, level with the name"


@pytest.mark.parametrize("look", LOOKS)
def test_the_wired_memory_sign_and_the_name_line_follow_the_type_size_together(report, look):
    big = report[look]["wiredBig"]
    assert abs(big["box"]["height"] - big["line"]["height"]) <= 0.5, big
    assert big["line"]["height"] > 25, "the line grew with the type size (1.4 x 20 px)"
    assert abs((big["sign"]["y"] + big["sign"]["height"] / 2) - (big["name"]["y"] + big["name"]["height"] / 2)) <= 2, big


@pytest.mark.parametrize("look", LOOKS)
def test_the_stripes_of_the_todoist_sign_stand_in_the_middle_of_the_red_tile(report, look):
    todoist = report[look]["todoist"]
    tile, stripes = todoist["tile"], todoist["stripes"]
    left, right = stripes["left"] - tile["left"], tile["right"] - stripes["right"]
    assert abs(left - right) <= 0.5, (left, right)
    # The stripes are no thin line in a corner: they fill most of the tile's width.
    assert stripes["width"] > tile["width"] * 0.5


def test_the_overview_of_the_servers_wears_the_ranking_bars_sign_in_its_row(report):
    drawn = report["list"]["overviewSign"]
    assert drawn == ["M9 55 H55", "M17 55 V19 M32 55 V29 M47 55 V39"], drawn
    assert report["dunkel"]["bars"]["paths"] == drawn


def test_the_head_of_the_overview_wears_the_same_sign():
    page = (SRC / "teile" / "ModelleLokal.svelte").read_text(encoding="utf-8")
    assert '{#if overview}\n            <span class="kasten"><Hauszeichen zeichen="ranking_bars" groesse={22} /></span>' in page
    rows = (SRC / "lib" / "einstellungsliste.js").read_text(encoding="utf-8")
    assert "{ id: 'overview', zeichen: 'ranking_bars'," in rows
    # The server pages keep the racks.
    assert "{ name: 'server', titel: 'modell.server', zeichen: 'server' }" in rows


def test_the_house_sign_is_the_drawing_of_the_catalogue_word_for_word():
    page = (SRC / "teile" / "Hauszeichen.svelte").read_text(encoding="utf-8")
    block = page.split("zeichen === 'ranking_bars'}", 1)[1].split("{:else if", 1)[0]
    assert 'd="M9 55 H55" stroke-width="4.5"' in block
    assert 'd="M17 55 V19 M32 55 V29 M47 55 V39" stroke-width="5"' in block


@pytest.mark.parametrize("look", LOOKS)
def test_the_ring_and_the_chosen_dots_are_lit_in_the_text_colour_and_the_rest_is_quiet(report, look):
    tokens = report[look]["tokens"]
    assert tokens["text"] != tokens["blue"]
    ring = report[look]["ring"]
    assert ring["fill"] == tokens["text"], ring
    assert ring["track"] == tokens["empty"], ring
    dots = report[look]["dots"]
    assert [dot["full"] for dot in dots] == [True, True, False], dots
    for dot in dots:
        assert dot["colour"] == (tokens["text"] if dot["full"] else tokens["empty"]), dot
    assert report[look]["mark"] == tokens["quiet"], report[look]["mark"]


def test_silence_only_the_ring_and_the_switch_lose_their_blue():
    thinking = (SRC / "teile" / "Denkschalter.svelte").read_text(encoding="utf-8")
    assert "var(--blau)" not in thinking, "the switch no longer uses the blue"
    ring = (SRC / "teile" / "ContextRing.svelte").read_text(encoding="utf-8")
    # Neither the ring nor the bar of the card's figures is blue: nothing in it runs.
    assert "var(--blau)" not in ring


def test_the_row_updates_shows_the_version_at_rest_centred_on_the_row(report):
    updates = report["list"]["updates"]["rest"]
    assert updates["text"] == "0.6.50", updates
    assert _near(updates["value"]["y"] + updates["value"]["height"] / 2, updates["row"]["y"] + updates["row"]["height"] / 2)


def test_the_list_has_no_update_block_of_its_own_under_it(report):
    assert report["list"]["own"] == 0


def test_the_row_updates_answers_a_look_at_its_right_end(report):
    answers = report["list"]["updates"]
    assert answers["current"]["text"] == "Die App ist aktuell." and answers["current"]["kind"] == "done"
    assert answers["available"]["text"].startswith("Neue Version 0.7.0") and answers["available"]["action"] == "Download"
    assert answers["downloading"]["kind"] == "running" and "40" in answers["downloading"]["text"]
    assert answers["downloaded"]["action"] == "Installieren"
    assert answers["failed"]["kind"] == "failed" and "offline" in answers["failed"]["text"]
    assert answers["store"]["kind"] == "done"
    for name, answer in answers.items():
        value, row = answer["value"], answer["row"]
        # The answer stays inside the row and level with it, whatever its length.
        assert value["x"] >= row["x"] and value["right"] <= row["right"] + 0.5, (name, answer)
        assert _near(value["y"] + value["height"] / 2, row["y"] + row["height"] / 2, 2), (name, answer)


def test_the_row_web_app_shows_its_own_version_level_with_the_row_and_flush_with_the_other_values(report):
    web, overview = report["list"]["web"], report["list"]["overview"]
    assert web["text"] == "0.1.1-r1 (Beta)", web
    assert _near(web["value"]["y"] + web["value"]["height"] / 2, web["row"]["y"] + web["row"]["height"] / 2)
    assert overview["value"] is not None and _near(web["value"]["right"], overview["value"]["right"], 0.5)


def test_the_web_app_version_is_one_constant():
    source = (SRC / "lib" / "webAppVersion.js").read_text(encoding="utf-8")
    assert "export const WEB_APP_VERSION = '0.1.1-r1 (Beta)'" in source
    state = (SRC / "lib" / "settingsState.svelte.js").read_text(encoding="utf-8")
    assert "case 'web_app':\n      return WEB_APP_VERSION" in state


def test_the_code_of_the_web_app_has_no_border_of_its_own():
    drawn = qr_code.svg("https://exe.tailnet-name.ts.net/app")
    modules = segno.make("https://exe.tailnet-name.ts.net/app", error="m").symbol_size(border=0)[0]
    assert re.search(rf'viewBox="0 0 {modules} {modules}"', drawn), drawn[:200]


def test_the_light_edge_around_the_code_is_a_few_pixels():
    page = (SRC / "teile" / "SettingsWebApp.svelte").read_text(encoding="utf-8")
    rule = page.split(".code {", 1)[1].split("}", 1)[0]
    # The code stands large in a tile of its own: the light edge is 10 px, the corners 14.
    assert "padding: 10px" in rule and "border-radius: 14px" in rule


@pytest.mark.parametrize(
    ("host", "port", "address"),
    [
        ("mac.tailnet-name.ts.net", 443, "https://mac.tailnet-name.ts.net/app"),
        ("mac.tailnet-name.ts.net", 8443, "https://mac.tailnet-name.ts.net:8443/app"),
    ],
)
def test_the_address_of_the_web_app_ends_on_the_path_of_the_app(host, port, address):
    assert web_app.APP_PATH == "/app"
    assert web_app.Tailscale.compose(host, port) + web_app.APP_PATH == address

