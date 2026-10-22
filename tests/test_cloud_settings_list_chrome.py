"""The cloud providers page carries the settings list in the sidebar and the
providers with their models as a column in the page, measured in a real browser.

`ModelleCloud.svelte` is built as shipped, together with a sidebar column of
its own that draws what the page hands over (`zustand.menuSections`, as the
real sidebar does), and drawn in headless Chrome with the answers of the
service made up in the page: OpenAI (key set, three models, one of them
chosen), Anthropic (key missing, does not answer), a server without a key that
does not answer, and a server that answers with one model and no catalogue.
The page reports:

* the sidebar holds the list of the settings with "Cloud providers" as the
  chosen row, and nothing of the providers (no provider rows, no tick rows, no
  "Add provider" row), and no arrow back;
* the page has a column of 300 px on the left with the providers, under each
  one that answers its chosen models, a missing key in the row of the provider,
  and the way to a new provider at the foot; a provider that does not answer
  stands alone, without a count and without a model row;
* a click on every row changes the right side, the tick takes a model out and
  brings it back, the column and the content end on one line;
* the right side keeps what the page held: the table, the card, the catalogue
  and the pop-up of the button for a new provider.

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
LONG = "Demo Cloud With A Very Long Provider Name Indeed"
BACK = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))["app"]["zurueck"]

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import ModelleCloud from %(cloud)r
  import { zustand } from %(zustand)r
</script>

<div style="display: flex; width: 1280px; height: 860px;">
  <nav id="leiste" style="width: 320px; flex: none; overflow: auto;">
    {#if zustand.menuSections}{@render zustand.menuSections.snippet?.()}{/if}
  </nav>
  <main id="seite" style="flex: 1; min-width: 0; overflow: auto; position: relative;">
    <ModelleCloud offen={true} />
  </main>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { zustand } from %(zustand)r
import { texte } from %(texts)r

texte.sprache = 'en'
texte.katalog = english
const LONG = 'Demo Cloud With A Very Long Provider Name Indeed'
const base = { group: 'cloud', capabilities: {}, timeout_enabled: true }
const empty = new URLSearchParams(location.search).get('providers') === 'none'
const all = [
  { ...base, id: 'openai/gpt-a', modell: 'gpt-a', name: 'gpt-a', anbieter: 'openai', anbieter_name: 'OpenAI', erreichbar: true,
    schluessel_env: 'OPENAI_API_KEY', schluessel_gesetzt: true, angeheftet: true, context_tokens: 200000, kontext_quelle: 'server' },
  { ...base, id: 'openai/gpt-b', modell: 'gpt-b', name: 'gpt-b', anbieter: 'openai', anbieter_name: 'OpenAI', erreichbar: true,
    schluessel_env: 'OPENAI_API_KEY', schluessel_gesetzt: true, context_tokens: 200000, kontext_quelle: 'server' },
  { ...base, id: 'openai/gpt-c', modell: 'gpt-c', name: 'gpt-c', anbieter: 'openai', anbieter_name: 'OpenAI', erreichbar: true,
    schluessel_env: 'OPENAI_API_KEY', schluessel_gesetzt: true, context_tokens: 200000, kontext_quelle: 'server' },
  { ...base, id: 'anthropic/claude-x', modell: 'claude-x', name: 'claude-x', anbieter: 'anthropic', anbieter_name: 'Anthropic',
    erreichbar: false, schluessel_env: 'ANTHROPIC_API_KEY', schluessel_gesetzt: false },
  { ...base, id: 'homelab', name: 'homelab', anbieter: 'homelab', anbieter_name: 'Homelab', erreichbar: false },
  { ...base, id: 'solo', name: 'solo-model', anbieter: 'solo', anbieter_name: 'Solo', erreichbar: true },
  { ...base, id: 'longname', name: 'longname', anbieter: 'longname', anbieter_name: LONG, erreichbar: false,
    schluessel_env: 'LONG_API_KEY', schluessel_gesetzt: false },
]
const models = empty ? [] : all
zustand.modelle = models.filter((m) => m.erreichbar)
window.fetch = async (address) => {
  const full = String(address)
  const path = full.replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path === '/models' ? models : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
window.zustand = zustand
mount(Shell, { target: document.getElementById('wurzel') })
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
const LONG = 'Demo Cloud With A Very Long Provider Name Indeed'
const side = () => document.getElementById('leiste')
const page = () => document.getElementById('seite')
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
const empty = new URLSearchParams(location.search).get('providers') === 'none'
const column = () => page().querySelector('nav.providers')
const right = () => page().querySelector('.right')
const rendered = () => side().querySelectorAll('.menuezeile').length > 10 && column()
  && (empty || (column().querySelectorAll('.menuezeile').length === 5 && page().querySelectorAll('[role=row].line').length === 5))
for (let k = 0; k < 60 && !rendered(); k += 1) await wait(100)
if (!rendered()) throw new Error('the page did not render the sidebar list and the providers')
await wait(600)
const click = async (node) => { node.click(); await wait(350) }
const report = {}
report.sideRows = Array.from(side().querySelectorAll('.menuezeile')).map((row) => text(row.querySelector('.titel')))
report.chosenRows = Array.from(side().querySelectorAll('.menuezeile.gewaehlt')).map((row) => text(row.querySelector('.titel')))
report.sideOwn = {
  ticks: side().querySelectorAll('.haken').length,
  listRows: side().querySelectorAll('.listenzeile').length,
  column: side().querySelectorAll('nav.providers').length,
  provider: report.sideRows.filter((title) => ['OpenAI', 'Anthropic', 'Homelab', 'Solo'].includes(title)).length,
  addRow: report.sideRows.filter((title) => title === 'Add provider').length,
}
const back = '__BACK__'
report.backArrows = document.querySelectorAll('button.zurueck').length
  + Array.from(document.querySelectorAll('button')).filter((b) => b.getAttribute('aria-label') === back).length

const groups = []
for (const node of column().children) {
  if (node.classList.contains('menuezeile')) {
    groups.push({
      provider: text(node.querySelector('.titel')),
      titleCut: node.querySelector('.titel').scrollWidth > node.querySelector('.titel').clientWidth,
      countWhole: !node.querySelector('.count') || node.querySelector('.count').scrollWidth <= node.querySelector('.count').clientWidth,
      titleShrink: getComputedStyle(node.querySelector('.titel')).flexShrink,
      count: text(node.querySelector('.count')),
      missing: Boolean(node.querySelector('.count.missing')),
      logo: Number(node.querySelector('.zeichen svg')?.getAttribute('width') || 0),
      chosen: node.classList.contains('gewaehlt'),
      models: [],
    })
  } else if (node.classList.contains('listenzeile') && !node.classList.contains('dazu')) {
    groups[groups.length - 1].models.push({
      name: text(node.querySelector('.mname')),
      on: node.querySelector('.haken').classList.contains('an'),
    })
  }
}
const frame = column().getBoundingClientRect()
const content = right().getBoundingClientRect()
// The heading of the list stands over its card, like the one of the table on the right.
const listHead = column().previousElementSibling
// Without a provider there is no table: the way to a new one stands there instead.
const tableHead = page().querySelector('.pick .tafelkopf')
const tableCard = page().querySelector('.pick .table')?.getBoundingClientRect() ?? null
report.column = {
  width: frame.width,
  head: text(listHead),
  headsFlush: tableHead ? Math.abs(listHead.getBoundingClientRect().top - tableHead.getBoundingClientRect().top) <= 0.5 : null,
  groups,
  addRow: text(column().querySelector('.listenzeile.dazu')),
  note: text(column().querySelector('.leer')),
  leftOfContent: frame.right <= content.left,
  topsFlush: tableCard ? Math.abs(frame.top - tableCard.top) <= 0.5 : null,
  endsOnOneLine: Math.abs(frame.bottom - content.bottom) <= 1,
  overflows: column().scrollWidth > column().clientWidth,
}
report.table = Array.from(page().querySelectorAll('[role=row].line')).map((row) => ({
  provider: text(row.querySelector('.name .text')),
  key: text(row.querySelector('.key')),
  keyMissing: row.querySelector('.key').classList.contains('missing'),
  models: text(row.querySelectorAll('[role=cell]')[2]),
  state: text(row.querySelector('.state')),
  chosen: row.classList.contains('chosen'),
}))
report.card = text(page().querySelector('.provider-head'))
report.catalogue = page().querySelectorAll('.katalog').length
report.emptyTile = Boolean(page().querySelector('.leerkachel'))
report.tableRows = page().querySelectorAll('[role=row].line').length

if (!empty) {
  const rowOf = (name) => Array.from(column().querySelectorAll('.menuezeile')).find((row) => text(row.querySelector('.titel')) === name)
  const modelRow = (name) => Array.from(column().querySelectorAll('.listenzeile')).find((row) => text(row.querySelector('.mname')) === name)
  const chosenTable = () => text(page().querySelector('[role=row].line.chosen .name .text'))

  // A click on every row of the column changes the right side.
  report.clicks = {}
  await click(rowOf('Solo'))
  report.clicks.solo = { card: text(page().querySelector('.provider-head')), table: chosenTable(), singleModelRow: page().querySelectorAll('.model-row').length }
  await click(rowOf('Homelab'))
  report.clicks.homelab = { card: text(page().querySelector('.provider-head')), table: chosenTable(), singleModelRow: page().querySelectorAll('.model-row').length }
  await click(rowOf('Anthropic'))
  report.clicks.anthropic = { card: text(page().querySelector('.provider-head')), table: chosenTable() }
  await click(rowOf('OpenAI'))
  report.clicks.openai = { card: text(page().querySelector('.provider-head')), table: chosenTable(), catalogue: page().querySelectorAll('.katalog').length }
  await click(modelRow('gpt-a'))
  report.clicks.model = { parameters: text(right()).includes('Parameters · gpt-a'), chosenModelRow: text(column().querySelector('.listenzeile.gewaehlt .mname')) }

  // The tick takes the model out of the model choice and brings it back.
  await click(rowOf('Solo'))
  const tick = () => modelRow('solo-model').querySelector('.haken')
  const states = [tick().getAttribute('aria-pressed')]
  await click(tick())
  states.push(tick().getAttribute('aria-pressed'))
  await click(tick())
  states.push(tick().getAttribute('aria-pressed'))
  report.tick = states

  // The column and the content still end on one line after the clicks.
  const frame2 = column().getBoundingClientRect()
  const content2 = right().getBoundingClientRect()
  report.endsOnOneLineAfter = Math.abs(frame2.bottom - content2.bottom) <= 1

  // The card of a provider, the catalogue head and the table as drawn.
  await click(rowOf('OpenAI'))
  const probe = (name) => {
    const node = document.createElement('i')
    node.style.color = `var(${name})`
    document.body.appendChild(node)
    const colour = getComputedStyle(node).color
    node.remove()
    return colour
  }
  const px = (value) => Math.round(parseFloat(value) * 10) / 10
  const look = (node) => getComputedStyle(node)
  const head = page().querySelector('.provider-head')
  const nameEl = head.querySelector('.provider-name')
  const stateEl = head.querySelector('.state-word')
  const sub = page().querySelector('.subline')
  const ch = page().querySelector('.catalog-head')
  const cardRows = ch ? Array.from(ch.parentElement.children) : []
  report.card2 = {
    nameSize: px(look(nameEl).fontSize), nameWeight: look(nameEl).fontWeight,
    stateSize: px(look(stateEl).fontSize), stateWeight: look(stateEl).fontWeight,
    stateGreen: look(stateEl).color === probe('--gruen-text'),
    gap: Math.round(stateEl.getBoundingClientRect().left - nameEl.getBoundingClientRect().right),
    stateNearName: stateEl.getBoundingClientRect().right < head.getBoundingClientRect().right - 150,
    labelWeight: look(page().querySelector('.label')).fontWeight,
    subSize: sub ? px(look(sub).fontSize) : null,
    subColour: sub ? look(sub).color === probe('--text-leise') : null,
    subOpacity: sub ? look(sub).opacity : null,
    catalogue: ch ? {
      title: text(ch.querySelector('.catalog-title')),
      titleSize: px(look(ch.querySelector('.catalog-title')).fontSize),
      titleWeight: look(ch.querySelector('.catalog-title')).fontWeight,
      count: text(ch.querySelector('.catalog-count')),
      countSize: px(look(ch.querySelector('.catalog-count')).fontSize),
      countColour: look(ch.querySelector('.catalog-count')).color === probe('--text-leise'),
      height: Math.round(ch.getBoundingClientRect().height),
      first: cardRows[0] === ch,
      hairlineBelow: cardRows[1] ? look(cardRows[1]).borderTopWidth : null,
      inCard: Boolean(ch.closest('.karte')),
      ownHead: Boolean(ch.closest('section').querySelector('.kopf')),
    } : null,
  }
  const lines = Array.from(page().querySelectorAll('[role=row].line'))
  const rowOfProvider = (name) => lines.find((r) => text(r.querySelector('.name .text')) === name)
  const headRow = page().querySelector('[role=row].head')
  const bin = page().querySelector('.binbutton')
  const binBox = bin.getBoundingClientRect()
  report.tableLook = {
    line: Math.round(lines[0].getBoundingClientRect().height),
    head: Math.round(headRow.getBoundingClientRect().height),
    headSize: px(look(headRow).fontSize), headWeight: look(headRow).fontWeight,
    headColour: look(headRow).color === probe('--text-leise'),
    bin: [Math.round(binBox.width), Math.round(binBox.height)],
    binGround: look(bin).backgroundColor !== 'rgba(0, 0, 0, 0)',
    binEdge: look(bin).boxShadow !== 'none',
    nameWeight: look(lines[0].querySelector('.name')).fontWeight,
    modelsInk: look(rowOfProvider('OpenAI').querySelector('.models')).color === probe('--text'),
    keyRed: look(rowOfProvider('Anthropic').querySelector('.key.missing')).color === probe('--rot-text'),
    stateGreen: look(rowOfProvider('OpenAI').querySelector('.state.reachable')).color === probe('--gruen-text'),
  }
  await click(rowOf('Solo'))
  const single = page().querySelector('.model-row .model-name')
  report.single = single ? {
    weight: look(single).fontWeight, size: px(look(single).fontSize),
    family: look(single).fontFamily === look(page().querySelector('.label')).fontFamily,
  } : null
  const longRow = rowOf(LONG)
  report.longRow = {
    titleCut: longRow.querySelector('.titel').scrollWidth > longRow.querySelector('.titel').clientWidth,
    countWhole: longRow.querySelector('.count').scrollWidth <= longRow.querySelector('.count').clientWidth,
    count: text(longRow.querySelector('.count')),
    inside: longRow.getBoundingClientRect().right <= column().getBoundingClientRect().right + 1,
  }
  const sideTitle = side().querySelector('.menuezeile .titel')
  const sideValue = side().querySelector('.menuezeile .wert')
  report.sideShrink = [look(sideTitle).flexShrink, sideValue ? look(sideValue).flexShrink : null]
}

const add = page().querySelector('.new-button')
report.addButton = text(add)
const flags = () => Object.fromEntries(Object.entries(window.zustand).filter(([, v]) => typeof v === 'boolean'))
const before = flags()
const foot = column().querySelector('.listenzeile.dazu')
if (foot) {
  await click(foot)
  report.popupAfterFoot = Boolean(document.querySelector('.schleier .popup .mask'))
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  await wait(400)
}
add.click()
await wait(500)
report.popupAfterClick = Boolean(document.querySelector('.schleier .popup .mask'))
report.popupWidth = Math.round(document.querySelector('.schleier .popup')?.getBoundingClientRect().width || 0)
const local = Array.from(side().querySelectorAll('.menuezeile')).find((row) => text(row.querySelector('.titel')) === 'Local models')
if (local) local.click()
await wait(300)
const after = flags()
report.localClick = {
  wish: window.zustand.lokalWunsch,
  flipped: Object.keys(after).filter((key) => after[key] !== before[key]),
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


def _run_case(providers: str = "two") -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-cloud-list-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {
                "cloud": "../../src/teile/ModelleCloud.svelte",
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
            PAGE % {"cases": CASES.replace("__BACK__", BACK), "links": links}, encoding="utf-8"
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
                (folder / "measure.html").as_uri() + f"?providers={providers}",
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
def without_providers() -> dict:
    return _run_case("none")


def test_the_sidebar_holds_the_settings_list_with_cloud_providers_chosen(measured):
    assert measured["chosenRows"] == ["Cloud providers"], measured["chosenRows"]
    rows = measured["sideRows"]
    for title in ("Local models", "Cloud providers", "Catalog"):
        assert title in rows, (title, rows)
    assert len(rows) > 15, rows


def test_nothing_of_the_providers_stands_in_the_sidebar_and_no_arrow_leads_back(measured):
    assert measured["sideOwn"] == {"ticks": 0, "listRows": 0, "column": 0, "provider": 0, "addRow": 0}, measured["sideOwn"]
    assert measured["backArrows"] == 0


def test_a_click_on_local_models_asks_for_that_page(measured):
    click = measured["localClick"]
    assert click["wish"] == "lokal", click
    assert click["flipped"], click


def test_the_page_has_a_column_of_300_px_with_the_providers_left_of_the_content(measured):
    column = measured["column"]
    assert abs(column["width"] - 300) <= 1, column["width"]
    assert column["leftOfContent"] and column["topsFlush"] and column["headsFlush"], column
    assert [g["provider"] for g in column["groups"]] == ["OpenAI", "Anthropic", "Homelab", "Solo", LONG], column["groups"]
    assert column["head"] == "Servers"
    assert all(g["logo"] in (0, 18) for g in column["groups"]), column["groups"]


def test_the_chosen_models_stand_under_their_provider_and_the_foot_holds_the_way_to_a_new_one(measured):
    groups = {g["provider"]: g for g in measured["column"]["groups"]}
    assert groups["OpenAI"]["count"] == "1/3", groups["OpenAI"]
    assert [m["name"] for m in groups["OpenAI"]["models"]] == ["gpt-a"], groups["OpenAI"]
    assert groups["OpenAI"]["models"][0]["on"]
    assert [m["name"] for m in groups["Solo"]["models"]] == ["solo-model"], groups["Solo"]
    assert measured["column"]["addRow"] == "Add provider"


def test_a_missing_key_says_so_in_the_row_of_the_provider(measured):
    groups = {g["provider"]: g for g in measured["column"]["groups"]}
    assert groups["Anthropic"]["count"] == "Key missing" and groups["Anthropic"]["missing"], groups["Anthropic"]
    assert not groups["OpenAI"]["missing"]


def test_a_provider_that_does_not_answer_stands_alone_with_the_words_and_without_a_model_row(measured):
    groups = {g["provider"]: g for g in measured["column"]["groups"]}
    # It says that it does not answer, where the count of an answering one stands.
    assert groups["Homelab"]["count"] == "Not responding" and groups["Homelab"]["models"] == [], groups["Homelab"]
    assert groups["Anthropic"]["models"] == [], groups["Anthropic"]
    # The table still says what it said.
    row = next(r for r in measured["table"] if r["provider"] == "Homelab")
    assert row["models"] == "-", row
    assert row["state"] == "Not responding", row


def test_a_click_on_every_row_changes_the_right_side(measured):
    clicks = measured["clicks"]
    assert "Solo" in clicks["solo"]["card"] and clicks["solo"]["table"] == "Solo", clicks["solo"]
    assert "Homelab" in clicks["homelab"]["card"] and clicks["homelab"]["table"] == "Homelab", clicks["homelab"]
    assert "Anthropic" in clicks["anthropic"]["card"] and clicks["anthropic"]["table"] == "Anthropic", clicks["anthropic"]
    assert "OpenAI" in clicks["openai"]["card"] and clicks["openai"]["catalogue"] >= 1, clicks["openai"]
    assert clicks["model"]["parameters"] and clicks["model"]["chosenModelRow"] == "gpt-a", clicks["model"]


def test_the_provider_that_does_not_answer_is_not_a_model_on_the_right_either(measured):
    assert measured["clicks"]["homelab"]["singleModelRow"] == 0, measured["clicks"]["homelab"]
    assert measured["clicks"]["solo"]["singleModelRow"] == 1, measured["clicks"]["solo"]


def test_the_tick_takes_a_model_out_and_brings_it_back(measured):
    assert measured["tick"] == ["true", "false", "true"], measured["tick"]


def test_the_column_and_the_content_end_on_one_line(measured):
    assert measured["column"]["endsOnOneLine"] and measured["endsOnOneLineAfter"], measured["column"]
    assert not measured["column"]["overflows"], measured["column"]


def test_the_page_keeps_the_table_with_the_key_and_the_count_of_chosen_models(measured):
    table = {row["provider"]: row for row in measured["table"]}
    assert set(table) == {"OpenAI", "Anthropic", "Homelab", "Solo", LONG}, measured["table"]
    assert table["Anthropic"]["key"] == "Key missing" and table["Anthropic"]["keyMissing"]
    assert table["OpenAI"]["key"] != "Key missing" and not table["OpenAI"]["keyMissing"]
    assert table["OpenAI"]["models"] == "1/3", table["OpenAI"]
    assert table["OpenAI"]["chosen"] and sum(1 for r in measured["table"] if r["chosen"]) == 1


def test_the_page_keeps_the_card_the_catalogue_and_the_way_to_a_new_provider(measured):
    assert "OpenAI" in measured["card"], measured["card"]
    assert measured["catalogue"] >= 1
    assert measured["addButton"] == "Add provider", measured["addButton"]
    assert measured["popupAfterClick"], "the button did not open the pop-up"
    assert measured["popupAfterFoot"], "the foot of the column did not open the pop-up"


def test_a_long_name_gives_way_and_the_state_stays_whole(measured):
    groups = {g["provider"]: g for g in measured["column"]["groups"]}
    row = groups[LONG]
    assert row["count"] == "Key missing" and row["countWhole"] and row["titleCut"], row
    assert measured["longRow"] == {"titleCut": True, "countWhole": True, "count": "Key missing", "inside": True}, measured["longRow"]
    assert row["titleShrink"] == "1"


def test_silence_the_other_lists_keep_the_order_name_first_then_value(measured):
    # The sidebar's rows keep a name that never shrinks and a value that gives way.
    assert measured["sideShrink"][0] == "0", measured["sideShrink"]
    assert measured["sideShrink"][1] in (None, "1"), measured["sideShrink"]


def test_the_table_is_drawn_like_the_drawing(measured):
    table = measured["tableLook"]
    assert table["line"] == 56 and table["head"] == 40, table
    assert table["headSize"] == 11 and table["headWeight"] == "600" and table["headColour"], table
    assert table["bin"] == [34, 34] and table["binGround"] and table["binEdge"], table
    assert table["nameWeight"] == "600" and table["modelsInk"], table


def test_the_words_of_a_state_wear_the_text_forms_of_the_colours(measured):
    assert measured["tableLook"]["keyRed"] and measured["tableLook"]["stateGreen"], measured["tableLook"]
    assert measured["card2"]["stateGreen"], measured["card2"]


def test_the_head_of_the_card_names_the_provider_large_with_its_state_right_behind(measured):
    card = measured["card2"]
    assert card["nameSize"] == 17 and card["nameWeight"] == "600", card
    assert card["stateSize"] == 12 and card["stateWeight"] == "500", card
    assert abs(card["gap"] - 12) <= 1 and card["stateNearName"], card
    assert card["labelWeight"] == "600", card
    assert card["subSize"] is not None, "the line under the context name is not drawn"
    assert card["subSize"] == 12 and card["subColour"], card
    assert abs(float(card["subOpacity"]) - 0.6) < 0.01, card


def test_a_single_model_stands_in_the_font_of_the_page(measured):
    single = measured["single"]
    assert single == {"weight": "600", "size": 13, "family": True}, single


def test_the_catalogue_head_is_the_first_row_of_its_card_with_a_hairline_under_it(measured):
    head = measured["card2"]["catalogue"]
    assert head["title"] == "Catalog" and head["titleSize"] == 15 and head["titleWeight"] == "600", head
    assert head["count"] == "1/3" and head["countSize"] == 12 and head["countColour"], head
    assert head["first"] and head["inCard"] and not head["ownHead"], head
    assert head["hairlineBelow"] == "1px", head
    assert 56 <= head["height"] <= 58, head


def test_the_pop_up_that_adds_a_provider_is_594_wide(measured):
    assert abs(measured["popupWidth"] - 594) <= 1, measured["popupWidth"]


def test_silence_without_any_provider_the_list_stays_and_the_way_to_a_new_one_stays(without_providers):
    assert without_providers["chosenRows"] == ["Cloud providers"], without_providers["chosenRows"]
    assert without_providers["sideOwn"] == {"ticks": 0, "listRows": 0, "column": 0, "provider": 0, "addRow": 0}
    assert without_providers["column"]["groups"] == [] and without_providers["column"]["note"] == "No provider yet"
    assert without_providers["tableRows"] == 0 and without_providers["emptyTile"]
    assert without_providers["addButton"] == "Add provider"
    assert without_providers["popupAfterClick"]
