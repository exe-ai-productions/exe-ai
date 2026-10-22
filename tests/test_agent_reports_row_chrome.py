"""The report rows of the agents bar and the one column of both bars, measured
in a real browser.

A long title of a report ends with an ellipsis before the cross and the state
dot, never under them — also where the shell's browser gives every button
`align-items: flex-start`, which a second run of the page says in a rule of its
own; between the dot and the right edge of the card stands
the same space as between the left edge of the card and the text; and the
agents bar and the schedules bar stay one column however wide the bar is
dragged: "Active tasks" over "Reports", the calendar over the runs.

`ModulAgenten.svelte` and `ModulCronjobs.svelte` are built as shipped, with
the reports made up in the page (the service is not asked), and drawn in
headless Chrome. Skipped where there is no Chrome or no node, like the other
browser tests.
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
  import ModulAgenten from %(agents)r
  import ModulCronjobs from %(schedules)r

  let { which } = $props()
</script>

<div id="rail" style="width: 364px; height: 760px; display: flex; flex-direction: column; position: relative; overflow: hidden;">
  {#if which === 'agents'}<ModulAgenten />{:else}<ModulCronjobs />{/if}
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import { zustand } from %(zustand)r
import { leiste } from %(rail)r
import { auftragGesehen } from %(ampel)r

const which = new URLSearchParams(location.search).get('bar') || 'agents'
const stamp = (minutes) => new Date(Date.now() + minutes * 60000).toISOString()
const LONG = 'Summarise every open question about the migration of the customer database, with sources and a list of what is still missing before the cutover, and then do the same for the second database, its backups and the three smaller services that read from it'
const jobs = [
  { id: 'j6', task: 'https://example.invalid/' + 'a'.repeat(140), state: 'fertig', agent: 'a-very-long-agent-name-that-goes-on-and-on-and-on', updated_at: stamp(-2), result: 'Done.\\n\\n```md\\n# Notes\\n```\\n', work_id: 'j6' },
  { id: 'j1', task: LONG, state: 'fertig', agent: 'research', updated_at: stamp(-5), result: 'A report.', work_id: 'j1' },
  { id: 'j2', task: LONG + ' (second pass)', state: 'gescheitert', agent: 'research', updated_at: stamp(5), result: 'It failed.', work_id: 'j2' },
  { id: 'j3', task: 'Short title', state: 'fertig', agent: 'research', updated_at: stamp(-9), result: 'A report.', work_id: 'j3' },
  { id: 'j4', task: LONG.replace('Summarise', 'List'), state: 'fertig', agent: 'research', updated_at: stamp(-12), result: 'A report.', work_id: 'j4' },
  { id: 'j5', task: LONG.replace('Summarise', 'Check'), state: 'fertig', agent: 'research', updated_at: stamp(-30), result: 'A report.', work_id: 'j5' },
]
const answers = { '/agents': [], '/skills': [], '/cronjobs': [] }
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path === '/jobs' ? zustand.auftraege : path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
zustand.auftraege = jobs
window.__rail = leiste
window.__seen = auftragGesehen
window.__zustand = zustand
mount(Shell, { target: document.getElementById('wurzel'), props: { which } })
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
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const rect = (node) => {
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
for (let k = 0; k < 60 && document.querySelectorAll('.abschnitt').length === 0; k += 1) await wait(100)
await wait(400)
const measure = async (label, width) => {
  window.__rail.breite = width
  document.getElementById('rail').style.width = width + 'px'
  await wait(500)
  const card = document.querySelector('.karte.zeilen')
  const rows = Array.from(document.querySelectorAll('.bzeile'))
  report[label] = {
    width,
    sections: Array.from(document.querySelectorAll('.abschnitt')).map((s) => ({ name: s.querySelector('.tafelkopf')?.textContent.trim(), ...rect(s) })),
    columns: document.querySelectorAll('.spalte, .spalten').length,
    card: card ? rect(card) : null,
    rows: rows.map((row) => {
      const one = row.querySelector('.beins')
      const two = row.querySelector('.bzwei')
      const cross = row.querySelector('.bweg')
      const dot = row.querySelector('.bpunkt')
      return {
        text: one.textContent.trim().slice(0, 24),
        oneRect: rect(one),
        twoRect: rect(two),
        clipped: one.scrollWidth > one.clientWidth,
        twoClipped: two.scrollWidth > two.clientWidth,
        overflow: getComputedStyle(one).textOverflow,
        crossRect: rect(cross),
        dotRect: rect(dot),
        row: rect(row),
        bar: row.querySelector('.unseen-bar') ? rect(row.querySelector('.unseen-bar')) : null,
        barColour: row.querySelector('.unseen-bar') ? getComputedStyle(row.querySelector('.unseen-bar')).backgroundColor : null,
        barLabel: row.querySelector('.unseen-bar') ? row.querySelector('.unseen-bar').getAttribute('aria-label') : null,
        weight: getComputedStyle(one).fontWeight,
        chips: Array.from(row.querySelectorAll('.datei-chip')).map(rect),
        files: row.querySelector('.dateien') ? rect(row.querySelector('.dateien')) : null,
      }
    }),
  }
}
const probe = document.createElement('i')
probe.style.background = 'var(--rot)'
document.body.appendChild(probe)
report.red = getComputedStyle(probe).backgroundColor
probe.remove()
await measure('narrow', 364)
await measure('middle', 780)
await measure('widest', 900)
// Seven reports, the oldest an unseen failure: the list reaches it at once and
// offers no "less"; seen, it is five rows again with "more" for the rest.
const shown = () => ({
  rows: document.querySelectorAll('.bzeile').length,
  buttons: Array.from(document.querySelectorAll('.knopfreihe .breitknopf')).map((b) => b.textContent.trim()).filter((text) => text.startsWith('agenten.we')),
  bars: document.querySelectorAll('.unseen-bar').length,
})
const stamp = (minutes) => new Date(Date.now() + minutes * 60000).toISOString()
const done = (id, minutes) => ({ id, task: 'Done ' + id, state: 'fertig', agent: 'research', updated_at: stamp(minutes), result: 'A report.', work_id: id })
window.__zustand.auftraege = [
  ...[6, 7, 8, 9, 10, 11].map((m, k) => done('d' + k, m)),
  { id: 'f7', task: 'The seventh', state: 'gescheitert', agent: 'research', updated_at: stamp(5), result: 'It failed.', work_id: 'f7' },
]
await wait(500)
report.seven = shown()
window.__seen('f7')
await wait(500)
report.sevenSeen = shown()
// Twelve reports, the failure the seventh: the list opens down to it and "more" adds five.
const click = async (label) => {
  Array.from(document.querySelectorAll('.knopfreihe .breitknopf')).find((b) => b.textContent.trim().startsWith(label))?.click()
  await wait(400)
}
window.__zustand.auftraege = [
  ...[6, 7, 8, 9, 10, 11].map((m, k) => done('e' + k, m)),
  { id: 'g7', task: 'The seventh of twelve', state: 'gescheitert', agent: 'research', updated_at: stamp(5), result: 'It failed.', work_id: 'g7' },
  ...[1, 2, 3, 4, 3.5].map((m, k) => done('h' + k, m - 20)),
]
await wait(500)
report.twelve = shown()
await click('agenten.weitere')
report.twelveMore = shown()
await click('agenten.weniger')
report.twelveLess = shown()
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1100px; height: 800px; position: relative; }</style>
%(shell_rule)s
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


# What the shell's browser (Electron 33, Chromium 130) gives a button: the rule
# the page of the second run says before the components are mounted.
SHELL_BUTTON_RULE = "<style>button { align-items: flex-start }</style>"


def _run_case(cases: str, bar: str, shell_rule: str = "") -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-agent-rows-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {
                "agents": "../../src/teile/ModulAgenten.svelte",
                "schedules": "../../src/teile/ModulCronjobs.svelte",
            },
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "zustand": "../../src/lib/zustand.svelte.js",
                "rail": "../../src/lib/arbeitsleiste.svelte.js",
                "ampel": "../../src/lib/agentenampel.svelte.js",
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
        (folder / "measure.html").write_text(PAGE % {"cases": cases, "shell_rule": shell_rule}, encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1100,800",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri() + f"?bar={bar}",
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
def agents() -> dict:
    return _run_case(CASES, "agents")


@pytest.fixture(scope="module")
def agents_electron33() -> dict:
    return _run_case(CASES, "agents", SHELL_BUTTON_RULE)


@pytest.fixture(scope="module")
def schedules() -> dict:
    return _run_case(CASES, "schedules")


WIDTHS = ("narrow", "middle", "widest")


def _title_rows(measured: dict) -> list[dict]:
    return [row for row in measured["rows"] if row["text"] != "Short title"]


# --- One column in every width ----------------------------------------------


@pytest.mark.parametrize("label", WIDTHS)
def test_active_tasks_stand_over_reports_in_every_width(agents, label):
    measured = agents[label]
    first, second = measured["sections"]
    assert measured["columns"] == 0, "the bar folded into columns again"
    assert abs(first["x"] - second["x"]) < 1 and abs(first["right"] - second["right"]) < 1
    assert second["y"] >= first["bottom"] - 1, (label, first, second)


@pytest.mark.parametrize("label", WIDTHS)
def test_the_calendar_stands_over_the_runs_in_every_width(schedules, label):
    measured = schedules[label]
    first, second = measured["sections"]
    assert measured["columns"] == 0
    assert abs(first["x"] - second["x"]) < 1 and abs(first["right"] - second["right"]) < 1
    assert second["y"] >= first["bottom"] - 1, (label, first, second)


# --- The rows of the reports -------------------------------------------------


def _assert_long_titles_end_with_an_ellipsis(measured: dict) -> None:
    rows = _title_rows(measured)
    assert len(rows) >= 4
    for row in rows:
        assert row["clipped"] and row["overflow"] == "ellipsis", row["text"]
        assert row["oneRect"]["right"] <= row["crossRect"]["x"] + 0.5, row["text"]
        assert row["crossRect"]["right"] <= row["dotRect"]["x"] + 0.5, row["text"]


def _assert_the_space_right_of_the_dot_is_the_space_left_of_the_text(measured: dict) -> None:
    for row in measured["rows"]:
        left = row["oneRect"]["x"] - row["row"]["x"]
        right = row["row"]["right"] - row["dotRect"]["right"]
        assert abs(left - right) <= 1, (row["text"], left, right)


@pytest.mark.parametrize("label", WIDTHS)
def test_a_long_title_ends_with_an_ellipsis_before_the_cross_and_the_dot(agents, label):
    _assert_long_titles_end_with_an_ellipsis(agents[label])


@pytest.mark.parametrize("label", WIDTHS)
def test_the_space_right_of_the_dot_is_the_space_left_of_the_text(agents, label):
    _assert_the_space_right_of_the_dot_is_the_space_left_of_the_text(agents[label])


@pytest.mark.parametrize("label", WIDTHS)
def test_a_long_title_ends_with_an_ellipsis_where_the_shell_gives_buttons_flex_start(agents_electron33, label):
    _assert_long_titles_end_with_an_ellipsis(agents_electron33[label])


@pytest.mark.parametrize("label", WIDTHS)
def test_the_space_right_of_the_dot_is_the_space_left_of_the_text_where_the_shell_gives_buttons_flex_start(
    agents_electron33, label,
):
    _assert_the_space_right_of_the_dot_is_the_space_left_of_the_text(agents_electron33[label])


@pytest.mark.parametrize("label", WIDTHS)
def test_the_second_line_and_the_file_chip_stay_left_of_the_cross(agents, label):
    for row in agents[label]["rows"]:
        assert row["twoRect"]["right"] <= row["crossRect"]["x"] + 0.5, row["text"]
        for chip in row["chips"]:
            assert chip["right"] <= row["crossRect"]["x"] + 0.5, row["text"]


@pytest.mark.parametrize("label", WIDTHS)
def test_silence_a_short_title_stays_whole_and_the_bar_does_not_move_the_text(agents, label):
    measured = agents[label]
    short = next(row for row in measured["rows"] if row["text"] == "Short title")
    assert not short["clipped"]
    unseen = [row for row in measured["rows"] if row["bar"]]
    assert unseen, "the case made up no unseen failure"
    # The text stands where the padding of the row puts it, with or without the bar.
    others = [row for row in measured["rows"] if not row["bar"]]
    assert others
    for row in unseen:
        assert abs((row["oneRect"]["x"] - row["row"]["x"]) - (others[0]["oneRect"]["x"] - others[0]["row"]["x"])) <= 0.5


@pytest.mark.parametrize("label", WIDTHS)
def test_an_unseen_failure_wears_a_red_bar_and_a_strong_title(agents, label):
    measured = agents[label]
    unseen = [row for row in measured["rows"] if row["bar"]]
    assert unseen, "the case made up no unseen failure"
    for row in unseen:
        bar = row["bar"]
        assert abs(bar["x"] - row["row"]["x"]) <= 0.5, row["text"]
        assert abs(bar["width"] - 3) <= 0.5, row["text"]
        assert abs(bar["height"] - row["row"]["height"]) <= 1, row["text"]
        assert row["barColour"] == agents["red"], row["text"]
        assert row["barLabel"], row["text"]
        assert row["weight"] == "600", row["text"]
    for row in measured["rows"]:
        if not row["bar"]:
            assert row["weight"] == "400", row["text"]


def test_the_list_reaches_an_unseen_failure_behind_the_fifth_row(agents):
    seven = agents["seven"]
    assert seven["rows"] == 7 and seven["bars"] == 1, seven
    # Nothing to add and nothing to take away: no "more", no "less".
    assert seven["buttons"] == [], seven


def test_once_it_is_seen_the_list_is_five_rows_again(agents):
    seen = agents["sevenSeen"]
    assert seen["rows"] == 5 and seen["bars"] == 0, seen
    assert len(seen["buttons"]) == 1, seen


def test_with_more_reports_than_the_floor_more_adds_what_it_says_and_less_goes_back_to_the_floor(agents):
    twelve, more, less = agents["twelve"], agents["twelveMore"], agents["twelveLess"]
    # Opened down to the unseen failure, the seventh row; "more" and "less" both offered.
    assert twelve["rows"] == 7 and twelve["bars"] == 1, twelve
    assert [text.split(" ")[0] for text in twelve["buttons"]] == ["agenten.weitere"], twelve
    # "More" adds five rows, as its label says; "less" goes back to the floor, not below it.
    assert more["rows"] == 12, more
    assert less["rows"] == 7, less
