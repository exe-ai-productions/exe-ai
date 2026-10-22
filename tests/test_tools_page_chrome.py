"""The tools page is drawn to its design and every built-in tool wears its
own sign, measured in a real browser.

`SystemPrompt.svelte` is built as shipped and drawn in headless Chrome with
the service made up in the page: eight built-in sources, one running server
with a tool, one switched-off server and one that is not running. The count
stands as a pill at the title, the list has a head of its own on a card 300
wide, the rows are 52 high with their dots on one line and the arrow beside
them, the unfolded tools are 36 high, and the right half sits 24 px beside
the list. Every built-in source and tool draws the sign the catalogue names
for it, never the fallback chevron. Skipped where there is no Chrome or no
node, like the other browser tests.
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

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import SystemPrompt from %(page)r

  let { offen = true } = $props()
</script>

<div id="frame" style="width: %(width)s; height: 1000px; position: relative;">
  <SystemPrompt {offen} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { zustand } from %(zustand)r

const tool = (name, server, extra = {}) => ({
  name, server, builtin: true, beschreibung: 'Does ' + name, needs_confirmation: false, ...extra,
})
const answers = {
  '/tools': {
    aktiv: true,
    server: ['searxng'],
    werkzeuge: [
      tool('run_command', 'shell'), tool('read_file', 'shell'), tool('start_job', 'shell'),
      tool('memory_save', 'memory'),
      tool('skill_load', 'skills'),
      tool('draw_image', 'image'), tool('draw_video', 'image'),
      tool('cronjob', 'cronjob'), tool('cron_note', 'cronjob'),
      tool('goal', 'goal'),
      tool('deliver_file', 'dock'),
      tool('get_current_time', 'clock'),
      tool('web_search', 'searxng', { builtin: false }),
    ],
  },
  // The page of the agents is asked for lists: an answer of `{}` there throws
  // at the first `.find`, and the page the pill is checked on would never open.
  '/agent-files': [],
  '/agents': [],
  '/skills': [],
  '/tools/servers': [
    { name: 'searxng', laeuft: true, enabled: true, allowed_tools: null,
      alle_werkzeuge: [{ name: 'web_search', beschreibung: 'Searches the web' }] },
    { name: 'figma', laeuft: false, enabled: false, allowed_tools: null, alle_werkzeuge: [] },
    { name: 'api-example-com', laeuft: false, enabled: true, allowed_tools: null, alle_werkzeuge: [] },
  ],
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
// The light look, so a text colour cannot be mistaken for a sign colour.
document.documentElement.dataset.modus = 'hell'
zustand.promptOffen = true
zustand.promptStart = 'werkzeuge'
window.__zustand = zustand
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
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js', cssFileName: 'style' },
  },
})
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const box = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height,
           cx: r.left + r.width / 2, cy: r.top + r.height / 2 }
}
const style = (node, name) => getComputedStyle(node)[name]
const probe = (property, value) => {
  const p = document.createElement('div')
  p.style[property] = value
  document.body.appendChild(p)
  const out = getComputedStyle(p)[property]
  p.remove()
  return out
}
const sign = (node) => {
  const svg = node && node.querySelector('svg')
  return svg ? svg.outerHTML.replace(/ class="[^"]*"/g, '').replace(/\s+/g, ' ') : ''
}
const rows = () => Array.from(document.querySelectorAll('.werkzeugseite .links .qbox'))
for (let k = 0; k < 100 && rows().length < 11; k += 1) await wait(100)
await wait(500)

// A narrow window: the list over the chosen entry, as wide as the page.
if (location.search.includes('narrow')) {
  const zwei = document.querySelector('.werkzeugseite .zwei')
  const links = document.querySelector('.werkzeugseite .links')
  document.getElementById('ergebnis').textContent = JSON.stringify({
    direction: getComputedStyle(zwei).flexDirection, list: box(links),
    right: box(document.querySelector('.werkzeugseite .rechts')), zwei: box(zwei),
  })
  return
}

const head = document.querySelector('.set-kopf')
const pill = head.querySelector('.zahlpille .pille')
report.pill = pill ? {
  title: box(head.querySelector('h3')), wrap: box(head.querySelector('.zahlpille')), pill: box(pill),
  text: pill.textContent.trim(), colour: style(pill, 'color'), dot: getComputedStyle(pill, '::before').display,
  leise: probe('color', getComputedStyle(document.documentElement).getPropertyValue('--text-leise')),
} : { missing: true }

const links = document.querySelector('.werkzeugseite .links')
const lkopf = links.querySelector('.lkopf')
report.list = {
  box: box(links), right: box(document.querySelector('.werkzeugseite .rechts')), radius: style(links, 'borderTopLeftRadius'),
  background: style(links, 'backgroundColor'), card: probe('backgroundColor', 'var(--glass-card)'),
  shadow: style(links, 'boxShadow'), overflowY: style(links, 'overflowY'),
  head: box(lkopf), headName: lkopf ? lkopf.querySelector('.lname').textContent.trim() : null,
  headCount: lkopf ? lkopf.querySelector('.lzahl').textContent.trim() : null,
  headLine: box(lkopf && lkopf.querySelector('.llinie')), headHeight: lkopf ? style(lkopf, 'height') : null,
  content: box(links.querySelector('.qbox:last-child')),
}

report.sources = rows().map((box_) => {
  const head_ = box_.querySelector('.qkopf')
  const name = head_.querySelector('.qname')
  const sentence = head_.querySelector('.qsatz')
  const dot = head_.querySelector('svg.lp')
  const disc = head_.querySelector('svg.lp circle.scheibe')
  const arrow = head_.querySelector('.qklapp svg')
  const holder = head_.querySelector('.qzeichen')
  return {
    name: name.textContent.trim(), box: box(head_), radius: style(head_, 'borderTopLeftRadius'),
    nameWeight: style(name, 'fontWeight'), nameSize: style(name, 'fontSize'), nameColour: style(name, 'color'),
    sentenceSize: style(sentence, 'fontSize'), sentenceColour: style(sentence, 'color'),
    dot: box(dot), disc: box(disc), arrow: box(arrow), arrowCentre: arrow ? (() => {
      // The tip of the chevron (12, 15 of 24) through the transform of the svg.
      const path = arrow.querySelector('path')
      const point = arrow.createSVGPoint()
      point.x = 12; point.y = 15
      const mapped = point.matrixTransform(path.getScreenCTM())
      return { x: mapped.x, y: mapped.y }
    })() : null,
    sign: box(holder.querySelector('svg')), signHolder: box(holder), signFill: sign(holder),
    chevronFallback: sign(holder).includes('M9 6l6 6-6 6'),
    hasArrow: Boolean(arrow), foldable: Boolean(head_.querySelector('.qklapp')),
    hasPlace: Boolean(head_.querySelector('.qplatz')), place: box(head_.querySelector('.qplatz')),
  }
})

// Closed arrows point right, the open one down.
const tipOf = (svg) => {
  const path = svg.querySelector('path')
  const point = svg.createSVGPoint()
  point.x = 12; point.y = 15
  const mapped = point.matrixTransform(path.getScreenCTM())
  const centre = box(svg)
  return { dx: mapped.x - centre.cx, dy: mapped.y - centre.cy }
}
const shellRow = rows()[0]
report.arrowClosed = tipOf(shellRow.querySelector('.qklapp svg'))
report.chosenAtStart = shellRow.querySelector('.qkopf').classList.contains('gewaehlt')

// The right half of a built-in source: the box with the sign, the tools under it.
const rightOf = () => {
  const card = document.querySelector('.werkzeugseite .rechts')
  const kasten = card.querySelector('.kasten')
  const inner = kasten && kasten.querySelector('svg')
  const sub = card.querySelector('.kopfkarte .unter')
  return {
    kasten: box(kasten), sign: box(inner), signHtml: sign(kasten), subSize: sub && style(sub, 'fontSize'),
    subColour: sub && style(sub, 'color'), subTop: sub && box(sub).top,
    tools: Object.fromEntries(Array.from(card.querySelectorAll('.eeintrag')).map((e) => {
      const holder = e.querySelector('.ezeichen')
      const svg = holder.querySelector('svg')
      return [e.querySelector('.ename').textContent.trim(), {
        html: sign(holder), svg: box(svg), holder: box(holder),
      }]
    })),
    cardBox: box(card), listBottom: box(card.querySelector('.eliste')),
  }
}
report.right = {}
const names = rows().map((r) => r.querySelector('.qname').textContent.trim())
for (let i = 0; i < 8; i += 1) {
  rows()[i].querySelector('.qeintrag').click()
  await wait(300)
  report.right[names[i]] = rightOf()
}
report.right.cardHeightForClock = box(document.querySelector('.werkzeugseite .rechts'))

// A server source: no box with a sign.
rows()[8].querySelector('.qeintrag').click()
await wait(300)
report.server = {
  kasten: Boolean(document.querySelector('.werkzeugseite .rechts .kasten')), chosen: rows()[8].querySelector('.qkopf').classList.contains('gewaehlt'),
  kopf: box(document.querySelector('.werkzeugseite .rechts .kopfkarte')), name: box(document.querySelector('.werkzeugseite .rechts .kopfkarte .gross')),
  nameSize: style(document.querySelector('.werkzeugseite .rechts .kopfkarte .gross'), 'fontSize'),
  subSize: style(document.querySelector('.werkzeugseite .rechts .kopfkarte .unter'), 'fontSize'),
}

// Unfold the first source: tools of 36, and the arrow turns down.
rows()[0].querySelector('.qeintrag').click()
await wait(200)
rows()[0].querySelector('.qklapp').click()
await wait(400)
report.arrowOpen = tipOf(rows()[0].querySelector('.qklapp svg'))
const tools = Array.from(rows()[0].querySelectorAll('.weintrag'))
report.unfolded = tools.map((n) => ({
  height: box(n).height, left: parseFloat(style(n, 'paddingLeft')), radius: style(n, 'borderTopLeftRadius'),
  name: n.querySelector('.wname').textContent.trim(),
}))
report.unfoldedSwitches = tools.map((n) => Boolean(n.querySelector('[role="switch"]')))
report.listBottomUnfolded = box(links)

// The switch does not choose; the row does, with the keyboard as well.
const before = rows()[0].querySelector('.qkopf').classList.contains('gewaehlt')
tools[1].querySelector('[role="switch"]').click()
await wait(300)
report.afterSwitch = {
  sourceStillChosen: rows()[0].querySelector('.qkopf').classList.contains('gewaehlt'),
  toolChosen: tools[1].classList.contains('gewaehlt'), before,
}
tools[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
await wait(300)
report.afterEnter = {
  toolChosen: tools[1].classList.contains('gewaehlt'), heading: document.querySelector('.werkzeugseite .rechts .gross').textContent.trim(),
}

// The pill belongs to this page only.
const titleOf = () => document.querySelector('.set-kopf h3')?.textContent.trim()
const toolsTitle = titleOf()
window.__zustand.promptStart = 'agent'
await wait(800)
report.otherPage = {
  pills: document.querySelectorAll('.set-kopf .zahlpille').length,
  title: titleOf(), toolsTitle,
}

document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 100%%; max-width: 1700px; position: relative; }</style>
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


async def _drive(port: int, limit: float = 150.0) -> dict:
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


def _run_case(narrow: bool = False) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-tools-page-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"page": "../../src/teile/SystemPrompt.svelte", "width": "100%" if narrow else "1400px"}, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css", "zustand": "../../src/lib/zustand.svelte.js"},
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
        (folder / "measure.html").write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                f"--window-size={700 if narrow else 1700},1200",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri() + ("?narrow" if narrow else ""),
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
def measured_narrow() -> dict:
    return _run_case(narrow=True)


def _close(a: float, b: float, by: float = 1.0) -> bool:
    return abs(a - b) <= by


# --- The count, the head of the list, the cards ---


def test_the_count_stands_as_a_quiet_pill_twelve_pixels_right_of_the_title(measured):
    pill = measured["pill"]
    assert "werkzeuge.aktiv_zahl" in pill["text"], pill
    assert _close(pill["pill"]["left"] - pill["title"]["right"], 12, 1.5), pill
    assert _close(pill["pill"]["cy"], pill["title"]["cy"], 2), pill
    assert pill["dot"] == "none", pill
    assert pill["colour"] == pill["leise"], pill


def test_the_list_has_a_head_with_its_name_a_line_and_the_number_of_sources(measured):
    listing = measured["list"]
    assert listing["headName"] == "werkzeuge.sources", listing
    assert listing["headCount"] == "11", listing
    assert listing["headHeight"] == "44px", listing
    assert listing["headLine"]["height"] == 1 and listing["headLine"]["width"] > 20, listing


def test_the_list_is_a_card_300_wide_with_the_right_half_24_px_beside_it(measured):
    listing = measured["list"]
    assert _close(listing["box"]["width"], 300), listing["box"]
    assert _close(listing["right"]["left"] - listing["box"]["right"], 24), listing
    assert listing["radius"] == "9px", listing
    assert listing["background"] == listing["card"], listing
    assert "inset" in listing["shadow"], listing


def test_the_cards_end_below_their_content_on_one_line_and_are_not_stretched_to_the_foot(measured):
    listing = measured["list"]
    # The list card ends 16 below its last row; it is not drawn down to the foot of the page.
    assert _close(listing["box"]["bottom"] - listing["content"]["bottom"], 16, 2), listing
    # The shorter card of the chosen entry is as high as the list, so both end on one line.
    clock = measured["right"]["werkzeuge.quelle_clock"]
    assert _close(clock["cardBox"]["bottom"], measured["list"]["box"]["bottom"], 0.5), clock["cardBox"]
    assert clock["cardBox"]["bottom"] - clock["listBottom"]["bottom"] > 24, clock


def test_a_narrow_window_puts_the_list_over_the_entry_as_wide_as_the_page(measured_narrow):
    narrow = measured_narrow
    assert narrow["direction"] == "column", narrow
    assert _close(narrow["list"]["width"], narrow["zwei"]["width"]), narrow
    assert narrow["right"]["top"] >= narrow["list"]["bottom"] - 1, narrow


def test_silence_the_other_pages_wear_no_count_pill(measured):
    other = measured["otherPage"]
    # The page really changed: a head that still names the tools page would
    # carry its pill and say nothing about the other pages.
    assert other["title"] and other["title"] != other["toolsTitle"], other
    assert other["pills"] == 0, other


# --- The rows, the arrow, the dots ---


def test_every_source_is_a_row_of_52_with_a_radius_of_8_and_the_type_of_the_design(measured):
    assert len(measured["sources"]) == 11
    for row in measured["sources"]:
        assert _close(row["box"]["height"], 52), row
        assert row["radius"] == "8px", row
        assert row["nameWeight"] == "500" and row["nameSize"] == "13px", row
        assert row["sentenceSize"] == "11px", row
        assert row["nameColour"] != row["sentenceColour"], row


def test_every_source_sign_is_18_pixels_and_centred_in_its_place(measured):
    for row in measured["sources"]:
        assert row["sign"], row["name"]
        assert _close(row["sign"]["width"], 18, 0.6) and _close(row["sign"]["height"], 18, 0.6), row
        assert _close(row["sign"]["cx"], row["signHolder"]["cx"], 0.6), row
        assert _close(row["sign"]["cy"], row["signHolder"]["cy"], 0.6), row


def test_the_dots_of_all_rows_stand_on_one_vertical_line_with_a_disc_of_10(measured):
    rights = {round(row["dot"]["right"], 1) for row in measured["sources"]}
    assert len(rights) == 1, [(r["name"], r["dot"]["right"]) for r in measured["sources"]]
    for row in measured["sources"]:
        assert _close(row["dot"]["width"], 12, 0.6), row
        assert _close(row["disc"]["width"], 10, 0.6), row


def test_the_arrow_is_14_pixels_12_right_of_the_dot_and_the_rows_without_one_keep_its_room(measured):
    foldable = [row for row in measured["sources"] if row["hasArrow"]]
    quiet = [row for row in measured["sources"] if not row["hasArrow"]]
    assert foldable and quiet, "the made-up service has both kinds of rows"
    for row in foldable:
        assert _close(row["arrow"]["width"], 14, 0.6) and _close(row["arrow"]["height"], 14, 0.6), row
        assert _close(row["arrow"]["left"] - row["dot"]["right"], 12, 1.5), row
    for row in quiet:
        assert row["hasPlace"] and _close(row["place"]["width"], 14, 0.6), row
        assert _close(row["place"]["left"] - row["dot"]["right"], 12, 1.5), row


def test_the_arrow_points_right_when_closed_and_down_when_open_and_does_not_choose(measured):
    closed, opened = measured["arrowClosed"], measured["arrowOpen"]
    assert closed["dx"] > 1 and abs(closed["dy"]) < 1, closed
    assert opened["dy"] > 1 and abs(opened["dx"]) < 1, opened
    assert measured["chosenAtStart"] is True


def test_the_tools_of_an_unfolded_source_are_36_high_and_indented_under_the_sign(measured):
    assert len(measured["unfolded"]) == 3
    for tool in measured["unfolded"]:
        assert _close(tool["height"], 36, 0.5), tool
        assert tool["left"] == 40, tool
        assert tool["radius"] == "8px", tool
    assert all(measured["unfoldedSwitches"])


def test_the_switch_of_a_tool_does_not_choose_it_but_the_row_does(measured):
    assert measured["afterSwitch"]["toolChosen"] is False, measured["afterSwitch"]
    assert measured["afterEnter"]["toolChosen"] is True, measured["afterEnter"]
    assert measured["afterEnter"]["heading"] == "read_file", measured["afterEnter"]


def test_silence_no_source_row_wears_the_fallback_chevron(measured):
    for row in measured["sources"]:
        assert row["chevronFallback"] is False, row["name"]


# --- Every built-in source and tool wears its own sign ---


def test_a_built_in_source_stands_in_a_box_of_40_with_its_sign_22_in_the_middle(measured):
    for name, right in measured["right"].items():
        if not isinstance(right, dict) or "kasten" not in right or right["kasten"] is None:
            continue
        assert _close(right["kasten"]["width"], 40) and _close(right["kasten"]["height"], 40), (name, right["kasten"])
        assert _close(right["sign"]["width"], 22, 0.6), (name, right["sign"])
        assert _close(right["sign"]["cx"], right["kasten"]["cx"], 0.6), (name, right)
        assert _close(right["sign"]["cy"], right["kasten"]["cy"], 0.6), (name, right)
        assert right["subSize"] == "12px", (name, right["subSize"])


def test_all_eight_built_in_sources_have_a_box(measured):
    boxed = [name for name, right in measured["right"].items() if isinstance(right, dict) and right.get("kasten")]
    assert len(boxed) == 8, boxed


def test_a_server_source_has_no_box_and_keeps_its_head(measured):
    server = measured["server"]
    assert server["kasten"] is False and server["chosen"] is True, server
    assert server["nameSize"] == "20px", server
    assert server["subSize"] == "12.5px", server


def test_the_built_in_sources_wear_the_signs_the_catalogue_names(measured):
    right = measured["right"]
    # The drawing tool wears the picture mark, as the tool draw_image does.
    assert right["bild.quelle"]["signHtml"] == right["bild.quelle"]["tools"]["draw_image"]["html"]
    # The schedules: a stopwatch, the same as both of their tools.
    stopwatch = right["cronjobs.quelle"]["signHtml"]
    assert 'cx="32" cy="39"' in stopwatch, stopwatch
    assert right["cronjobs.quelle"]["tools"]["cronjob"]["html"] == stopwatch
    assert right["cronjobs.quelle"]["tools"]["cron_note"]["html"] == stopwatch
    # The goals: a flag.
    flag = right["werkzeuge.quelle_goal"]["signHtml"]
    assert "M4 22V4" in flag, flag
    assert right["werkzeuge.quelle_goal"]["tools"]["goal"]["html"] == flag
    # The clock: a ring with four ticks and two hands.
    clock = right["werkzeuge.quelle_clock"]["signHtml"]
    assert 'r="22"' in clock and "M32 12v4" in clock, clock
    assert right["werkzeuge.quelle_clock"]["tools"]["get_current_time"]["html"] == clock
    # The terminal source wears the sign of the shell tool.
    terminal = right["werkzeuge.eingebaut"]
    assert terminal["signHtml"] == terminal["tools"]["run_command"]["html"]
    # The delivered files wear the page, like the tool that reads a file.
    assert right["werkzeuge.quelle_dock"]["signHtml"] == terminal["tools"]["read_file"]["html"]


def test_the_job_start_wears_the_agent_mark_and_the_video_tool_its_clapperboard(measured):
    tools = measured["right"]["werkzeuge.eingebaut"]["tools"]
    assert "M8 60 V51 Q8 42 19 39.5" in tools["start_job"]["html"], tools["start_job"]
    assert tools["start_job"]["html"] != tools["run_command"]["html"]
    video = measured["right"]["bild.quelle"]["tools"]["draw_video"]
    assert "-1.15 -0.25 26.5 26.5" in video["html"], video
    assert _close(video["svg"]["width"], 18, 0.6) and _close(video["svg"]["height"], 18, 0.6), video
    assert _close(video["svg"]["cx"], video["holder"]["cx"], 0.6), video
    assert _close(video["svg"]["cy"], video["holder"]["cy"], 0.6), video


def test_every_tool_sign_in_the_list_of_a_source_is_18_and_centred(measured):
    for name, right in measured["right"].items():
        if not isinstance(right, dict) or "tools" not in right:
            continue
        for tool, found in right["tools"].items():
            assert _close(found["svg"]["width"], 18, 0.6), (name, tool, found)
            assert _close(found["svg"]["cx"], found["holder"]["cx"], 0.6), (name, tool, found)
            assert _close(found["svg"]["cy"], found["holder"]["cy"], 0.6), (name, tool, found)
            assert "M9 6l6 6-6 6" not in found["html"], (name, tool)
