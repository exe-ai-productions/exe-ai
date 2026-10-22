"""The month of the tool surface (Cronjobs) after version B, measured in a real browser.

The month of the right-hand surface has the calendar week in a column of its
own ("KW" / "Wk"), the weekdays in two letters, every number in a circle at a
fixed place of its row with the dots of its schedules at a fixed place under
it, today as a filled circle and the chosen day as a ring, the days of the
neighbouring months pale but present, and — from four runs on — the count of
the runs where the dots stood. The tiles of Settings › Cronjobs (`gross`) and
the month of the schedule form stay as they were.

`ScheduleCalendar.svelte` takes its state as a prop, so the page hands it a
fixed month (28 September to 1 November 2026, today the 21st, chosen the
22nd) and the browser measures what is drawn. The week numbers come out of
`lib/isoweek.js`, run by node on its own. Skipped where there is no Chrome or
no node, like the other browser tests.
"""

from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import threading
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_pdf_pages_chrome as harness

ROOT = harness.ROOT
FRONTEND = harness.FRONTEND
LIB = FRONTEND / "src" / "lib"
SOURCE = (FRONTEND / "src" / "teile" / "ScheduleCalendar.svelte").read_text(encoding="utf-8")

pytestmark = harness.pytestmark

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _catalogue(language: str) -> dict:
    return json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))


# --- The calendar week --------------------------------------------------------


def _iso_weeks(days: list[str]) -> list[int]:
    script = (
        f"import {{ isoWeek }} from {json.dumps((LIB / 'isoweek.js').as_uri())}\n"
        f"console.log(JSON.stringify({json.dumps(days)}.map(isoWeek)))\n"
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    return json.loads(run.stdout)


@needs_node
def test_the_calendar_week_follows_iso_8601():
    # A Monday inside a year, the Friday that still belongs to week 53 of the
    # year before, the first Monday of a year and its first Thursday.
    days = ["2026-10-19", "2027-01-01", "2026-12-28", "2024-12-30", "2026-01-05", "2026-01-01"]
    assert _iso_weeks(days) == [43, 53, 53, 1, 2, 1]


def test_the_head_of_the_week_column_is_said_in_both_languages():
    assert _catalogue("de")["cronjobs"]["week_short"] == "KW"
    assert _catalogue("en")["cronjobs"]["week_short"] == "Wk"


def test_the_rail_names_the_weekdays_in_two_letters_and_the_form_keeps_its_own_heads():
    assert "{#each kalender.weekdayShort as head" in SOURCE
    assert "weekdayHeads" not in SOURCE
    moment = (FRONTEND / "src" / "teile" / "ScheduleMoment.svelte").read_text(encoding="utf-8")
    assert "weekdayHeads" in moment and "grid" in moment
    state = (LIB / "schedulecalendar.svelte.js").read_text(encoding="utf-8")
    assert "weekdayHeads = $derived(" in state


def test_a_day_of_the_neighbouring_month_is_no_longer_hidden():
    assert "visibility: hidden" not in SOURCE


# --- The month in the browser ---------------------------------------------------

SHELL = """<script>
  import ScheduleCalendar from '../../src/teile/ScheduleCalendar.svelte'
  import { stub } from './stub.js'
</script>

<div id="rail" style="width: 340px"><ScheduleCalendar kalender={stub()} /></div>
<div id="gross" style="width: 1000px"><ScheduleCalendar kalender={stub()} gross /></div>
"""

STUB_JS = """const pad = (n) => String(n).padStart(2, '0')
const day = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const grid = Array.from({ length: 35 }, (_, i) => day(new Date(2026, 8, 28 + i)))
const run = (colour, count = 1) => ({ colour, count, task: 'a run' })

export function stub() {
  return {
    title: 'Oktober 2026',
    shownMonth: '2026-10',
    chosen: '2026-10-22',
    today: '2026-10-21',
    grid,
    weeks: [40, 41, 42, 43, 44],
    weekdayShort: ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'],
    shaped: {
      // Two dots, none, and three dots: a day with runs and a day without.
      '2026-10-06': [run('gruen'), run('rot')],
      '2026-10-08': [run('gruen'), run('still'), run('blau')],
      // Four runs of four schedules, and one schedule that comes 24 times.
      '2026-10-14': [run('gruen'), run('gruen'), run('gruen'), run('gruen')],
      '2026-10-15': [run('still', 24)],
      // A day of the neighbouring month with a run of its own.
      '2026-11-01': [run('still')],
    },
    choose() {},
    step() {},
    toToday() {},
  }
}
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import german from '@@GERMAN@@'
import { texte } from '@@TEXTE@@'

texte.katalog = german
texte.sprache = 'de'
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 100 && document.querySelectorAll('.tag').length < 70; k += 1) await wait(100)
const box = (el) => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width / 2, cy: r.y + r.height / 2 } }
const glyph = (el) => { const range = document.createRange(); range.selectNodeContents(el); const r = range.getBoundingClientRect(); return r.y + r.height / 2 }
const days = (root) => Array.from(root.querySelectorAll('.tag'))
const named = (root, number, outside = false) => {
  const found = days(root).find((d) => d.querySelector('.n').textContent === String(number) && d.classList.contains('fremd') === outside)
  if (!found) throw new Error(`no day ${number} (neighbouring month: ${outside}) in ${root.parentElement.id}`)
  return found
}
const look = (tag) => {
  const n = tag.querySelector('.n'), c = box(n), t = box(tag)
  const after = getComputedStyle(n, '::after')
  return {
    circleTop: +(c.y - t.y).toFixed(2), circle: [+c.w.toFixed(1), +c.h.toFixed(1)], glyphOff: +(glyph(n) - c.cy).toFixed(2),
    dots: tag.querySelectorAll('.punkte i').length, count: tag.querySelector('.count')?.textContent ?? null,
    opacity: +getComputedStyle(tag).opacity, visibility: getComputedStyle(tag).visibility,
    fill: getComputedStyle(n).backgroundColor, ink: getComputedStyle(n).color, ring: parseFloat(after.borderTopWidth) || 0,
    day: t, row: t.y,
  }
}
const paint = (el) => (el ? getComputedStyle(el).color : null)
const report = {}
for (const mode of ['snow', 'dunkel']) {
  document.documentElement.setAttribute('data-modus', mode)
  await wait(100)
  const rail = document.querySelector('#rail .kalender'), gross = document.querySelector('#gross .kalender')
  report[mode] = {
    today: look(named(rail, 21)), chosen: look(named(rail, 22)), plain: look(named(rail, 23)),
    grossToday: look(named(gross, 21)),
  }
}
document.documentElement.setAttribute('data-modus', 'dunkel')
const rail = document.querySelector('#rail .kalender'), gross = document.querySelector('#gross .kalender')
Object.assign(report, {
  weekHead: rail.querySelector('.kopfkw')?.textContent,
  weeks: Array.from(rail.querySelectorAll('.kw:not(.kopfkw)')).map((k) => k.textContent),
  weekdays: Array.from(rail.querySelectorAll('.wt')).map((w) => w.textContent),
  weekendHeads: Array.from(rail.querySelectorAll('.wt.weekend')).map((w) => w.textContent),
  weekendColour: [paint(rail.querySelector('.wt.weekend')), paint(rail.querySelectorAll('.wt')[0])],
  weekendBand: [getComputedStyle(named(rail, 3)).backgroundColor, getComputedStyle(named(rail, 7)).backgroundColor],
  withRuns: look(named(rail, 6)), threeDots: look(named(rail, 8)), without: look(named(rail, 9)),
  four: look(named(rail, 14)), many: look(named(rail, 15)), outside: look(named(rail, 1, true)),
  todayButton: Array.from(rail.querySelectorAll('.datum button')).map((b) => b.textContent.trim()).filter(Boolean),
  railWeekCells: rail.querySelectorAll('.kw').length,
  gross: {
    weekCells: gross.querySelectorAll('.kw').length, count: gross.querySelectorAll('.count').length,
    tile: look(named(gross, 6)), outside: look(named(gross, 1, true)),
    names: gross.querySelectorAll('.names').length, weekdays: Array.from(gross.querySelectorAll('.wt')).map((w) => w.textContent),
  },
  rowSpacing: [box(named(rail, 6)).y - box(named(rail, 1)).y, box(named(rail, 13)).y - box(named(rail, 6)).y],
})
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _run() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-schedule-rail-{uuid4().hex}"
    folder.mkdir(parents=True)
    server = None
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "stub.js").write_text(STUB_JS, encoding="utf-8")
        entry = (
            ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
            .replace("@@TEXTE@@", "../../src/lib/texte.svelte.js")
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
        (folder / "measure.html").write_text(
            harness.PAGE % {"cases": CASES, "links": links}, encoding="utf-8"
        )
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
                "--window-size=1400,900", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", f"http://127.0.0.1:{web_port}/measure.html",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return harness.asyncio.run(harness._drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        if server:
            server.shutdown()
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def report() -> dict:
    return _run()


def test_the_month_has_the_week_column_with_its_head_and_the_numbers_of_the_weeks(report):
    assert report["weekHead"] == "KW"
    assert report["weeks"] == ["40", "41", "42", "43", "44"]
    assert report["railWeekCells"] == 6


def test_the_weekdays_have_two_letters_and_the_weekend_is_quieter(report):
    assert report["weekdays"] == ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    assert report["weekendHeads"] == ["Sa", "So"]
    weekend, workday = report["weekendColour"]
    assert weekend != workday
    # The weekend days lie on a faint surface the workdays lack.
    band, plain = report["weekendBand"]
    assert band != plain and plain in ("rgba(0, 0, 0, 0)", "transparent")


def test_every_number_stands_in_a_circle_at_the_same_place_of_its_row(report):
    for name in ("withRuns", "threeDots", "without", "four", "many", "outside"):
        day = report[name]
        assert day["circle"] == [26.0, 26.0], (name, day)
        assert day["circleTop"] == 5, (name, day)
        # The number sits in the middle of its circle, with or without runs.
        assert abs(day["glyphOff"]) <= 1, (name, day)


def test_the_dots_have_their_place_and_four_runs_say_how_many_instead(report):
    assert (report["withRuns"]["dots"], report["withRuns"]["count"]) == (2, None)
    assert (report["threeDots"]["dots"], report["threeDots"]["count"]) == (3, None)
    assert (report["without"]["dots"], report["without"]["count"]) == (0, None)
    # Four runs of four schedules, and one schedule that comes 24 times.
    assert (report["four"]["dots"], report["four"]["count"]) == (0, "4")
    assert (report["many"]["dots"], report["many"]["count"]) == (0, "24")


@pytest.mark.parametrize("mode", ["snow", "dunkel"])
def test_today_is_a_filled_circle_and_the_chosen_day_a_ring_in_a_light_and_a_dark_look(report, mode):
    today, chosen, plain = report[mode]["today"], report[mode]["chosen"], report[mode]["plain"]
    assert today["fill"] not in ("rgba(0, 0, 0, 0)", "transparent"), today
    assert today["fill"] != today["ink"], today
    assert today["circle"] == chosen["circle"] == plain["circle"] == [26.0, 26.0]
    assert chosen["ring"] > 0 and plain["ring"] == 0 and today["ring"] == 0
    assert chosen["fill"] in ("rgba(0, 0, 0, 0)", "transparent"), chosen


def test_the_days_of_the_neighbouring_months_are_pale_but_there(report):
    outside = report["outside"]
    assert outside["visibility"] == "visible"
    assert 0 < outside["opacity"] < 0.5
    assert outside["dots"] == 1


def test_the_date_row_says_today_and_the_rows_keep_their_distance(report):
    assert "Heute" in report["todayButton"]
    # A row is 40 px high and the rows stand 2 px apart.
    assert report["rowSpacing"] == [42, 42], report["rowSpacing"]


def test_silence_the_tiles_of_the_settings_stay_as_they_were(report):
    gross = report["gross"]
    assert gross["weekCells"] == 0 and gross["count"] == 0
    assert gross["names"] > 0
    assert gross["tile"]["day"]["h"] >= 100
    assert gross["outside"]["visibility"] == "visible" and gross["outside"]["opacity"] == 0.45
    assert gross["weekdays"] == ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    # Today stays an outlined number in the tile, not a filled circle.
    for mode in ("snow", "dunkel"):
        assert report[mode]["grossToday"]["fill"] in ("rgba(0, 0, 0, 0)", "transparent")
