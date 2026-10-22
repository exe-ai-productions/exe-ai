"""The catalogue list of a cloud provider as the drawing has it, measured in a
real browser.

`ModelleCloud.svelte` is built as shipped, with a sidebar column of its own
(what the page hands over to the sidebar), and drawn in headless Chrome with
the answers of the service made up in the page: OpenAI with three models, one
of them named by the configuration and so fixed. The page reports, for the
catalogue's card: the search as a row of 57 px with a hairline, its field 32 px
high on the button glass; every entry a row of 57 px with a hairline under it,
the name 13 px in 600, the sign of the parameters 15, the tick 14 in green with
a stroke of 2; the open row on the button glass without a radius; the foot as a
row of 57 px with the count in 600 and the card's own button; everything edge
to edge. And the same list in its basic look (the tools list), measured on its
own, which must stay as it was.

The build of the harness links the built stylesheet, so every colour and size
probe reads the real tokens.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LISTE = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))["liste"]

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import ModelleCloud from %(cloud)r
  import Ankreuzliste from %(list)r
  import { zustand } from %(zustand)r

  let { view = 'cloud' } = $props()
  const items = [
    { id: 'a', name: 'item-a' }, { id: 'b', name: 'item-b' }, { id: 'c', name: 'item-c' },
  ]
  let on = $state({ a: true })
</script>

{#if view === 'plain'}
  <div id="plain" style="width: 520px;">
    <Ankreuzliste
      eintraege={items}
      istAn={(e) => Boolean(on[e.id])}
      istFest={(e) => e.id === 'c'}
      onschalten={(e, an) => { on[e.id] = an }}
      onalle={(an) => { for (const e of items) on[e.id] = an }}
    />
  </div>
{:else}
  <div style="display: flex; width: 1280px; height: 860px;">
    <nav id="leiste" style="width: 320px; flex: none; overflow: auto;">
      {#if zustand.menuSections}{@render zustand.menuSections.snippet?.()}{/if}
    </nav>
    <main id="seite" style="flex: 1; min-width: 0; overflow: auto; position: relative;">
      <ModelleCloud offen={true} />
    </main>
  </div>
{/if}
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { zustand } from %(zustand)r
import { texte } from %(texts)r

texte.sprache = 'en'
texte.katalog = english
const base = { group: 'cloud', capabilities: {}, timeout_enabled: true }
const view = new URLSearchParams(location.search).get('view') || 'cloud'
const all = [
  { ...base, id: 'openai/gpt-a', modell: 'gpt-a', name: 'gpt-a', anbieter: 'openai', anbieter_name: 'OpenAI', erreichbar: true,
    schluessel_env: 'OPENAI_API_KEY', schluessel_gesetzt: true, angeheftet: true },
  { ...base, id: 'openai/gpt-b', modell: 'gpt-b', name: 'gpt-b', anbieter: 'openai', anbieter_name: 'OpenAI', erreichbar: true,
    schluessel_env: 'OPENAI_API_KEY', schluessel_gesetzt: true },
  { ...base, id: 'openai/gpt-c', modell: 'gpt-c', name: 'gpt-c', anbieter: 'openai', anbieter_name: 'OpenAI', erreichbar: true,
    schluessel_env: 'OPENAI_API_KEY', schluessel_gesetzt: true },
]
zustand.modelle = all
window.fetch = async (address) => {
  const full = String(address)
  const path = full.replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path === '/models' ? all : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
window.zustand = zustand
mount(Shell, { target: document.getElementById('wurzel'), props: { view } })
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

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const page = () => document.getElementById('seite')
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
const look = (node) => getComputedStyle(node)
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const probe = (token, property = 'color') => {
  const node = document.createElement('i')
  node.style[property] = `var(${token})`
  document.body.appendChild(node)
  const value = getComputedStyle(node)[property]
  node.remove()
  return value
}
const rowsOf = () => Array.from(page().querySelectorAll('.katalog .zeile.end'))
for (let k = 0; k < 60 && rowsOf().length !== 3; k += 1) await wait(100)
if (rowsOf().length !== 3) throw new Error('the catalogue did not render its three rows')
await wait(600)
const click = async (node) => { node.click(); await wait(400) }
const report = {}

const card = page().querySelector('.katalog').closest('.karte')
const cardBox = card.getBoundingClientRect()
const rows = rowsOf()
report.rows = rows.map((row) => {
  const name = row.querySelector('.name')
  const box = row.getBoundingClientRect()
  return {
    name: text(name),
    height: Math.round(box.height),
    hairline: look(row).borderBottomWidth,
    hairlineInk: look(row).borderBottomColor === probe('--linie', 'borderBottomColor'),
    nameSize: px(look(name).fontSize), nameWeight: look(name).fontWeight,
    nameInk: look(name).color === probe('--text'),
    edgeToEdge: Math.abs(box.left - cardBox.left) <= 1 && Math.abs(box.width - cardBox.width) <= 1,
  }
})
const open = rows.find((row) => row.classList.contains('open'))
report.open = open ? {
  name: text(open.querySelector('.name')),
  ground: look(open).backgroundColor === probe('--glass-button', 'backgroundColor'),
  radius: look(open).borderTopLeftRadius,
  shadow: look(open).boxShadow,
} : null
const first = rows[0]
const tick = first.querySelector('.end-tick svg')
const sign = first.querySelector('.action svg')
report.first = {
  fixed: first.classList.contains('fest'), tabindex: first.getAttribute('tabindex'),
  fixedWord: text(first.querySelector('.woher')),
  tick: Math.round(tick.getBoundingClientRect().width), tickStroke: tick.getAttribute('stroke-width'),
  tickInk: look(first.querySelector('.end-tick')).color === probe('--gruen'),
  sign: Math.round(sign.getBoundingClientRect().width),
  signInk: look(first.querySelector('.sign-button')).color === probe('--text-leise'),
}
const searchRow = page().querySelector('.suchzeile')
const field = searchRow.querySelector('.suche')
report.search = {
  height: Math.round(searchRow.getBoundingClientRect().height),
  hairline: look(searchRow).borderBottomWidth,
  field: Math.round(field.getBoundingClientRect().height),
  fieldGround: look(field).backgroundColor === probe('--glass-button', 'backgroundColor'),
  fieldEdge: look(field).boxShadow !== 'none',
  radius: look(field).borderTopLeftRadius,
  lens: Math.round(field.querySelector('svg').getBoundingClientRect().width),
  edgeToEdge: Math.abs(searchRow.getBoundingClientRect().left - cardBox.left) <= 1
    && Math.abs(searchRow.getBoundingClientRect().width - cardBox.width) <= 1,
}
const foot = page().querySelector('.katalog .fuss')
const count = foot.querySelector('.zahl')
const all = foot.querySelector('button')
report.foot = {
  height: Math.round(foot.getBoundingClientRect().height),
  countSize: px(look(count).fontSize), countWeight: look(count).fontWeight,
  countInk: look(count).color === probe('--text'),
  button: Array.from(all.classList).filter((c) => !c.startsWith('svelte-')).join(' '), buttonHeight: Math.round(all.getBoundingClientRect().height),
  buttonGround: look(all).backgroundColor === probe('--glass-button', 'backgroundColor'),
  buttonSize: px(look(all).fontSize), buttonWeight: look(all).fontWeight,
  buttonRadius: look(all).borderTopLeftRadius,
  edgeToEdge: Math.abs(foot.getBoundingClientRect().left - cardBox.left) <= 1
    && Math.abs(foot.getBoundingClientRect().width - cardBox.width) <= 1,
}
report.noOwnInset = look(page().querySelector('.listenkarte')).paddingLeft === '0px'
  && look(page().querySelector('.katalog')).paddingLeft === '0px'

// What the list does.
const pressed = (row) => row.getAttribute('aria-pressed')
const number = () => (text(page().querySelector('.katalog .zahl')).match(/\d+/) || ['?'])[0]
const behaviour = {}
behaviour.countBefore = number()
behaviour.pressedBefore = pressed(rowsOf()[1])
await click(rowsOf()[1])
behaviour.pressedAfter = pressed(rowsOf()[1])
behaviour.countAfter = number()
behaviour.signOnChosen = Boolean(rowsOf()[1].querySelector('.sign-button'))
await click(rowsOf()[0])
behaviour.fixedStays = pressed(rowsOf()[0])
await click(rowsOf()[1].querySelector('.sign-button'))
behaviour.parameters = text(page().querySelector('.right')).includes('Parameters · gpt-b')
const input = page().querySelector('.suchzeile input')
input.value = 'gpt-b'
input.dispatchEvent(new Event('input', { bubbles: true }))
await wait(300)
behaviour.filtered = rowsOf().map((row) => text(row.querySelector('.name')))
input.value = 'zzz-no-such-model'
input.dispatchEvent(new Event('input', { bubbles: true }))
await wait(300)
behaviour.nothing = text(page().querySelector('.katalog .leer'))
behaviour.nothingPad = look(page().querySelector('.katalog .leer')).paddingLeft
input.value = ''
input.dispatchEvent(new Event('input', { bubbles: true }))
await wait(300)
await click(page().querySelector('.katalog .fuss button'))
behaviour.allPressed = rowsOf().map(pressed)
behaviour.allWord = text(page().querySelector('.katalog .fuss button'))
behaviour.allCount = number()
await click(page().querySelector('.katalog .fuss button'))
behaviour.noneWord = text(page().querySelector('.katalog .fuss button'))
report.behaviour = behaviour

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

CASES_PLAIN = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
const look = (node) => getComputedStyle(node)
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const probe = (token, property = 'color') => {
  const node = document.createElement('i')
  node.style[property] = `var(${token})`
  document.body.appendChild(node)
  const value = getComputedStyle(node)[property]
  node.remove()
  return value
}
for (let k = 0; k < 60 && !document.querySelector('#plain .zeile'); k += 1) await wait(100)
await wait(400)
const root = document.getElementById('plain')
const row = root.querySelector('.zeile')
const field = root.querySelector('.suche')
const foot = root.querySelector('.fuss')
const button = foot.querySelector('button')
const report = {
  rows: root.querySelectorAll('.zeile').length,
  endRows: root.querySelectorAll('.zeile.end').length,
  row: {
    padding: look(row).padding, nameWeight: look(row.querySelector('.name')).fontWeight,
    nameSize: px(look(row.querySelector('.name')).fontSize),
    hairline: look(row).borderBottomWidth,
    box: Math.round(row.querySelector('.kreuz').getBoundingClientRect().width),
  },
  field: {
    height: Math.round(field.getBoundingClientRect().height), marginBottom: look(field).marginBottom,
    ground: look(field).backgroundColor === probe('--bg-hoch', 'backgroundColor'),
    lens: Math.round(field.querySelector('svg').getBoundingClientRect().width),
    inRow: Boolean(root.querySelector('.suchzeile.end-look')),
  },
  card: {
    ground: look(root.querySelector('.listenkarte')).backgroundColor === probe('--bg-erhoben', 'backgroundColor'),
    padding: look(root.querySelector('.listenkarte')).padding,
    ends: Boolean(root.querySelector('.listenkarte.end-look')),
  },
  foot: {
    marginTop: look(foot).marginTop, size: px(look(foot).fontSize), ends: foot.classList.contains('end-look'),
    button: Array.from(button.classList).filter((c) => !c.startsWith('svelte-')).join(' '), buttonSize: px(look(button).fontSize),
    buttonGround: look(button).backgroundColor,
    count: text(foot.querySelector('span')),
    countWeight: look(foot.querySelector('span')).fontWeight,
  },
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
%(links)s
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; position: relative; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
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
</body></html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 120.0) -> dict:
    """Read the page's report over the debug port."""
    websockets = pytest.importorskip("websockets")
    end = time.monotonic() + limit
    address = None
    while time.monotonic() < end and address is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                for page in json.load(response):
                    if page.get("type") == "page" and "measure.html" in page.get("url", ""):
                        address = page["webSocketDebuggerUrl"]
        except OSError:
            pass
        if address is None:
            await asyncio.sleep(0.2)
    assert address, "Chrome did not open the page"
    async with websockets.connect(address, max_size=32 * 1024 * 1024) as connection:
        number = 0

        async def value_of(expression: str):
            nonlocal number
            number += 1
            await connection.send(
                json.dumps({"id": number, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True}})
            )
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response.get("result", {}).get("result", {}).get("value")

        raw = ""
        while time.monotonic() < end and not raw:
            raw = await value_of("document.getElementById('ergebnis')?.textContent || ''")
            if not raw:
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


def _run_case(view: str = "cloud") -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-cloud-catalogue-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {
                "cloud": "../../src/teile/ModelleCloud.svelte",
                "list": "../../src/teile/Ankreuzliste.svelte",
                "zustand": "../../src/lib/zustand.svelte.js",
            },
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "texts": "../../src/lib/texte.svelte.js",
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        assert links, "the build emitted no stylesheet: the colour probes would measure nothing"
        (folder / "measure.html").write_text(
            PAGE % {"cases": CASES_PLAIN if view == "plain" else CASES, "links": links}, encoding="utf-8"
        )
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1280,900",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri() + f"?view={view}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return asyncio.run(_drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def measured() -> dict:
    return _run_case()


@pytest.fixture(scope="module")
def plain() -> dict:
    return _run_case("plain")


def test_every_entry_is_a_row_of_57_with_a_hairline_under_it_edge_to_edge(measured):
    assert [r["name"] for r in measured["rows"]] == ["gpt-a", "gpt-b", "gpt-c"], measured["rows"]
    for row in measured["rows"]:
        assert abs(row["height"] - 57) <= 1, row
        assert row["hairline"] == "1px" and row["hairlineInk"], row
        assert row["edgeToEdge"], row
    assert measured["noOwnInset"]


def test_the_name_of_an_entry_is_13_px_in_600_and_the_full_ink(measured):
    for row in measured["rows"]:
        assert row["nameSize"] == 13 and row["nameWeight"] == "600" and row["nameInk"], row


def test_the_tick_is_14_px_green_with_a_stroke_of_2_and_the_sign_of_the_parameters_is_15(measured):
    first = measured["first"]
    assert first["tick"] == 14 and first["tickStroke"] == "2" and first["tickInk"], first
    assert first["sign"] == 15 and first["signInk"], first


def test_the_open_row_stands_on_the_button_glass_without_a_radius(measured):
    opened = measured["open"]
    assert opened is not None and opened["name"] == "gpt-a", opened
    assert opened["ground"] and opened["radius"] == "0px", opened


def test_the_search_is_a_row_of_57_with_a_hairline_and_its_field_is_32_on_the_button_glass(measured):
    search = measured["search"]
    assert abs(search["height"] - 57) <= 1 and search["hairline"] == "1px", search
    assert search["field"] == 32 and search["fieldGround"] and search["fieldEdge"], search
    assert search["radius"] == "9px" and search["lens"] == 15 and search["edgeToEdge"], search


def test_the_foot_is_a_row_of_57_with_the_count_in_600_and_the_button_of_the_card(measured):
    foot = measured["foot"]
    assert abs(foot["height"] - 57) <= 1 and foot["edgeToEdge"], foot
    assert foot["countSize"] == 13 and foot["countWeight"] == "600" and foot["countInk"], foot
    assert foot["button"] == "feldknopf" and foot["buttonHeight"] == 34 and foot["buttonGround"], foot
    assert foot["buttonSize"] == 13 and foot["buttonRadius"] == "9px", foot


def test_a_click_on_an_entry_chooses_and_unchooses_it_and_the_fixed_one_stays_locked(measured):
    behaviour = measured["behaviour"]
    assert behaviour["pressedBefore"] == "false" and behaviour["pressedAfter"] == "true", behaviour
    assert int(behaviour["countAfter"]) == int(behaviour["countBefore"]) + 1, behaviour
    assert measured["first"]["fixed"] and measured["first"]["tabindex"] == "-1", measured["first"]
    assert measured["first"]["fixedWord"] == LISTE["aus_konfiguration"]
    assert behaviour["fixedStays"] == "true", behaviour


def test_the_sign_opens_the_parameters_the_search_filters_and_select_all_selects_all(measured):
    behaviour = measured["behaviour"]
    assert behaviour["signOnChosen"] and behaviour["parameters"], behaviour
    assert behaviour["filtered"] == ["gpt-b"], behaviour
    assert behaviour["nothing"] == LISTE["nichts_gefunden"], behaviour
    # The message stands 16 px in, like the rows.
    assert behaviour["nothingPad"] == "16px", behaviour
    assert behaviour["allPressed"] == ["true", "true", "true"] and behaviour["allCount"] == "3", behaviour
    assert behaviour["allWord"] == LISTE["alle_abwaehlen"] and behaviour["noneWord"] == LISTE["alle_waehlen"], behaviour


def test_silence_the_basic_look_of_the_list_stays_as_it_was(plain):
    # The tools list: rows of a card, the field above, the foot below.
    assert plain["rows"] == 3 and plain["endRows"] == 0, plain
    assert plain["row"]["padding"] == "9px 0px" and plain["row"]["hairline"] == "1px", plain["row"]
    assert plain["row"]["nameWeight"] == "400" and plain["row"]["nameSize"] == 13 and plain["row"]["box"] == 17, plain["row"]
    assert plain["field"]["height"] == 32 and plain["field"]["marginBottom"] == "10px", plain["field"]
    assert plain["field"]["ground"] and plain["field"]["lens"] == 13 and not plain["field"]["inRow"], plain["field"]
    assert plain["card"]["ground"] and plain["card"]["padding"] == "2px 16px" and not plain["card"]["ends"], plain["card"]
    foot = plain["foot"]
    assert foot["marginTop"] == "10px" and foot["size"] == 12 and not foot["ends"], foot
    assert foot["button"] == "textknopf" and foot["buttonSize"] == 12, foot
    assert foot["buttonGround"] == "rgba(0, 0, 0, 0)" and foot["countWeight"] == "400", foot
