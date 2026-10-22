"""The info marks on the pages Notifications and Skills, measured in a real browser.

`Meldewahl.svelte` and `Skillmaske.svelte` are built as shipped and drawn in
headless Chrome with the answers of the service made up in the page: two
skills in the list. The page reports, for the Notifications page: fifteen
marks (the four occurrences stand twice: once with the sound, once in the
block of the popups), each 14 by 14 px, 6 px after the name and centred on its line; none
beside the volume and the display duration. Pressed one after the other, each
shows its approved sentence, first in English, then (the catalogue switched)
in German. For the Skills page: one mark, beside "Load skills automatically",
none beside the rows of the skills. And what stays: a press on a mark
switches no switch and calls no route, and no row carries a line under its
name.

The build of the harness links the built stylesheet, so every size probe
reads the real tokens.

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
LOCALES = ROOT / "app" / "locales"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

# The approved sentences (English, German), in the order of the pages. The
# English one of the agent / cronjob row names "Failed", the page's own word.
SENTENCES = {
    'meldewesen.info_toene': (
        'Turns all notification sounds on or off. The Sound column below determines which events play a sound.',
        'Aktiviert oder deaktiviert alle Benachrichtigungstöne. In der Spalte „Ton“ unten wird festgelegt, bei welchen Ereignissen ein Ton abgespielt wird.',
    ),
    'meldewesen.info_nur_hintergrund': (
        'Plays sounds only when Exe AI is not in the foreground, e.g., when minimized or behind another window. Test buttons always play.',
        'Spielt Töne nur ab, wenn Exe AI nicht im Vordergrund ist, z. B. wenn das Fenster minimiert oder verdeckt ist. Test-Schaltflächen geben immer Töne aus.',
    ),
    'meldewesen.info_fertig': (
        'A chat has finished responding while you were in a different chat or program.',
        'Ein Chat hat seine Antwort fertiggestellt, während ein anderer Chat oder ein anderes Programm aktiv war.',
    ),
    'meldewesen.info_wartet': (
        'Exe AI needs your attention: a question, a pending tool call approval, or an agent inquiry.',
        'Exe AI braucht Aufmerksamkeit: eine Frage, ein zu bestätigender Werkzeugaufruf oder eine Agentenanfrage.',
    ),
    'meldewesen.info_fehler': (
        'An error occurred: a run failed or stopped, or an item could not be saved or loaded.',
        'Ein Fehler ist aufgetreten: Ein Lauf ist fehlgeschlagen oder wurde abgebrochen, oder Daten konnten nicht gespeichert bzw. geladen werden.',
    ),
    'meldewesen.info_agent_cronjob': (
        'An agent or cronjob run completed successfully. Failed runs are categorized under Failed.',
        'Ein Agenten- oder Cronjob-Lauf wurde erfolgreich beendet. Fehlgeschlagene Läufe fallen unter „Fehler“.',
    ),
    'meldewesen.info_popups_aus': (
        'Hides all notification cards. Sounds and indicators retain their individual settings.',
        'Blendet alle Benachrichtigungskarten aus. Töne und Indikatoren behalten ihre jeweiligen Schalter bei.',
    ),
    'meldewesen.info_punkt_agenten': (
        'Pulses the dot at the Agents icon when a run is finished, waiting for input, or failed. When disabled, the dot retains its color and remains static.',
        'Lässt den Punkt am Agenten-Symbol pulsieren, wenn ein Lauf beendet ist, auf Eingaben wartet oder fehlgeschlagen ist. Im inaktiven Zustand behält er seine Farbe und steht still.',
    ),
    'meldewesen.info_punkt_cronjob': (
        'Pulses the dot at the Cronjobs icon when a run is finished, waiting for input, or failed. When disabled, the dot retains its color and remains static.',
        'Lässt den Punkt am Cronjob-Symbol pulsieren, wenn ein Lauf beendet ist, auf Eingaben wartet oder fehlgeschlagen ist. Im inaktiven Zustand behält er seine Farbe und steht still.',
    ),
    'meldewesen.info_punkt_terminal': (
        'Pulses the terminal dots when a command is finished, waiting for input, or failed. When disabled, they retain their color and remain static.',
        'Lässt die Terminal-Punkte pulsieren, wenn ein Befehl beendet ist, auf Eingaben wartet oder fehlgeschlagen ist. Im inaktiven Zustand behalten sie ihre Farbe und stehen still.',
    ),
    'meldewesen.info_punkt_chat': (
        'Pulses the dots of your chats in the list and of tool calls within a chat. When disabled, they retain their color and remain static.',
        'Lässt die Punkte der Chats in der Liste sowie der Werkzeugaufrufe im Chat pulsieren. Im inaktiven Zustand behalten sie ihre Farbe und stehen still.',
    ),
    'skills.info_selbst': (
        'Allows the model to select skills automatically without explicit invocation. Each available skill adds a line to requests; direct calls by name incur no overhead.',
        'Ermöglicht dem Modell die automatische Auswahl von Skills, ohne dass sie ausdrücklich aufgerufen werden. Jeder verfügbare Skill fügt der Anfrage eine Zeile hinzu; ein direkter Aufruf per Name verursacht keinen Mehraufwand.',
    ),
}

NOTIFICATION_NAMES = [
    "Sounds", "Sounds only in the background", "Done", "Waiting", "Failed", "Agent / Cronjob",
    "Disable popups", "Done", "Waiting", "Failed", "Agent / Cronjob", "Agents indicator", "Cronjob indicator", "Terminal indicator", "Chat indicator",
]

SHELL = """<script>
  import Meldewahl from %(meldewahl)r
  import Skillmaske from %(skillmaske)r
</script>

<div style="width: 900px; padding: 20px;">
  <div id="meld"><Meldewahl /></div>
  <div id="skills"><Skillmaske /></div>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import german from %(german)r
import { texte } from %(texts)r

texte.sprache = 'en'
texte.katalog = english
const skills = [
  { name: 'alpha', beschreibung: 'First skill', mitgeliefert: true, eigen: false, auto: true },
  { name: 'beta', beschreibung: 'Second skill', mitgeliefert: false, eigen: true, auto: false },
]
window.calls = []
window.fetch = async (address, options = {}) => {
  const full = String(address)
  const path = full.replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const method = (options.method || 'GET').toUpperCase()
  if (method !== 'GET') window.calls.push(method + ' ' + path)
  const body = path === '/skills/verwaltung' ? skills : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
window.texte = texte
window.english = english
window.german = german
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
const meld = document.getElementById('meld')
const skills = document.getElementById('skills')
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
const round = (value) => Math.round(value * 10) / 10
for (let k = 0; k < 60 && skills.querySelectorAll('.zeile').length !== 2; k += 1) await wait(100)
if (skills.querySelectorAll('.zeile').length !== 2) throw new Error('the skill list did not render its two rows')
await wait(500)

const holderOf = (mark) => mark.closest('.zeilentext, .beschriftung')
const marksOf = (root) => Array.from(root.querySelectorAll('.mark'))
const switchStates = () => Array.from(document.querySelectorAll('[role=switch]')).map((s) => s.getAttribute('aria-checked'))
const label = (holder) => Array.from(holder.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim()
const measure = (mark) => {
  const holder = holderOf(mark)
  const nameNode = Array.from(holder.childNodes).find((n) => n.nodeType === 3)
  const range = document.createRange()
  range.selectNodeContents(nameNode)
  const name = range.getBoundingClientRect()
  const box = mark.getBoundingClientRect()
  return {
    label: label(holder),
    width: round(box.width), height: round(box.height),
    gap: round(box.left - name.right),
    off: round(Math.abs(box.top + box.height / 2 - (name.top + name.height / 2))),
  }
}
const sentences = async (root) => {
  const found = []
  for (const mark of marksOf(root)) {
    mark.click()
    await wait(60)
    const holder = holderOf(mark)
    const bubble = holder.querySelector('.bubble')
    found.push({
      label: label(holder), sentence: text(bubble),
      below: bubble ? bubble.getBoundingClientRect().top >= holder.querySelector('.mark').getBoundingClientRect().bottom - 1 : false,
    })
  }
  document.body.click()
  await wait(60)
  return found
}

const report = {}
report.closedBubbles = document.querySelectorAll('.bubble').length
report.meld = marksOf(meld).map(measure)
report.skills = marksOf(skills).map(measure)
report.skillMarkInHead = marksOf(skills).every((m) => m.closest('.schalterzeile'))
report.skillRowMarks = Array.from(skills.querySelectorAll('.zeile')).reduce((n, row) => n + row.querySelectorAll('.mark').length, 0)
const rowOf = (node) => node.closest('.einstellkachel')
report.volumeMarks = rowOf(meld.querySelector('.regler')).querySelectorAll('.mark').length
report.durationMarks = rowOf(meld.querySelector('.einheit')).querySelectorAll('.mark').length
report.rowLines = Array.from(document.querySelectorAll('.zeilentext, .beschriftung')).map((h) => text(h) === label(h))
const before = switchStates()
report.english = [...(await sentences(meld)), ...(await sentences(skills))]
texte.sprache = 'de'
texte.katalog = german
await wait(100)
report.german = [...(await sentences(meld)), ...(await sentences(skills))]
report.switchesStay = JSON.stringify(before) === JSON.stringify(switchStates())
report.calls = window.calls
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


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-info-marks-notifications-skills-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {
                "meldewahl": "../../src/teile/Meldewahl.svelte",
                "skillmaske": "../../src/teile/Skillmaske.svelte",
            },
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "german": "../../../app/locales/de.json",
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
            PAGE % {"cases": CASES, "links": links}, encoding="utf-8"
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
                (folder / "measure.html").as_uri(),
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


def _catalogue(language: str) -> dict:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))


def test_the_notifications_page_has_fifteen_marks_14_px_wide_6_px_after_the_name_and_centred(measured):
    marks = measured["meld"]
    assert [mark["label"] for mark in marks] == NOTIFICATION_NAMES, marks
    for mark in marks:
        assert mark["width"] == 14 and mark["height"] == 14, mark
        assert abs(mark["gap"] - 6) <= 0.5, mark
        assert mark["off"] <= 1, mark


def test_every_mark_shows_its_approved_sentence_in_english_and_then_in_german(measured):
    for language, index in (("english", 0), ("german", 1)):
        shown = {row["label"]: row for row in measured[language]}
        assert len(measured[language]) == 16, measured[language]
        sentences = [row["sentence"] for row in measured[language]]
        keys = list(SENTENCES)
        # The four occurrences are read twice: with the sound and in the popup block.
        at = keys.index("meldewesen.info_popups_aus") + 1
        keys[at:at] = keys[keys.index("meldewesen.info_fertig"):keys.index("meldewesen.info_popups_aus")]
        assert sentences == [SENTENCES[key][index] for key in keys], (language, sentences)
        assert all(row["below"] for row in shown.values()), shown


def test_the_skills_page_has_one_mark_beside_the_switch_name_and_none_on_the_skill_rows(measured):
    assert len(measured["skills"]) == 1, measured["skills"]
    mark = measured["skills"][0]
    assert mark["label"] == "Load skills automatically", mark
    assert mark["width"] == 14 and mark["height"] == 14 and abs(mark["gap"] - 6) <= 0.5 and mark["off"] <= 1, mark
    assert measured["skillMarkInHead"] and measured["skillRowMarks"] == 0, measured


def test_the_volume_and_the_display_duration_carry_no_mark(measured):
    assert measured["volumeMarks"] == 0 and measured["durationMarks"] == 0, measured


def test_every_key_is_in_both_catalogues_with_the_approved_sentence():
    english, german = _catalogue("en"), _catalogue("de")
    for key, (en, de) in SENTENCES.items():
        group, name = key.split(".")
        assert english[group][name] == en, key
        assert german[group][name] == de, key
    assert "Failed runs are categorized under Failed." in english["meldewesen"]["info_agent_cronjob"]


def test_silence_a_press_switches_nothing_calls_nothing_and_no_row_gets_a_second_line(measured):
    assert measured["switchesStay"] is True, measured
    assert measured["calls"] == [], measured["calls"]
    assert measured["closedBubbles"] == 0, measured
    assert all(measured["rowLines"]), measured["rowLines"]
