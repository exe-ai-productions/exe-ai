"""Six settings pages, laid out in a real browser at the width of a 2560 px window.

The content of a menu page is 2166 px wide there. Appearance: the eight look
cards share the whole row, the picture of each in the ratio 190 : 92, and a
block of 23 lines of code in the chosen colours stands under the card with the
three rows (the one-line sample in the colour row is gone). Shortcuts: the
microphone card over the full width with its two rows side by side, under it
three equally wide and equally high columns in the order Chat, Edit, Developer
options. Instructions and Memory: the rows under the field stand side by side
as equally wide, equally high tiles. Embedding server: model card beside the
llama.cpp section, memory beside the advanced levers, the log open from the
start and reaching down to 40 px above the window's lower edge. Clean-up
server: model beside the network, the advanced drawer over the full width,
memory beside the generation values.

The pages of the menu are built as shipped, the first four inside the frame
they stand in (`SystemPrompt.svelte`), the two servers on the stand-in of
`tests/model_windows_page.py`. Skipped where there is no Chrome or no node,
like the other browser tests.
"""

from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading
from unittest import mock
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import model_windows_page
from tests import test_pdf_pages_chrome as harness

ROOT = harness.ROOT
FRONTEND = harness.FRONTEND

pytestmark = harness.pytestmark

# --- The pages of the menu: look, shortcuts, instructions, memory -----------

SHELL = """<script>
  import SystemPrompt from '../../src/teile/SystemPrompt.svelte'

  let { offen = true } = $props()
</script>

<div id="frame" style="width: @@AREA@@px; height: 1300px; position: relative; display: flex; flex-direction: column;">
  <SystemPrompt {offen} />
</div>
"""

ENTRY_JS = """import { mount, unmount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import '../../src/stil/codefarben.css'
import german from '@@GERMAN@@'
import english from '@@ENGLISH@@'
import { texte } from '@@TEXTE@@'
import { zustand } from '@@ZUSTAND@@'

texte.katalog = german
texte.sprache = 'de'
window.__texte = texte
window.__german = german
window.__english = english
window.__zustand = zustand
window.fetch = async () =>
  new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
zustand.promptOffen = true
// Each page is a fresh mount: the page starts on the entry the settings were opened with.
let current = null
window.__show = (start) => {
  if (current) unmount(current)
  document.getElementById('wurzel').textContent = ''
  zustand.promptStart = start
  current = mount(Shell, { target: document.getElementById('wurzel') })
}
"""

PAGE_CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom } }
const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null)
const body = () => [...document.querySelectorAll('.inhalt > .breite')].find((x) => x.getBoundingClientRect().width > 0)
const contentRight = () => { const b = body(); return b.getBoundingClientRect().right - parseFloat(getComputedStyle(b).paddingRight) }
const contentLeft = () => { const b = body(); return b.getBoundingClientRect().left + parseFloat(getComputedStyle(b).paddingLeft) }
const open = async (key, ready) => {
  window.__show(key)
  for (let k = 0; k < 100; k += 1) { await wait(100); if (body() && body().querySelector(ready)) break }
  await wait(500)
}
const report = {}

await open('darstellung', '.looktafel .karte')
{
  const cards = [...body().querySelectorAll('.looktafel .karte')]
  const pre = body().querySelector('pre.code-sample')
  const picture = body().querySelector('.looktafel .vorschau')
  const list = body().querySelector('.kachelliste')
  report.look = {
    contentRight: contentRight(), contentLeft: contentLeft(), cards: cards.map(box), picture: box(picture), code: box(pre), list: box(list),
    codeLines: pre ? pre.textContent.split('\n').length : 0, codeText: pre ? pre.textContent : '',
    codeStyle: pre ? (({ paddingTop, paddingLeft, fontSize, lineHeight, borderTopLeftRadius, backgroundColor }) =>
      ({ paddingTop, paddingLeft, fontSize, lineHeight, borderTopLeftRadius, backgroundColor }))(getComputedStyle(pre)) : null,
    keywordColour: pre ? getComputedStyle(pre.querySelector('.hljs-keyword')).color : null,
    probe: Boolean(body().querySelector('.codeprobe')),
    colourRowHasName: [...body().querySelectorAll('.einstellkachel')].some((row) => /Code-Farben/.test(text(row)) && row.querySelector('.auswahl')),
  }
}

// The block is painted by the colour pack the way a block of the chat is.
{
  const reference = document.createElement('pre')
  reference.className = 'hljs'
  reference.innerHTML = '<code><span class="hljs-keyword">const</span></code>'
  document.body.appendChild(reference)
  const sample = body().querySelector('pre.code-sample')
  report.packs = {}
  for (const pack of ['exe', 'dracula', 'nord']) {
    if (pack === 'exe') document.documentElement.removeAttribute('data-codefarben')
    else document.documentElement.setAttribute('data-codefarben', pack)
    await wait(100)
    report.packs[pack] = {
      sample: getComputedStyle(sample.querySelector('.hljs-keyword')).color,
      reference: getComputedStyle(reference.querySelector('.hljs-keyword')).color,
      ground: getComputedStyle(sample).backgroundColor,
    }
  }
  document.documentElement.removeAttribute('data-codefarben')
  reference.remove()
}

await open('shortcuts', '.shortcut-columns')
{
  const read = () => ({
    contentRight: contentRight(), contentLeft: contentLeft(),
    mic: box(body().querySelector('.microphone-rows')),
    micRows: [...body().querySelectorAll('.microphone-rows > .einstellkachel')].map(box),
    columns: [...body().querySelectorAll('.shortcut-columns > section')].map((s) => ({
      title: text(s.querySelector('.blocktitel')), card: box(s.querySelector('.kachelliste')),
      rows: [...s.querySelectorAll('.einstellkachel')].map(box),
    })),
    micTitle: text(body().querySelector('section.block .blocktitel')),
  })
  report.shortcuts = read()
  window.__texte.katalog = window.__english
  window.__texte.sprache = 'en'
  await wait(400)
  report.shortcutsEnglish = read()
  window.__texte.katalog = window.__german
  window.__texte.sprache = 'de'
  await wait(300)
}

for (const [key, name] of [['system', 'instructions'], ['memory', 'memory']]) {
  await open(key, '.row-tiles')
  const tiles = [...body().querySelectorAll('.row-tiles > .schalterzeile')]
  const area = body().querySelector('.row-tiles')
  report[name] = {
    contentRight: contentRight(), area: box(area), tiles: tiles.map(box), labels: tiles.map((t) => text(t.querySelector('.beschriftung'))),
    field: box(body().querySelector('textarea')), foot: box(body().querySelector('.fuss')),
    gap: tiles.length > 1 ? tiles[1].getBoundingClientRect().left - tiles[0].getBoundingClientRect().right : null,
  }
  if (key === 'system') {
    window.__texte.katalog = window.__english
    window.__texte.sprache = 'en'
    await wait(400)
    report.instructionsEnglish = [...body().querySelectorAll('.row-tiles > .schalterzeile')].map((t) => text(t.querySelector('.beschriftung')))
    window.__texte.katalog = window.__german
    window.__texte.sprache = 'de'
    await wait(300)
  }
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _run_pages(area: int, window: int) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-settings-pages-{uuid4().hex}"
    folder.mkdir(parents=True)
    server = None
    try:
        (folder / "Shell.svelte").write_text(SHELL.replace("@@AREA@@", str(area)), encoding="utf-8")
        entry = (
            ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
            .replace("@@ENGLISH@@", str(ROOT / "app" / "locales" / "en.json"))
            .replace("@@TEXTE@@", "../../src/lib/texte.svelte.js")
            .replace("@@ZUSTAND@@", "../../src/lib/zustand.svelte.js")
        )
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(harness.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [str(FRONTEND / "node_modules" / ".bin" / "vite"), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        (folder / "measure.html").write_text(harness.PAGE % {"cases": PAGE_CASES, "links": links}, encoding="utf-8")
        web_port = harness._free_port()
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", web_port), functools.partial(harness._Handler, directory=str(folder))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = harness._free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking",
                "--mute-audio", "--use-mock-keychain", "--password-store=basic",
                f"--window-size={window},1400", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", f"http://127.0.0.1:{web_port}/measure.html",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return harness.asyncio.run(harness._drive(port, limit=240.0))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        if server:
            server.shutdown()
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def wide() -> dict:
    # A 2560 px window: the area right of the sidebar and the page's own padding leaves 2166 px.
    return _run_pages(area=2246, window=2560)


@pytest.fixture(scope="module")
def narrow() -> dict:
    return _run_pages(area=780, window=800)


# --- The two server pages ---------------------------------------------------

SERVER_CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
window.texte.katalog = window.germanTexts
const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null)
const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom } }
const report = { innerHeight: window.innerHeight, innerWidth: window.innerWidth }
const show = async (name) => {
  scene.show = null
  await wait(300)
  scene.show = name
  for (let k = 0; k < 100 && !document.querySelector('.reihe'); k += 1) await wait(100)
  await wait(1200)
}
const read = () => ({
  rows: [...document.querySelectorAll('.reihe')].map((row) => [...row.children].map((column) => ({
    heads: [...column.querySelectorAll(':scope > section.abschnitt > .kopf')].map(text),
    box: box(column),
    cards: [...column.querySelectorAll(':scope > section.abschnitt')].map(box),
  }))),
  sections: [...document.querySelectorAll('.tafel > section.abschnitt')].map((s) => ({ head: text(s.querySelector(':scope > .kopf')), box: box(s) })),
  log: box(document.querySelector('pre.protokoll')),
  logText: text(document.querySelector('pre.protokoll')),
  logCalls: window.__logCalls || 0,
  shell: box(document.querySelector('.tafel')),
})
for (const name of %(pages)s) {
  window.__logCalls = 0
  await show(name)
  report[name] = read()
}
// The log of the embedding server folds shut and open again.
await show('einbettung')
document.querySelector('.logkopf .klapp').click()
await wait(300)
report.embeddingFolded = Boolean(document.querySelector('pre.protokoll'))
document.querySelector('.logkopf .klapp').click()
await wait(300)
report.embeddingReopened = box(document.querySelector('pre.protokoll'))
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

SERVER_PAGES = ["einbettung", "bereinigung", "modell", "agent"]


def _run_servers(window: str) -> dict:
    imports = (
        "  import Einbettungsserver from '../../src/teile/Einbettungsserver.svelte'\n"
        "  import Bereinigungsserver from '../../src/teile/Bereinigungsserver.svelte'\n"
    )
    scenes = (
        "  {#if scene.show === 'einbettung'}<Einbettungsserver />{/if}\n"
        "  {#if scene.show === 'bereinigung'}<Bereinigungsserver />{/if}\n"
    )
    anchors = (
        "  import { scene } from './scene.svelte.js'\n",
        "  {#if scene.show === 'modell'}",
        '<div style="width: 1100px; margin: 0 auto;">',
    )
    for anchor in anchors:
        assert anchor in model_windows_page.SHELL, f"the shared harness changed, widen it again: {anchor!r}"
    shell = (
        model_windows_page.SHELL
        .replace(anchors[0], imports + anchors[0])
        .replace(anchors[1], scenes + anchors[1])
        .replace(anchors[2], '<div style="width: min(2166px, 100vw); margin: 0 auto;">')
    )
    stub_anchor = "const methods = {\n"
    assert stub_anchor in model_windows_page.API_STUB, "the shared harness changed, widen it again"
    stub = model_windows_page.API_STUB.replace(
        stub_anchor,
        stub_anchor
        + "  einbettungAuskunft: async () => ({ ...auskunft('chat'), ordner: '/m', laeuft: false, port: 8081,\n"
        "    modelle: [{ name: 'embed.gguf', groesse_gb: 0.6 }], modell: 'embed.gguf', context: 2048, batch: 2048,\n"
        "    pooling: '', layers: null, threads: 0, mlock: false, parallel: null, unknown_architecture: null }),\n"
        "  einbettungProtokoll: async () => { window.__logCalls = (window.__logCalls || 0) + 1; return ['first log line'] },\n"
        "  bereinigungAuskunft: async () => ({ ...auskunft('chat'), ordner: '/s', laeuft: false,\n"
        "    modelle: [{ name: 'clean.gguf', groesse_gb: 1 }] }),\n"
        "  serverThroughput: async () => ({ now: null, average: null, history: [] }),\n",
    )
    cases = SERVER_CASES % {"pages": repr(SERVER_PAGES)}
    with (
        mock.patch.object(model_windows_page, "SHELL", shell),
        mock.patch.object(model_windows_page, "API_STUB", stub),
    ):
        return model_windows_page.run_cases(cases, window_size=window)


@pytest.fixture(scope="module")
def servers() -> dict:
    return _run_servers("2560,1440")


@pytest.fixture(scope="module")
def servers_narrow() -> dict:
    return _run_servers("800,1000")


# --- Appearance -------------------------------------------------------------


def test_the_eight_look_cards_share_the_whole_row(wide):
    look = wide["look"]
    cards = look["cards"]
    assert len(cards) == 8, cards
    assert len({round(card["y"]) for card in cards}) == 1, cards
    assert abs(cards[-1]["right"] - look["contentRight"]) <= 1, (cards[-1], look["contentRight"])
    assert abs(cards[0]["x"] - look["contentLeft"]) <= 1
    assert abs(look["contentRight"] - look["contentLeft"] - 2166) <= 1
    assert len({round(card["w"]) for card in cards}) == 1, cards


def test_the_picture_of_a_card_keeps_the_ratio_190_to_92(wide):
    picture = wide["look"]["picture"]
    assert abs(picture["w"] / picture["h"] - 190 / 92) <= 0.01, picture
    assert picture["w"] > 190


def test_a_block_of_23_lines_stands_under_the_card_with_the_three_rows(wide):
    look = wide["look"]
    code, rows = look["code"], look["list"]
    assert look["codeLines"] == 23, look["codeLines"]
    assert look["codeText"].startswith("// Ask every server for its models and keep the fastest one.\nasync function pickServer(")
    assert look["codeText"].rstrip().endswith("return results[0] ?? null;\n}")
    assert abs(code["w"] - 2166) <= 1 and abs(code["x"] - rows["x"]) <= 1
    assert abs(code["y"] - rows["bottom"] - 16) <= 1, (code, rows)
    style = look["codeStyle"]
    assert (style["paddingTop"], style["paddingLeft"], style["fontSize"], style["borderTopLeftRadius"]) == (
        "20px", "24px", "13px", "9px",
    )
    assert abs(float(style["lineHeight"].removesuffix("px")) - 13 * 1.65) <= 0.1, style


def test_the_colour_row_carries_no_sample_of_code_any_more(wide):
    assert wide["look"]["probe"] is False
    assert wide["look"]["colourRowHasName"] is True


def test_silence_the_block_of_code_is_painted_by_the_colour_pack_like_a_block_of_the_chat(wide):
    packs = wide["packs"]
    for pack, colours in packs.items():
        assert colours["sample"] == colours["reference"], (pack, colours)
    # Another pack, another colour and another ground: the block follows the choice.
    assert len({packs[pack]["sample"] for pack in packs}) >= 2
    assert len({packs[pack]["ground"] for pack in packs}) >= 2


# --- Shortcuts --------------------------------------------------------------


def test_the_microphone_card_stands_over_the_full_width_with_its_two_rows_side_by_side(wide):
    page = wide["shortcuts"]
    mic, rows = page["mic"], page["micRows"]
    assert abs(mic["w"] - 2166) <= 1, mic
    assert len(rows) == 2 and abs(rows[0]["y"] - rows[1]["y"]) <= 1, rows
    assert rows[0]["right"] <= rows[1]["x"] and abs(rows[0]["w"] - rows[1]["w"]) <= 1, rows
    assert wide["shortcuts"]["micTitle"] == "Mikrofon"


def test_the_three_shortcut_columns_stand_equally_wide_and_equally_high(wide):
    columns = wide["shortcuts"]["columns"]
    assert [column["title"] for column in columns] == ["Chat", "Bearbeiten", "Entwickleroptionen"]
    cards = [column["card"] for column in columns]
    assert max(card["w"] for card in cards) - min(card["w"] for card in cards) <= 1, cards
    assert max(card["h"] for card in cards) - min(card["h"] for card in cards) <= 1, cards
    assert len({round(card["y"]) for card in cards}) == 1, cards
    # 24 px apart, from the left edge of the content to its right edge.
    assert abs(cards[1]["x"] - cards[0]["right"] - 24) <= 1 and abs(cards[2]["x"] - cards[1]["right"] - 24) <= 1
    assert abs(cards[2]["right"] - wide["shortcuts"]["contentRight"]) <= 1


def test_the_rows_of_a_shortcut_card_share_its_height_evenly(wide):
    for column in wide["shortcuts"]["columns"]:
        heights = [row["h"] for row in column["rows"]]
        # The first row has no hairline above it: a row is up to a pixel lower than the others.
        assert max(heights) - min(heights) <= 1.5, (column["title"], heights)


def test_the_shortcut_headings_in_english(wide):
    english = wide["shortcutsEnglish"]
    assert [column["title"] for column in english["columns"]] == ["Chat", "Edit", "Developer options"]
    assert english["micTitle"] == "Microphone"


def test_silence_the_shortcut_columns_and_the_microphone_rows_stack_under_900_px(narrow):
    page = narrow["shortcuts"]
    cards = [column["card"] for column in page["columns"]]
    assert all(cards[i]["bottom"] <= cards[i + 1]["y"] + 1 for i in range(2)), cards
    assert all(abs(card["w"] - cards[0]["w"]) <= 1 for card in cards)
    rows = page["micRows"]
    assert rows[0]["bottom"] <= rows[1]["y"] + 1, rows


# --- Instructions and Memory -------------------------------------------------


@pytest.mark.parametrize(("name", "count"), [("instructions", 5), ("memory", 3)])
def test_the_rows_under_the_field_stand_as_a_row_of_equal_tiles(wide, name, count):
    page = wide[name]
    tiles = page["tiles"]
    assert len(tiles) == count, tiles
    assert len({round(tile["y"]) for tile in tiles}) == 1, tiles
    assert max(tile["w"] for tile in tiles) - min(tile["w"] for tile in tiles) <= 1, tiles
    assert max(tile["h"] for tile in tiles) - min(tile["h"] for tile in tiles) <= 1, tiles
    assert abs(page["gap"] - 12) <= 1, page["gap"]
    assert abs(tiles[-1]["right"] - page["contentRight"]) <= 1, (tiles[-1], page["contentRight"])


def test_the_field_stays_above_the_tiles_and_the_foot_below(wide):
    for name in ("instructions", "memory"):
        page = wide[name]
        assert page["field"]["bottom"] <= page["area"]["y"] + 1, page
        assert page["foot"]["y"] >= page["area"]["bottom"] - 1, page


def test_the_name_field_is_headed_anrede_in_german_and_preferred_name_in_english(wide):
    assert wide["instructions"]["labels"][0] == "Anrede"
    assert wide["instructions"]["labels"][1] == "Begrüßung & Anrede"
    assert wide["instructionsEnglish"][0] == "Preferred name"


def test_silence_the_tiles_wrap_where_the_room_runs_out(narrow):
    tiles = narrow["instructions"]["tiles"]
    assert len(tiles) == 5
    assert len({round(tile["y"]) for tile in tiles}) >= 2, tiles
    assert all(tile["right"] <= narrow["instructions"]["contentRight"] + 1 for tile in tiles)


# --- Embedding server -------------------------------------------------------


def _heads(rows):
    return [[head for column in row for head in column["heads"]] for row in rows]


def test_the_embedding_page_stands_in_two_rows_of_two_columns(servers):
    rows = servers["einbettung"]["rows"]
    assert _heads(rows) == [["Einbettungsmodell", "llama.cpp"], ["Speicher", "Erweitert"]], rows
    for row in rows:
        left, right = row
        assert abs(left["box"]["y"] - right["box"]["y"]) <= 1 and abs(left["box"]["w"] - right["box"]["w"]) <= 1
        assert abs(left["box"]["h"] - right["box"]["h"]) <= 1
        assert abs(left["cards"][-1]["bottom"] - right["cards"][-1]["bottom"]) <= 1, row


def test_the_embedding_log_is_open_and_large(servers):
    page = servers["einbettung"]
    log = page["log"]
    assert log, "the log stands closed"
    assert log["h"] >= 320, log
    assert abs(servers["innerHeight"] - log["bottom"] - 40) <= 1, (servers["innerHeight"], log)
    assert abs(log["w"] - page["shell"]["w"]) <= 1
    assert page["logText"] == "first log line"
    # Fetched once, when the page opens.
    assert page["logCalls"] == 1, page["logCalls"]


def test_the_embedding_log_folds_shut_and_open_again(servers):
    assert servers["embeddingFolded"] is False
    assert servers["embeddingReopened"]["h"] >= 320


# --- Clean-up server --------------------------------------------------------


def test_the_cleanup_page_stands_in_rows_with_the_advanced_drawer_over_the_full_width(servers):
    page = servers["bereinigung"]
    assert _heads(page["rows"]) == [["Bereinigungsmodell", "Netzwerk"], ["Speicher", "Parameter"]], page["rows"]
    heads = [section["head"] for section in page["sections"]]
    assert heads.index("Erweitert") > 0
    drawer = next(section for section in page["sections"] if section["head"] == "Erweitert")
    assert abs(drawer["box"]["w"] - page["shell"]["w"]) <= 1, drawer
    first, second = page["rows"]
    assert first[0]["box"]["bottom"] <= drawer["box"]["y"] + 1 and drawer["box"]["bottom"] <= second[0]["box"]["y"] + 1
    for left, right in page["rows"]:
        assert abs(left["box"]["h"] - right["box"]["h"]) <= 1
        assert abs(left["cards"][-1]["bottom"] - right["cards"][-1]["bottom"]) <= 1
    # llama.cpp under the rows, over the full width.
    llama = next(section for section in page["sections"] if section["head"] == "llama.cpp")
    assert llama["box"]["y"] >= second[0]["box"]["bottom"] - 1 and abs(llama["box"]["w"] - page["shell"]["w"]) <= 1


def test_the_cleanup_log_stays_shut_as_before(servers):
    assert servers["bereinigung"]["log"] is None


def test_silence_the_other_server_pages_keep_their_log_shut(servers):
    for name in ("modell", "agent"):
        assert servers[name]["log"] is None, name


def test_silence_under_900_px_the_rows_of_the_server_pages_stand_one_under_the_other(servers_narrow):
    assert servers_narrow["innerWidth"] < 900
    for name in ("einbettung", "bereinigung"):
        rows = servers_narrow[name]["rows"]
        assert rows, name
        for left, right in rows:
            assert left["box"]["bottom"] <= right["box"]["y"] + 1, (name, left["box"], right["box"])
