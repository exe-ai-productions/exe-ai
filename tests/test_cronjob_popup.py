"""Settings › Cronjobs: a schedule is made in the calendar and nowhere else.

The form stands in a pop-up beside the day clicked in the month (or beside
"Change"), the settings shell offers no "New cronjob" button any more, and
Escape closes the pop-up without taking the settings page with it. Read off
the source, the way the other interface tests do.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from uuid import uuid4

import pytest

# Borrowed rather than copied: the folder under node_modules is where node
# resolves the Svelte runtime the compiled module pulls in.
from tests.test_agentenampel import _pruefordner

FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src"
SEITE = (FRONTEND / "teile/SettingsCronjobs.svelte").read_text(encoding="utf-8")
FORM = (FRONTEND / "teile/ScheduleForm.svelte").read_text(encoding="utf-8")
HUELLE = (FRONTEND / "teile/SystemPrompt.svelte").read_text(encoding="utf-8")
LEISTE = (FRONTEND / "teile/ModulCronjobs.svelte").read_text(encoding="utf-8")


def test_die_seite_zeigt_den_kalender_und_oeffnet_das_formular_im_popup():
    assert "<ScheduleCalendar {kalender} gross onpick={tagGeklickt}" in SEITE
    assert 'popover="auto"' in SEITE
    # A day clicked opens the pop-up with that day's runs beside that day.
    klick = SEITE.split("function tagGeklickt(day, anker) {", 1)[1].split("\n  }\n", 1)[0]
    assert "view = { kind: 'day' }" in klick
    assert "zeigen(anker)" in klick
    # "New cronjob" at the foot of the day opens the form in the same pop-up.
    neu = SEITE.split("function newOnDay() {", 1)[1].split("\n  }\n", 1)[0]
    assert "view = { kind: 'form', entry: null }" in neu
    # The pen opens the form with the schedule, in the same pop-up.
    assert "view = { kind: 'form', entry: zeile }" in SEITE
    assert "<ScheduleForm entry={own.entry}" in SEITE


def test_escape_schliesst_nur_das_popup():
    """The window's key handler closes the settings page on Escape; the
    pop-up holds the focus and keeps the key to itself."""
    assert "onkeydown={taste}" in SEITE
    taste = SEITE.split("function taste(ev) {", 1)[1].split("\n  }\n", 1)[0]
    assert "ev.key === 'Escape'" in taste
    assert "ev.stopPropagation()" in taste
    assert "popup.focus()" in SEITE
    assert 'tabindex="-1"' in SEITE


def test_es_gibt_keinen_knopf_neuer_cronjob_mehr():
    """Only the agents page keeps the head's button."""
    assert "cronjobsTeil" not in HUELLE
    assert "istCronjobs ? cronjobsTeil" not in HUELLE
    assert "export function neu()" not in SEITE
    # Silence probe: the rail chooses a day and opens nothing.
    assert "onpick" not in LEISTE
    assert "popover" not in LEISTE


def test_art_und_wiederholung_sind_auswahlfelder():
    assert "<Auswahlfeld bind:wert={kind} eintraege={kindChoice}" in FORM
    assert "<Auswahlfeld bind:wert={repeat} eintraege={repeatChoice}" in FORM
    assert 'class="segments"' not in FORM
    # Side by side, one size: both foot buttons take half the row.
    fuss = FORM.split("  .foot {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: 1fr 1fr" in fuss


# --- the fields in the pop-up: glass with the house's field outline -------

GLOBAL = (FRONTEND / "stil/global.css").read_text(encoding="utf-8")
KALENDER = (FRONTEND / "teile/ScheduleCalendar.svelte").read_text(encoding="utf-8")
AUSWAHL = (FRONTEND / "teile/Auswahlfeld.svelte").read_text(encoding="utf-8")


def _luminance(colour: str) -> float:
    """Relative luminance of a #rrggbb colour, as the contrast formula wants it."""
    channels = []
    for i in (1, 3, 5):
        c = int(colour[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _block(selector: str) -> str:
    """The declarations of one look, by its selector — which must open exactly one block."""
    assert GLOBAL.count(selector + " {") == 1, selector
    return GLOBAL.split(selector + " {", 1)[1].split("\n}", 1)[0]


def test_die_felder_im_popup_sind_glas_mit_dem_feldrand():
    feld = FORM.split("  .field input,", 1)[1].split("}", 1)[0]
    assert "background: var(--glass-button)" in feld
    assert "border: 1px solid var(--feldstrich)" in feld
    assert "transparent" not in feld
    # No plain surface is left in the form: chips and foot buttons are glass too.
    assert "var(--bg-hoch)" not in FORM
    # The selection fields carry the same outline (glass is their one way).
    glas = AUSWAHL.split("  .feld {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid var(--feldstrich)" in glas
    # Silence probe: the day line and the month grid stay without an edge.
    assert "feldstrich" not in KALENDER


def test_der_feldrand_haelt_drei_zu_eins_auf_dem_feld_in_jedem_hellen_look():
    """Pearl, Heaven and Moune: the outline is a boundary, so it holds the
    non-text minimum of 3 : 1 against the field it surrounds."""
    for selector in (":root", ":root[data-modus='heaven']", ":root[data-modus='moune']"):
        block = _block(selector)
        edge = block.split("--feldstrich: ", 1)[1].split(";", 1)[0]
        field = block.split("--bg-hoch: ", 1)[1].split(";", 1)[0]
        assert edge.startswith("#"), (selector, edge)
        assert _contrast(edge, field) >= 3.0, (selector, edge, field, _contrast(edge, field))


def test_die_dunklen_looks_zeichnen_die_glaskante_als_feldrand():
    for selector in (
        ":root[data-modus='dunkel']",
        ":root[data-modus='darkmatter']",
        # the auto-dark copy of Exe for a device in dark mode
        ":root:not([data-modus='hell'], [data-modus='snow'], [data-eigen='hell'])",
    ):
        block = _block(selector)
        assert "--feldstrich: var(--glass-button-edge);" in block, selector


def test_die_dunklen_looks_geben_dem_datumsfeld_das_dunkle_farbschema():
    """The calendar of the "once" field is the browser's own: it follows the
    colour scheme the field carries. The looks name it — dark in every dark
    one (Exe and the own gradient when dark, Dark Matter, the auto block of a
    dark device), light in the light ones — and the form only reads it."""
    for selector in (
        ":root[data-modus='dunkel']",
        ":root[data-modus='darkmatter']",
        ":root:not([data-modus='hell'], [data-modus='snow'], [data-eigen='hell'])",
    ):
        assert "--feld-farbschema: dark;" in _block(selector), selector
    for selector in (":root", ":root[data-modus='heaven']", ":root[data-modus='moune']"):
        assert "--feld-farbschema: light;" in _block(selector), selector


def test_das_formular_liest_das_farbschema_nur_und_die_seite_bleibt_unberuehrt():
    feld = FORM.split("  .field input,", 1)[1].split("}", 1)[0]
    assert "color-scheme: var(--feld-farbschema, normal);" in feld
    assert "color-scheme: inherit" not in FORM
    # Not on the root and not on any other field: the scheme is the field's.
    declaration = re.compile(r"^\s*color-scheme\s*:", re.M)
    assert not declaration.search(GLOBAL)
    other = [
        path.name
        for path in FRONTEND.rglob("*.svelte")
        if path.name != "ScheduleForm.svelte" and declaration.search(path.read_text(encoding="utf-8"))
    ]
    assert other == []


# --- the pop-up follows what opened it -------------------------------------

ROOT = Path(__file__).resolve().parent.parent
PLACE = ROOT / "frontend" / "src" / "lib" / "popupPlace.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="no Node on this machine"
)


def _place(cases: list[dict]) -> list[dict]:
    """Run `popupPlace` (the pure module) over the cases, in Node."""
    driver = ROOT / "frontend" / f"popup-place-{uuid4().hex}.mjs"
    driver.write_text(
        textwrap.dedent(
            """
            import { popupPlace } from './src/lib/popupPlace.js'
            const cases = %s
            console.log('---REPORT---' + JSON.stringify(cases.map((c) =>
              popupPlace(c.anker, c.groesse, c.fenster, c.abstand, c.rand))))
            """
        )
        % json.dumps(cases),
        encoding="utf-8",
    )
    try:
        run = subprocess.run(
            ["node", driver.name], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60
        )
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


WINDOW = {"breite": 1200, "hoehe": 800}
POPUP = {"breite": 320, "hoehe": 400}


@needs_node
def test_das_popup_steht_rechts_vom_anker_wenn_platz_ist_sonst_links():
    stelle = _place(
        [
            {"anker": {"left": 100, "right": 180, "top": 200}, "groesse": POPUP, "fenster": WINDOW},
            # No room on the right: the left of the anchor, its own width away.
            {"anker": {"left": 900, "right": 980, "top": 200}, "groesse": POPUP, "fenster": WINDOW},
        ]
    )
    assert stelle[0] == {"left": 190, "top": 200}
    assert stelle[1] == {"left": 900 - 10 - 320, "top": 200}


@needs_node
def test_das_popup_geht_nie_ueber_den_fensterrand():
    stelle = _place(
        [
            # The anchor scrolled near the foot: the pop-up stays above it.
            {"anker": {"left": 100, "right": 180, "top": 700}, "groesse": POPUP, "fenster": WINDOW},
            # The anchor scrolled out of the top: the pop-up keeps its margin.
            {"anker": {"left": 100, "right": 180, "top": -300}, "groesse": POPUP, "fenster": WINDOW},
            # No room on either side: the margin on the left holds.
            {"anker": {"left": 40, "right": 1190, "top": 100}, "groesse": POPUP, "fenster": WINDOW},
        ]
    )
    assert stelle[0] == {"left": 190, "top": 800 - 12 - 400}
    assert stelle[1] == {"left": 190, "top": 12}
    assert stelle[2]["left"] == 12


def test_das_popup_liest_den_ort_seines_ankers_bei_jedem_setzen():
    """The pop-up used to be set once from a rect read at the click; it is
    set from the element each time, and a scroll or a resize sets it again."""
    seite = SEITE
    assert "import { popupPlace } from '../lib/popupPlace.js'" in seite
    platzieren = seite.split("function platzieren() {", 1)[1].split("\n  }\n", 1)[0]
    assert "anker.getBoundingClientRect()" in platzieren
    assert "popupPlace(" in platzieren
    # No place is computed anywhere else.
    assert seite.count("popup.style.left") == 1
    nachfuehren = seite.split("window.addEventListener('scroll'", 1)[1].split("\n", 1)[0]
    assert "true)" in nachfuehren, "a scroll of any element must be heard (capture)"
    assert "window.addEventListener('resize'" in seite
    assert "window.removeEventListener('scroll'" in seite


def test_der_kalender_gibt_das_feld_selbst_weiter_und_die_leiste_bleibt_still():
    assert "onpick?.(day, ev.currentTarget)" in KALENDER
    assert "getBoundingClientRect" not in KALENDER
    # Silence probe: the rail passes no `onpick` and opens nothing.
    assert "onpick" not in LEISTE


def test_eine_geoeffnete_liste_im_formular_wird_vom_popup_nicht_abgeschnitten():
    """The pop-up scrolls inside, and what scrolls clips. The list
    "Repetition" opens over the foot of the form, so it is a popover of its
    own in the top layer: no container of the field can cut it off."""
    assert 'popover="manual"' in AUSWAHL
    assert "klapp.showPopover()" in AUSWAHL
    regel = AUSWAHL.split("\n  .klapp {", 1)[1].split("}", 1)[0]
    assert "position: fixed" in regel


# --- one calendar for the rail and the settings ----------------------------

CALENDAR_STATE = ROOT / "frontend" / "src" / "lib" / "schedulecalendar.svelte.js"
MENU_PAGE = (FRONTEND / "teile/Menueseite.svelte").read_text(encoding="utf-8")

_CALENDAR_DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const stubs = {
  'echt.mjs': "import { untrack, flush } from 'svelte/internal/client'\\nexport { untrack }\\nexport const flushSync = flush\\n",
  'api.mjs': "export const calls = []\\nexport const api = { cronjobCalendar: async (a, b) => { calls.push([a, b]); return {} } }\\n",
  'texte.mjs': "export const t = (k) => k\\nexport const texte = { sprache: 'de' }\\n",
  'agentmarke.mjs': "export const agentName = (a) => a\\n",
  'clock.mjs': "export const dayIn = () => '2026-10-13'\\nexport const partsIn = () => ({ hour: 8, minute: 0 })\\n",
  'zustand.mjs': "export const zustand = { timezone: 'Europe/Berlin' }\\n",
  'isoweek.mjs': "export const isoWeek = () => 1\\n",
}
for (const [name, code] of Object.entries(stubs)) writeFileSync(name, code)
// The counter the windows read is reactive, as in the real module: a move
// of it is what makes the calendar ask again.
writeFileSync('ereignisstrom.mjs', compileModule(
  'export const neuigkeit = $state({ termine: 0, auftraege: 0 })',
  { filename: 'ereignisstrom.svelte.js', generate: 'client' },
).js.code)
// The generated module, not the source: node resolves a plain `svelte` to
// the server build, where effects do not run.
writeFileSync('gebaut.mjs', compileModule(readFileSync(%r, 'utf-8'), {
  filename: 'schedulecalendar.svelte.js', generate: 'client',
}).js.code
  .replace("from 'svelte';", "from './echt.mjs';")
  .replace('./api.js', './api.mjs')
  .replace('./texte.svelte.js', './texte.mjs')
  .replace('./agentmarke.js', './agentmarke.mjs')
  .replace('./clock.js', './clock.mjs')
  .replace('./ereignisstrom.svelte.js', './ereignisstrom.mjs')
  .replace('./zustand.svelte.js', './zustand.mjs')
  .replace('./isoweek.js', './isoweek.mjs'))
const { kalender } = await import('./gebaut.mjs')
const { calls } = await import('./api.mjs')
const { neuigkeit } = await import('./ereignisstrom.mjs')
const { flushSync } = await import('./echt.mjs')
const settle = async () => { flushSync(); await new Promise((r) => setTimeout(r, 0)) }
const report = {}
const releaseA = kalender.hold()
await settle()
report.afterFirstFace = calls.length
const releaseB = kalender.hold()
await settle()
report.afterSecondFace = calls.length
kalender.chosen = '2026-10-14'
await settle()
report.rangeChangeLoadsOnce = calls.length
neuigkeit.termine += 1
await settle()
report.afterAnnouncement = calls.length
releaseA()
kalender.chosen = '2026-10-15'
await settle()
report.oneFaceLeftStillLoads = calls.length
releaseB()
kalender.chosen = '2026-10-16'
await settle()
report.noFaceLeftNoLoad = calls.length
const releaseC = kalender.hold()
await settle()
report.chosenAfterReopen = kalender.chosen
releaseC()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""


@needs_node
def test_one_calendar_state_loads_once_while_a_face_stands():
    with _pruefordner() as folder:
        driver = folder / "kalender.mjs"
        driver.write_text(_CALENDAR_DRIVER % str(CALENDAR_STATE), encoding="utf-8")
        run = subprocess.run(
            ["node", driver.name], cwd=folder, capture_output=True, text=True, timeout=120
        )
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    report = json.loads(run.stdout.split("---REPORT---", 1)[1].strip())
    # Two faces, one question: the second face adds none.
    assert report["afterFirstFace"] == 1
    assert report["afterSecondFace"] == 1
    # The chosen day moves the range once, and the service's announcement of
    # a changed schedule asks once.
    assert report["rangeChangeLoadsOnce"] == 2
    assert report["afterAnnouncement"] == 3
    # While one face is left the calendar still follows its range ...
    assert report["oneFaceLeftStillLoads"] == 4
    # ... and with none left nothing runs; the next face starts from today.
    assert report["noFaceLeftNoLoad"] == 4
    assert report["chosenAfterReopen"] == "2026-10-13"


def test_rail_and_settings_take_the_same_calendar_and_neither_builds_one():
    for source in (LEISTE, SEITE):
        assert "import { kalender } from '../lib/schedulecalendar.svelte.js'" in source
        assert "new Kalender()" not in source
        assert "$effect(() => kalender.hold())" in source
    assert "export const kalender = new ScheduleCalendar()" in CALENDAR_STATE.read_text(
        encoding="utf-8"
    )
    # Silence probe: the rail still knows no pop-up and no script choice.
    assert "popover" not in LEISTE
    assert "skriptwahl" not in LEISTE


def test_a_change_in_the_settings_leaves_the_calendar_to_the_announcement():
    """One way: the service announces every change of a schedule, the
    calendar asks again off that, here as in every other window. The page
    keeps what is its own: the list's quiet answers older than the change
    are dropped."""
    changed = SEITE.split("function scheduleChanged() {", 1)[1].split("\n  }\n", 1)[0]
    assert "edits += 1" in changed
    assert "kalender" not in changed
    assert "reload" not in CALENDAR_STATE.read_text(encoding="utf-8").replace("preload", "")
    for signature in ("function geschlossen(row, own = view) {", "async function umschalten(z, an) {", "async function loeschen(z) {"):
        body = SEITE.split(signature, 1)[1].split("\n  }\n", 1)[0]
        assert "scheduleChanged()" in body, signature
    # Silence probe: a hand start changes no schedule.
    hand_start = SEITE.split("async function starten(z) {", 1)[1].split("\n  }\n", 1)[0]
    assert "scheduleChanged()" not in hand_start


def test_the_window_counts_the_announcement_for_schedules_and_not_for_jobs():
    """A changed schedule moves the schedules' counter and the sidebar's own
    readout; the job list does not move with it — no run did."""
    strom = (FRONTEND / "lib/ereignisstrom.svelte.js").read_text(encoding="utf-8")
    handler = strom.split("  cron_changed: () => {", 1)[1].split("\n  },\n", 1)[0]
    assert "cronStandLaden()" in handler
    assert "neuigkeit.termine += 1" in handler
    assert "auftraegeStillLaden" not in handler
    assert "neuigkeit.auftraege" not in handler


def test_the_cronjob_page_does_not_reach_into_the_foot_with_a_negative_margin():
    regel = HUELLE.split("  .cronjobseite {", 1)[1].split("\n  }\n", 1)[0]
    assert "margin-bottom" not in regel
    assert "fillsFoot={istCronjobs || agentList}" in HUELLE
    # The frame gives the foot room back to a page that asks for it ...
    assert "class:fillsFoot" in MENU_PAGE
    gibt = MENU_PAGE.split("  .breite.fillsFoot {", 1)[1].split("}", 1)[0]
    assert "padding-bottom: 24px;" in gibt
    # ... and every other page keeps the default room.
    standard = MENU_PAGE.split("  .breite {\n    padding-top", 1)[1].split("}", 1)[0]
    assert "padding-bottom: 56px;" in standard


# --- the pop-up's six faults: Escape, cut-off list, height, late answer, day, page height ---


def test_escape_in_an_open_list_closes_only_the_list():
    """The key is the list's: the pop-up that holds the field would take an
    Escape that is not prevented as its own close request."""
    felder = AUSWAHL.split("function tasten(ereignis) {", 1)[1].split("\n  }\n", 1)[0]
    escape = felder.split("if (key === 'Escape' && offen) {", 1)[1].split("}", 1)[0]
    assert "ereignis.preventDefault()" in escape
    assert "ereignis.stopPropagation()" in escape
    such = AUSWAHL.split("function searchKeys(event) {", 1)[1].split("\n  }\n", 1)[0]
    such_escape = such.split("if (key === 'Escape') {", 1)[1].split("}", 1)[0]
    assert "event.preventDefault()" in such_escape


def test_the_open_list_stands_in_the_top_layer_and_is_sized_from_the_room():
    assert 'popover="manual"' in AUSWAHL
    assert "klapp.showPopover()" in AUSWAHL
    platz = AUSWAHL.split("function place() {", 1)[1].split("\n  }\n", 1)[0]
    assert "window.innerHeight" in platz
    assert "klapp.style.maxHeight" in platz
    # Whatever scrolls behind it, or a resized window, takes the list away.
    assert "window.addEventListener('scroll', dismiss, true)" in AUSWAHL
    assert "window.addEventListener('resize', dismiss)" in AUSWAHL
    # Silence probe: still glass, still beneath the field as the default.
    regel = AUSWAHL.split("\n  .klapp {", 1)[1].split("}", 1)[0]
    assert "var(--glass-dropdown)" in regel
    assert "position: fixed" in regel
    # Laid out only while open — a display on the closed list would show it.
    assert "display: flex" not in regel
    assert ".klapp:popover-open {" in AUSWAHL


def test_the_popup_is_at_most_as_tall_as_the_window_leaves_room_and_scrolls_inside():
    platz = SEITE.split("function platzieren() {", 1)[1].split("\n  }\n", 1)[0]
    assert "popup.style.maxHeight" in platz
    assert "window.innerHeight" in platz
    regel = SEITE.split("\n  .popup {", 1)[1].split("}", 1)[0]
    assert "overflow: hidden" in regel
    assert "overflow: visible" not in regel
    offen = SEITE.split("\n  .popup:popover-open {", 1)[1].split("}", 1)[0]
    assert "display: flex" in offen and "flex-direction: column" in offen
    # The fields scroll, the two buttons stand outside what scrolls: nothing
    # shows through behind them.
    felder = FORM.split("  .fields {", 1)[1].split("}", 1)[0]
    assert "overflow-y: auto" in felder
    assert '<div class="fields">' in FORM
    assert '  </div>\n\n  <div class="foot">' in FORM
    fuss = FORM.split("  .foot {", 1)[1].split("}", 1)[0]
    assert "position: sticky" not in fuss
    assert "flex: none" in fuss


def test_a_late_answer_closes_only_the_popup_it_came_from():
    # The form this instance was made for is an each-item keyed by the form
    # object: a `{@const own = form}` follows `form` to the next one, and the
    # late answer would close the pop-up that stands then.
    assert "{#each view ? [view] : [] as own (own)}" in SEITE
    assert "{@const own = view}" not in SEITE
    assert "onclose={(row) => geschlossen(row, own)}" in SEITE
    kopf = SEITE.split("function geschlossen(row, own = view) {", 1)[1].split("view = null", 1)[0]
    assert "if (own !== view)" in kopf
    # The saved schedule still reaches the lists.
    assert "scheduleChanged()" in kopf and "laden()" in kopf


def test_a_new_schedule_from_a_day_is_a_one_off_on_that_day():
    assert "{ ...formFromEntry(null, day), repeat: 'once' }" in FORM
    assert "repeat: 'daily' }" not in FORM
    # Silence probe: a stored schedule keeps the rhythm it has.
    assert "entry ? formFromEntry(entry, day)" in FORM


def test_the_script_wall_has_a_height_limit_and_scrolls_inside():
    regel = HUELLE.split("\n  .skriptteil {", 1)[1].split("}", 1)[0]
    assert "max-height:" in regel
    assert "overflow-y: auto" in regel
    assert "flex: none" not in regel


def test_the_form_offers_no_agent_for_every_schedule_and_sends_it():
    """An old schedule whose agent is gone cannot name it again: "No agent"
    is always among the choices, and a change to it is sent (as nothing),
    where a named agent that differs from the stored one is sent by name."""
    choice = FORM.split("const agentChoice = $derived([", 1)[1].split("])\n", 1)[0]
    assert "wert: ''" in choice
    assert "entry && initial.agent" not in choice
    aenderung = FORM.split("async function change() {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (kind === 'agent' && agent !== initial.agent) fields.agent = agent" in aenderung
    assert "agent && agent !== initial.agent" not in aenderung


def test_the_row_says_when_the_agent_file_is_broken():
    """One short sentence, with the line where the reader names one — never
    the reader's own message."""
    assert "z.agent_broken" in SEITE
    assert "t('cronjobs.agent_kaputt_zeile', { zeile: z.agent_broken_line })" in SEITE
    assert "t('cronjobs.agent_kaputt')" in SEITE
    assert "grund: z.agent_broken" not in SEITE


def _scroll_moves_field(cases: list[dict]) -> list[bool]:
    """Runs the shipped ``scrollMovesField`` of the selection field in node,
    against stood-in nodes: each case names the scrolled node, and the
    answer is whether the list would close for it."""
    import json

    source = AUSWAHL.split("  function scrollMovesField(source) {", 1)[1].split("\n  }\n", 1)[0]
    script = (
        "class FakeNode {\n"
        "  constructor(...children) { this.children = children }\n"
        "  contains(other) { return other === this || this.children.some((c) => c.contains(other)) }\n"
        "}\n"
        "globalThis.Node = FakeNode\n"
        "const feld = new FakeNode()\n"
        "const inList = new FakeNode()\n"
        "const klapp = new FakeNode(inList)\n"
        "const box = new FakeNode(feld)\n"
        "const elsewhere = new FakeNode()\n"
        "const document = new FakeNode(box, elsewhere, klapp)\n"
        "const nodes = { feld, inList, klapp, box, elsewhere, document, window: {} }\n"
        f"function scrollMovesField(source) {{{source}\n}}\n"
        f"const cases = {json.dumps(cases)}\n"
        "console.log(JSON.stringify(cases.map((c) => scrollMovesField(nodes[c.node]))))\n"
    )
    run = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


@needs_node
def test_a_scroll_elsewhere_leaves_the_open_list_standing():
    """A box that scrolls by itself — an answer being written, a log running
    along — does not hold the field: the list stays and an entry can be
    chosen. Only what moves the field takes the list away."""
    nodes = ["elsewhere", "box", "document", "inList", "klapp", "window"]
    answers = dict(zip(nodes, _scroll_moves_field([{"node": n} for n in nodes])))
    assert answers["elsewhere"] is False
    # Silence probes: the box that holds the field, and the page itself.
    assert answers["box"] is True
    assert answers["document"] is True
    # The list's own scrolling is not the field's.
    assert answers["inList"] is False
    assert answers["klapp"] is False
    # A scroll with no node as its target (the window) moves the field.
    assert answers["window"] is True


def test_the_list_closes_on_resize_and_only_a_field_moving_scroll():
    handler = AUSWAHL.split("const dismiss = (event) => {", 1)[1].split("\n    }\n", 1)[0]
    assert "event.type === 'scroll' && !scrollMovesField(event.target)" in handler
    assert "zumachen()" in handler
    assert "window.addEventListener('scroll', dismiss, true)" in AUSWAHL
    assert "window.addEventListener('resize', dismiss)" in AUSWAHL


def test_the_settings_pass_the_calendar_the_prop_it_reads_for_the_plus():
    calendar = (FRONTEND / "teile/ScheduleCalendar.svelte").read_text(encoding="utf-8")
    assert "let { kalender, gross = false, onpick = null, empty = false, onplus = null } = $props()" in calendar
    call = SEITE.split("<ScheduleCalendar", 1)[1].split("/>", 1)[0]
    assert "empty={loaded && zeilen.length === 0}" in call
    assert "leer=" not in call


def test_a_click_on_the_open_row_shuts_it_even_when_the_light_dismiss_came_first():
    waehlen = SEITE.split("function waehlen(z, ev) {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (gewaehlt === z.id) {" in waehlen
    assert "lightClosed.id === z.id && performance.now() - lightClosed.time < 300" in waehlen
    toggle = SEITE.split("function umgeschaltet(ev) {", 1)[1].split("\n  }\n", 1)[0]
    assert "lightClosed = { id: gewaehlt, time: performance.now() }" in toggle
